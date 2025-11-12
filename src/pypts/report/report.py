# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty
from pypts.core.report_to_core_interface import ReportToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToReportEvent, CoreToReportCommand
from pypts.logger.log import log
import time

def report_main(core: ReportToCoreInterface, core_to_report_queue):
    """Entry point called by Core process"""
    report = Report(core, core_to_report_queue)
    report.start()

class Report:
    def __init__(self, core_interface: ReportToCoreInterface, core_to_report_queue):
        self.core = core_interface
        self.core_to_report_queue = core_to_report_queue
        self.running = True

    def start(self):
        log.info("Starting module...")
        self.main_loop()
        log.info("Stopping module...")

    def main_loop(self):
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("exited main event loop.")

    def poll_core(self):
        try:
            event: CoreToReportEvent = self.core_to_report_queue.get(timeout=0)
            self.handle_command(event)
        except Empty:
            pass

    def handle_command(self, event: CoreToReportEvent):
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

    def generate_report(self):
        pass

    def export_report(self):
        pass

    def do_periodic_tasks(self):
        """Periodic tasks, status updates, etc."""
        pass

    def stop(self):
        self.running = False
        log.info("stopping module")
        self.core.stop()
        # add any teardown methods here

    def _test_all_messages(self):
        self.core.report_generated()
        self.core.report_exported()
        self.core.stop()