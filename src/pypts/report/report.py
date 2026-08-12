# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Report module - builds and exports the artefacts of a run.

The event loop and the link to CORE are real; generation is not. The CSV and
HTML logic to be ported lives in old_code/report.py (roadmap Phase 1).
"""

import time
from pathlib import Path

from pypts.config_handler import ConfigHandler
from pypts.logger.log import DEFAULT_LOG_LEVEL, init_logging, log
from pypts.messages import Channel, unhandled
from pypts.messages.report_link import (
    CoreToReport,
    ExportReport,
    GenerateReport,
    ReportStopped,
    ReportToCore,
    StopReport,
)
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager

#: The name CORE knows this module by, and the `source` on its heartbeats.
MODULE_NAME = "report"


def report_main(
    to_core: Channel[ReportToCore],
    from_core: Channel[CoreToReport],
    log_queue,
    log_level: int = DEFAULT_LOG_LEVEL,
) -> None:
    """
    Entry point called by CORE. Runs in the Report process.

    Log records are routed to the Logger before anything is logged.
    """
    init_logging(log_queue, log_level)
    Report(to_core, from_core).start()


class Report:
    """
    Attributes:
        core: outbox to CORE. Named `core` because @catch_and_report_errors()
              reports failures through it.
        inbox: commands from CORE.
        output_dir: where artefacts go, from the configuration.
    """

    def __init__(
        self,
        to_core: Channel[ReportToCore],
        from_core: Channel[CoreToReport],
        output_dir: Path | None = None,
    ) -> None:
        """
        Args:
            output_dir: overrides `paths.reports_dir`. Tests pass a tmp_path;
                the framework passes nothing and the configuration decides.
        """
        self.core = to_core
        self.inbox = from_core
        self.running = True
        self.heartbeat_manager = HeartbeatManager(self.core, MODULE_NAME)
        self.output_dir = (
            Path(output_dir)
            if output_dir is not None
            else ConfigHandler().get_parameter("paths.reports_dir")
        )

    @catch_and_report_errors()
    def start(self) -> None:
        log.info("Starting module...")
        # Stated once, at startup, because "where did my report go" is asked
        # after the run, when the answer is no longer on screen.
        log.info("Reports will be written to: %s", self.output_dir)
        self.main_loop()
        log.info("Stopping module...")

    @catch_and_report_errors()
    def main_loop(self) -> None:
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("exited main event loop.")

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)

    @catch_and_report_errors()
    def handle_core_message(self, message: CoreToReport) -> None:
        match message:
            case GenerateReport():
                self.generate_report()
            case ExportReport():
                self.export_report()
            case StopReport():
                self.stop()
            case _:
                unhandled(message)

    # --- Generation -----------------------------------------------------------

    @catch_and_report_errors()
    def generate_report(self) -> None:
        """
        Build the report for the run that just finished.

        Not implemented. When the logic from old_code/report.py is ported it
        answers with ReportGenerated carrying the absolute path of the artefact.
        """
        log.warning("Cannot generate: the report layer is not ported yet.")

    @catch_and_report_errors()
    def export_report(self) -> None:
        """
        Write the generated report out.

        Not implemented. Answers with ReportExported carrying the path.
        """
        log.warning("Cannot export: the report layer is not ported yet.")

    # --- Housekeeping ---------------------------------------------------------

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self) -> None:
        self.running = False
        log.info("stopping module")
        self.core.send(ReportStopped())
