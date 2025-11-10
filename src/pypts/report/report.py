from queue import Empty
import time
from pypts.logger.log import log


def report_main(report_to_core_queue, core_to_report_queue):
    """Entry point called by Core process"""
    report = Report(report_to_core_queue, core_to_report_queue)
    report.start()


class Report:
    def __init__(self, report_to_core_queue, core_to_report_queue):
        self.report_to_core_queue = report_to_core_queue
        self.core_to_report_queue = core_to_report_queue
        self.running = True

    def start(self):
        log.info("[report] Starting module...")
        self.main_loop()
        log.info("[report] Starting module...")

    def main_loop(self):
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)

    def poll_core(self):
        try:
            cmd = self.core_to_report_queue.get(timeout=0)
            if cmd:
                self.handle_command(cmd)
        except Empty:
            pass

    def handle_command(self, cmd):
        log.info(f"[report] Handling core event: {cmd}")
        if cmd == "generate":
            self.generate_report()
        elif cmd == "exit":
            self.running = False
        else:
            print(f"[report] Unknown event: {cmd}")

    def generate_report(self):
        print("[report] Generating report...")
        # simulate report generation
        time.sleep(1.5)
        self.report_to_core_queue.put("Report generated.")

    def do_periodic_tasks(self):
        """Periodic housekeeping, status updates, etc."""
        pass
