# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Report module - builds and exports the artefacts of a run.
Runs as a thread of the Core process. CORE forwards the run events here
"""

import csv
import html
import json
import time
from pathlib import Path
from typing import IO

from pypts.config_handler import ConfigHandler
from pypts.logger.log import log
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.common_messages import ResultType
from pypts.messages.core_report_communication import (
    CoreToReport,
    ExportReport,
    GenerateReport,
    ReportGenerated,
    ReportStopped,
    ReportToCore,
    StopReport,
)
from pypts.messages.run_events import RunFinished, RunStarted, SequenceStarted, StepExecuted
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import REPORT, HeartbeatManager

#: The name CORE knows this module by, and the `source` on its heartbeats.
#: Imported rather than spelled again
MODULE_NAME = REPORT

#: One flat row per executed step
CSV_COLUMNS = (
    "recipe_name",
    "sequence_name",
    "step_name",
    "step_id",
    "step_type",
    "result",
    "inputs",
    "outputs",
    "error_info",
    "started_at",
    "duration_s",
)


def report_main(
    to_core: QueueWrapper[ReportToCore],
    from_core: QueueWrapper[CoreToReport],
) -> None:
    """
    Entry point called by CORE. Runs on the Report thread.
    """
    Report(to_core, from_core).start()


class Report:
    """
    Attributes:
        core: outbox to CORE
        inbox: commands from CORE.
        output_dir: where the run folders go, from the configuration.
        run_dir: the folder of the run in progress (or just finished), or None
              before the first run.
        csv_file: the open, growing report.csv, or None outside a run.
        rows: what has been written to the CSV, kept for the HTML pass.
        run_info: the RunStarted of the current run.`
        run_result: the RunFinished verdict, or None while the run is going.
        current_sequence: the sequence name stamped on the rows being written.
    """

    def __init__(
        self,
        to_core: QueueWrapper[ReportToCore],
        from_core: QueueWrapper[CoreToReport],
        output_dir: Path | None = None,
    ) -> None:
        self.core = to_core
        self.inbox = from_core
        self.running = True
        self.heartbeat_manager = HeartbeatManager(self.core, MODULE_NAME)
        if output_dir is not None:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = ConfigHandler().get_parameter("paths.reports_dir")

        self.run_dir: Path | None = None
        self.csv_file: IO[str] | None = None
        self.csv_writer: csv.DictWriter | None = None
        self.rows: list[dict[str, str]] = []
        self.run_info: RunStarted | None = None
        self.run_result: ResultType | None = None
        self.current_sequence = ""

    @catch_and_report_errors()
    def start(self) -> None:
        log.info("Starting module.")
        log.info("Reports will be written to: %s", self.output_dir)
        self.main_loop()
        log.info("Module stopped.")

    @catch_and_report_errors()
    def main_loop(self) -> None:
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("Left main event loop.")

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)

    @catch_and_report_errors()
    def handle_core_message(self, message: CoreToReport) -> None:
        match message:
            case RunStarted():
                self.start_run(message)
            case SequenceStarted(sequence_name=sequence_name):
                self.current_sequence = sequence_name
            case StepExecuted():
                self.record_step(message)
            case RunFinished(result=result):
                self.finish_run(result)
            case GenerateReport():
                self.generate_report()
            case ExportReport():
                self.export_report()
            case StopReport():
                self.stop()
            case _:
                unhandled(message)

    # --- The incremental CSV --------------------------------------------------

    @catch_and_report_errors()
    def start_run(self, event: RunStarted) -> None:
        """Open this run's folder and its CSV, header written and flushed."""
        # Clear the previous run's state first: if make_run_dir() raises below,
        # the decorator swallows it, and stale state would silently attribute
        # this run's verdict and HTML to the previous run's folder.
        self.close_csv()
        self.run_dir = None
        self.run_info = None
        self.run_result = None
        self.rows = []
        self.current_sequence = ""

        self.run_dir = self.make_run_dir(event.recipe_name)
        self.run_info = event

        csv_path = self.run_dir / "report.csv"
        # SIM115 silenced because the file *must* outlive this method: it
        # grows for the whole run, and close_csv() owns the close.
        self.csv_file = open(csv_path, "w", newline="", encoding="utf-8")  # noqa: SIM115
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=list(CSV_COLUMNS))
        self.csv_writer.writeheader()
        self.csv_file.flush()
        log.info("Recording run results to: %s", csv_path)

    def make_run_dir(self, recipe_name: str) -> Path:
        """
        One folder per run: <reports_dir>/<timestamp>_<recipe name>.
        """
        safe_name = "".join(c if c.isalnum() else "_" for c in recipe_name)[:60]
        if not safe_name:
            safe_name = "recipe"
        base = time.strftime("%Y%m%d_%H%M%S", time.localtime()) + "_" + safe_name
        run_dir = self.output_dir / base
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = self.output_dir / f"{base}_{suffix}"
        run_dir.mkdir(parents=True)
        return run_dir

    @catch_and_report_errors()
    def record_step(self, event: StepExecuted) -> None:
        """
        Append one row for one executed step, flushed immediately.
        """
        if self.csv_writer is None or self.csv_file is None:
            log.warning(
                "Dropping a step record with no run open: %s", event.outcome.step_name
            )
            return
        recipe_name = self.run_info.recipe_name if self.run_info is not None else ""
        row = {
            "recipe_name": recipe_name,
            "sequence_name": self.current_sequence,
            "step_name": event.outcome.step_name,
            "step_id": str(event.outcome.step_id),
            "step_type": event.step_type,
            "result": str(event.outcome.result),
            "inputs": json.dumps(event.inputs, default=str),
            "outputs": json.dumps(event.outputs, default=str),
            "error_info": event.outcome.error_info,
            "started_at": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(event.started_at)
            ),
            "duration_s": str(event.duration_s),
        }
        self.csv_writer.writerow(row)
        self.csv_file.flush()
        self.rows.append(row)

    @catch_and_report_errors()
    def finish_run(self, result: ResultType) -> None:
        """The run is over: keep its verdict, close its CSV."""
        if self.run_dir is None:
            log.warning("RunFinished with no run open; nothing to close.")
            return
        self.run_result = result
        self.close_csv()

    def close_csv(self) -> None:
        if self.csv_file is not None:
            self.csv_file.close()
        self.csv_file = None
        self.csv_writer = None

    # --- Generation -----------------------------------------------------------

    @catch_and_report_errors()
    def generate_report(self) -> None:
        """
        Build report.html from the recorded rows
        """
        if self.run_dir is None or self.run_info is None:
            log.warning("Cannot generate: no run has been recorded.")
            return
        self.close_csv()
        html_path = self.run_dir / "report.html"
        html_path.write_text(self.render_html(), encoding="utf-8")
        log.info("Report generated: %s", html_path)
        self.core.send(ReportGenerated(report_path=str(html_path)))

    def render_html(self) -> str:
        """The whole report as one self-contained page: header, summary, table."""
        assert self.run_info is not None  # guarded by generate_report()
        title = html.escape(self.run_info.recipe_name)
        description = html.escape(self.run_info.recipe_description)
        if self.run_result is not None:
            verdict = str(self.run_result)
        else:
            verdict = "in progress"
        generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row["result"]] = counts.get(row["result"], 0) + 1
        summary = ", ".join(f"{result}: {count}" for result, count in sorted(counts.items()))
        if not summary:
            summary = "no steps ran"

        table_rows = []
        for row in self.rows:
            cells = "".join(
                f"<td>{html.escape(row[column])}</td>"
                for column in (
                    "sequence_name",
                    "step_name",
                    "step_type",
                    "result",
                    "duration_s",
                    "inputs",
                    "outputs",
                    "error_info",
                )
            )
            table_rows.append(f'<tr class="{html.escape(row["result"])}">{cells}</tr>')
        steps_html = "\n".join(table_rows)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pypts report - {title}</title>
<style>
body {{ font-family: sans-serif; margin: 2em; color: #222; background: #fff; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left;
          font-size: 0.9em; word-break: break-word; }}
th {{ background: #eee; }}
tr.PASS td, tr.DONE td {{ background: #e6f4e6; }}
tr.FAIL td {{ background: #f9e0e0; }}
tr.ERROR td {{ background: #fbe9d0; }}
tr.SKIP td {{ background: #f0f0f0; color: #777; }}
tr.STOP td {{ background: #ece0f4; }}
</style>
</head>
<body>
<h1>pypts Test Report</h1>
<p><strong>Recipe:</strong> {title}<br>
<strong>Description:</strong> {description}<br>
<strong>Result:</strong> {verdict}<br>
<strong>Generated:</strong> {generated_at}</p>
<h2>Summary</h2>
<p>{len(self.rows)} steps ({summary})</p>
<h2>Steps</h2>
<table>
<tr><th>Sequence</th><th>Step</th><th>Type</th><th>Result</th><th>Duration [s]</th>
<th>Inputs</th><th>Outputs</th><th>Error</th></tr>
{steps_html}
</table>
</body>
</html>
"""

    @catch_and_report_errors()
    def export_report(self) -> None:
        """
        Write the generated report out in another format.
        Not implemented yet
        """
        log.warning("Cannot export: report export is not implemented.")

    # --- Housekeeping ---------------------------------------------------------

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self) -> None:
        self.running = False
        self.close_csv()
        log.info("Stopping module.")
        self.core.send(ReportStopped())
