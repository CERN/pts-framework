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
from pypts.messages.run_events import (
    RunFinished,
    RunMetadata,
    RunStarted,
    SequenceStarted,
    StepExecuted,
)
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import REPORT, HeartbeatManager

#: The name CORE knows this module by, and the `source` on its heartbeats.
#: Imported rather than spelled again
MODULE_NAME = REPORT

#: One flat row per executed step. report.csv is the whole record of a run -
#: there is no second file - so the run-level facts are repeated on every row
#: rather than kept somewhere else. `recipe_name` always worked this way; the
#: rest joined it when report.html stopped needing anything but the CSV.
#:
#: The recipe's `report_metadata` names are appended to these at run start,
#: which is why the full set is computed per run rather than being a constant.
RUN_COLUMNS = (
    "recipe_name",
    "recipe_description",
    "recipe_version",
    "pypts_version",
    "run_started_at",
    "run_result",
)

STEP_COLUMNS = (
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

#: The columns of a run that declares no metadata. Kept as a name because the
#: tests and the HTML pass both read it.
CSV_COLUMNS = RUN_COLUMNS + STEP_COLUMNS


def columns_for(metadata_names: tuple[str, ...]) -> tuple[str, ...]:
    """The header row of one run: the run-level columns, its metadata, the step ones."""
    return RUN_COLUMNS + tuple(metadata_names) + STEP_COLUMNS


def safe_name_part(value: str) -> str:
    """One folder-name component: alphanumerics kept, everything else an underscore."""
    return "".join(c if c.isalnum() else "_" for c in value)[:60]


def rows_from_csv(csv_path: Path) -> list[dict[str, str]]:
    """
    Read a past run's report.csv back into rows.

    What makes report.html regenerable from the CSV alone: every run-level
    value the header block shows is on every row, so nothing else has to be
    kept. A run in which no step executed writes a header and no rows, and
    has nothing to regenerate from.
    """
    with open(csv_path, newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


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
        metadata: the run's metadata globals as they stand - what the recipe
              named in `report_metadata`, filled in as the run learns them.
        columns: this run's CSV header, the metadata names included.
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
        self.metadata: dict[str, str] = {}
        self.columns: tuple[str, ...] = CSV_COLUMNS
        self.run_started_at = ""

    @catch_and_report_errors()
    def start(self) -> None:
        log.debug("REPORT module starting.")
        log.debug("Reports will be written under %s.", self.output_dir)
        log.info("REPORT module started.")
        self.main_loop()
        log.info("REPORT module stopped.")

    @catch_and_report_errors()
    def main_loop(self) -> None:
        log.debug("REPORT entered its main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.debug("REPORT left its main event loop.")

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
            case RunMetadata(values=values):
                self.record_metadata(values)
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
        self.metadata = {}
        self.run_started_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        self.run_dir = self.make_run_dir(event.recipe_name)
        self.run_info = event
        # The names are known now even though the values are not, which is what
        # lets the header row be written once and stay correct for the run.
        self.columns = columns_for(event.metadata_names)

        csv_path = self.run_dir / "report.csv"
        # SIM115 silenced because the file *must* outlive this method: it
        # grows for the whole run, and close_csv() owns the close.
        self.csv_file = open(csv_path, "w", newline="", encoding="utf-8")  # noqa: SIM115
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=list(self.columns))
        self.csv_writer.writeheader()
        self.csv_file.flush()
        # One of the three paths logging_rules.md keeps at INFO: the operator has to
        # be able to find the run's files without asking anyone.
        log.info("Results will be written to: %s", self.run_dir)
        log.debug("The run's CSV is %s with columns %s.", csv_path, ", ".join(self.columns))

    def make_run_dir(self, recipe_name: str) -> Path:
        """
        One folder per run: <reports_dir>/<timestamp>_<recipe name>.
        """
        safe_name = safe_name_part(recipe_name)
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
                "Step '%s' could not be added to the results file.", event.outcome.step_name
            )
            log.debug("No run is open, so there is no CSV writer to append to.")
            return
        row = self.run_level_cells()
        row.update(
            {
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
        )
        self.csv_writer.writerow(row)
        self.csv_file.flush()
        self.rows.append(row)

    def run_level_cells(self) -> dict[str, str]:
        """
        The run-level half of a row, as it stands right now.

        `run_result` is empty until the run ends and a metadata value is empty
        until the run learns it, so a row written early carries blanks.
        finish_run() rewrites the file once, backfilled, so the CSV that is
        left behind has them on every row - and a run that crashed keeps
        whatever it had flushed, which is the point of writing as it goes.
        """
        info = self.run_info
        cells = {
            "recipe_name": info.recipe_name if info is not None else "",
            "recipe_description": info.recipe_description if info is not None else "",
            "recipe_version": info.recipe_version if info is not None else "",
            "pypts_version": info.pypts_version if info is not None else "",
            "run_started_at": self.run_started_at,
            "run_result": str(self.run_result) if self.run_result is not None else "",
        }
        for name in self.metadata_names():
            cells[name] = self.metadata.get(name, "")
        return cells

    def metadata_names(self) -> tuple[str, ...]:
        """The metadata columns of this run, in the order the recipe named them."""
        if self.run_info is None:
            return ()
        return self.run_info.metadata_names

    @catch_and_report_errors()
    def record_metadata(self, values: tuple[tuple[str, str], ...]) -> None:
        """
        Take the run's metadata as the Sequencer reports it.

        Only remembered here: the rows already written keep their blanks until
        finish_run() backfills them, and the HTML is built at the end anyway.
        """
        for name, value in values:
            self.metadata[name] = value
        log.debug(
            "Report stored the run metadata: %s.",
            ", ".join(f"{name} = {value}" for name, value in values),
        )

    @catch_and_report_errors()
    def finish_run(self, result: ResultType) -> None:
        """The run is over: keep its verdict, settle its CSV, name its folder."""
        if self.run_dir is None:
            log.debug("RunFinished arrived with no run open; there is nothing to close.")
            return
        self.run_result = result
        self.close_csv()
        self.rewrite_csv()
        self.rename_run_dir()

    def rewrite_csv(self) -> None:
        """
        Write report.csv again, with every row carrying the run-level values.

        The verdict is only known now, and a metadata global is learned
        somewhere in the middle of the run, so the rows flushed as the run went
        have blanks in those columns. This is the one pass that fills them, and
        it is what lets report.html be built from the CSV alone.
        """
        if self.run_dir is None or not self.rows:
            return
        run_cells = self.run_level_cells()
        for row in self.rows:
            row.update(run_cells)
        csv_path = self.run_dir / "report.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.columns))
            writer.writeheader()
            writer.writerows(self.rows)

    def rename_run_dir(self) -> None:
        """
        Append the run's metadata to the folder name, so a season of runs is
        browsable by eye: <timestamp>_<recipe>_<serial>.

        It happens here because the folder is created on RunStarted, before any
        step has run - the serial number simply does not exist yet at that
        point. A rename that fails (the operator has the folder open, say) is a
        WARNING and the original folder is kept: losing the run over a cosmetic
        name would be a poor trade.
        """
        if self.run_dir is None:
            return
        suffix_parts = []
        for name in self.metadata_names():
            value = self.metadata.get(name, "")
            if value:
                suffix_parts.append(safe_name_part(value))
        if not suffix_parts:
            return
        target = self.run_dir.with_name(self.run_dir.name + "_" + "_".join(suffix_parts))
        if target.exists():
            log.warning("The results folder kept its name: '%s' already exists.", target.name)
            log.debug("Wanted to rename %s to %s.", self.run_dir, target)
            return
        try:
            self.run_dir.rename(target)
        except OSError as error:
            log.warning(
                "The results folder could not be renamed to '%s': %s", target.name, error
            )
            log.debug("Keeping the results in %s.", self.run_dir)
            return
        self.run_dir = target
        log.info("Results are in: %s", self.run_dir)

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
        if self.run_dir is None:
            log.warning("No report was generated: no test run has been recorded yet.")
            return
        self.close_csv()
        html_path = self.run_dir / "report.html"
        html_path.write_text(self.render_html(), encoding="utf-8")
        log.info("Report generated: %s", html_path)
        log.debug("The report covers %d recorded step rows.", len(self.rows))
        self.core.send(ReportGenerated(report_path=str(html_path)))

    def render_html(self) -> str:
        """
        The whole report as one self-contained page: header, summary, table.

        Everything it shows comes from the rows, which is what makes
        report.html regenerable from report.csv alone - point rows_from_csv()
        at a past run and render it again. The run-level values are on every
        row, so the first one answers for all of them.
        """
        # A run in which no step executed has no rows to read, so the live
        # path falls back to what it holds. Regenerating from a CSV that has
        # no rows finds nothing either way - there is nothing to regenerate.
        if self.rows:
            first_row = self.rows[0]
        else:
            first_row = self.run_level_cells()
        title = html.escape(first_row.get("recipe_name", ""))
        description = html.escape(first_row.get("recipe_description", ""))
        verdict = first_row.get("run_result", "")
        if not verdict:
            verdict = "in progress"
        version_line = first_row.get("recipe_version", "")
        pypts_version = first_row.get("pypts_version", "")
        started_at = first_row.get("run_started_at", "")
        generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        metadata_lines = []
        for name in self.metadata_names():
            value = first_row.get(name, "")
            if value:
                metadata_lines.append(
                    f"<strong>{html.escape(name)}:</strong> {html.escape(value)}<br>"
                )
        metadata_html = "".join(metadata_lines)

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
<p>{metadata_html}
<strong>Recipe:</strong> {title} {version_line}<br>
<strong>Description:</strong> {description}<br>
<strong>Result:</strong> {verdict}<br>
<strong>Started:</strong> {started_at}<br>
<strong>Generated:</strong> {generated_at} by pypts {pypts_version}</p>
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
        log.warning("The report could not be exported: exporting is not available yet.")

    # --- Housekeeping ---------------------------------------------------------

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self) -> None:
        self.running = False
        self.close_csv()
        log.debug("REPORT module stopping.")
        self.core.send(ReportStopped())
