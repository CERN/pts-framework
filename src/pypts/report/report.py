# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty
from pypts.core.report_to_core_interface import ReportToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToReportEvent, CoreToReportCommand
from pypts.logger.log import log
import time
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager
from pypts.utilities.common import poll_queue


def report_main(core: ReportToCoreInterface, core_to_report_queue):
    """
    Entry point called by the Core process to start the report module.
    Creates an instance of Report and launches its main loop.
    """
    report = Report(core, core_to_report_queue)
    report.start()


class Report:
    """
    Represents the report module, managing report generation, export, and shutdown.

    Attributes:
      - core: Interface for sending messages back to Core.
      - core_to_report_queue: Queue object for receiving commands from Core.
      - running: Boolean flag controlling the main loop's execution.
    """

    def __init__(self, core_interface: ReportToCoreInterface, core_to_report_queue):
        self.core = core_interface
        self.core_to_report_queue = core_to_report_queue
        self.running = True
        self.heartbeat_manager = HeartbeatManager(self.core.send_heartbeat)

    @catch_and_report_errors()
    def start(self):
        """
        Begins module operation, logs start and stop events.
        Runs the main event loop until stop() is called.
        """
        log.info("Starting module...")
        self.main_loop()
        log.info("Stopping module...")

    @catch_and_report_errors()
    def main_loop(self):
        """
        Main processing loop: polls for commands, executes periodic tasks,
        sleeps briefly to reduce CPU load. Exits when 'running' is False.
        """
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("exited main event loop.")

    @catch_and_report_errors()
    def poll_core(self):
        poll_queue(self.core_to_report_queue, self.handle_core_event)

    @catch_and_report_errors()
    def handle_core_event(self, event: CoreToReportEvent):
        """
        Routes incoming commands based on the event's command type.
        """
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToReportCommand.GENERATE:
                self.generate_report()
            case CoreToReportCommand.EXPORT:
                self.export_report()
            case CoreToReportCommand.STOP:
                self.stop()
            case _:
                log.error(f"Unknown event: {event}")

    @catch_and_report_errors()
    def generate_report(self):
        """
        Placeholder to implement report generation logic.
        """
        pass

    @catch_and_report_errors()
    def export_report(self):
        """
        Placeholder to implement report export logic.
        """
        pass

    @catch_and_report_errors()
    def do_periodic_tasks(self):
        """
        Executes any periodic status updates or maintenance tasks.
        """
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self):
        """
        Signals main loop to exit, logs, and calls core to shut down.
        """
        self.running = False
        log.info("stopping module")
        self.core.stop()

    @catch_and_report_errors()
    def _test_all_messages(self):
        """
        Sends all test messages for validating communication.
        Useful during development and debugging.
        """
        self.core.report_generated()
        self.core.report_exported()
        self.core.stop()
