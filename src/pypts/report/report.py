# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty
from pypts.core.core_interface import ReportToCoreInterface
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
        log.info("[report] Starting module...")
        self.main_loop()
        log.info("[report] Starting module...")

    def main_loop(self):
        log.info("[report] Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)

    def poll_core(self):
        try:
            event: CoreToReportEvent = self.core_to_report_queue.get(timeout=0)
            self.handle_command(event)
        except Empty:
            pass

    def handle_command(self, event: CoreToReportEvent):
        print(f"[sequencer] Received event from core: {event}")
        match event.cmd:
            case CoreToReportCommand.GENERATE:
                self.generate_report()
            case CoreToReportCommand.EXPORT:
                self.export_report()
            case CoreToReportCommand.STOP:
                self.running = False
            case _:
                print(f"[sequencer] Unknown event: {event}")

    def generate_report(self):
        print("[report] Generating report...")
        # simulate report generation
        time.sleep(1.5)
        self.core.report_generated()


    def export_report(self):
        print("[report] Exporting report...")
        # simulate report generation
        time.sleep(1.5)
        self.core.report_exported()

    def do_periodic_tasks(self):
        """Periodic housekeeping, status updates, etc."""
        pass
