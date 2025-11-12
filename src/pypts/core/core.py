from multiprocessing import Process, Queue
import time
from queue import Empty

from pypts.core.sequencer_to_core_interface import SequencerToCoreInterface, SequencerToCoreQueue
from pypts.core.report_to_core_interface import ReportToCoreInterface, ReportToCoreQueue

from pypts.hmi.core_to_HMI_interface import CoreToHMIQueue
from pypts.hmi.HMI_MESSAGES import HMIToCoreCommand, HMIToCoreEvent

from pypts.sequencer.core_to_sequencer_interface import CoreToSequencerQueue
from pypts.sequencer.sequencer import sequencer_main
from pypts.sequencer.SEQUENCER_MESSAGES import SequencerToCoreCommand, SequencerToCoreEvent

from pypts.report.core_to_report_interface import CoreToReportQueue
from pypts.report.report import report_main
from pypts.report.REPORT_MESSAGES import ReportToCoreEvent, ReportToCoreCommand

from pypts.logger.log import log

"""
Entry point for launcher. This is used to spawn an object of a class and run its thread.
"""
def core_main(
        coreToHMIInterface: CoreToHMIQueue,
        hmi_to_core_queue: Queue):
    core = Core(coreToHMIInterface, hmi_to_core_queue)
    core.start()
#

class Core:
    def __init__(self, coreToHMIInterface: CoreToHMIQueue, hmi_to_core_queue: Queue):
        """Interface and queues definitions"""
        self.hmi = coreToHMIInterface
        self.hmi_to_core_queue = hmi_to_core_queue

        # sequencer -> core
        self.sequencer_to_core_queue = Queue()
        self.sequencerToCoreInterface = SequencerToCoreQueue(self.sequencer_to_core_queue)
        # core -> sequencer
        self.core_to_sequencer_queue = Queue()
        self.sequencer = CoreToSequencerQueue(self.core_to_sequencer_queue)

        # report -> core
        self.report_to_core_queue = Queue()
        self.reportToCoreInterface = ReportToCoreQueue(self.report_to_core_queue)
        # core -> report
        self.core_to_report_queue = Queue()
        self.report = CoreToReportQueue(self.core_to_report_queue)

        self.running = True

        # todo - implement mechanism to check if the modules are really running
        # todo - add watchdog, so we know when modules are dying
        self.report_running = True
        self.sequencer_running = True
        self.hmi_running = True

    # --- Startup ---
    def start(self):
        log.info("Starting module...")
        self.start_submodules()
        self.main_loop()
        log.info("Stopping module...")

    def start_submodules(self):
        self.sequencerProcess = Process(
            target=sequencer_main,
            args=(self.sequencerToCoreInterface, self.core_to_sequencer_queue)
        )
        self.sequencerProcess.start()

        self.reportProcess = Process(
            target=report_main,
            args=(self.reportToCoreInterface, self.core_to_report_queue)
        )
        self.reportProcess.start()

    # --- Main loop - it is where the messages from other modules (or internal messages) are received ---
    def main_loop(self):
        log.info("Starting main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            self.check_stop_status()
            time.sleep(0.01)

    def poll_queue(self, queue, handler):
        try:
            event = queue.get_nowait()
            if event:
                handler(event)
        except Empty:
            pass

    def poll_all_sources(self):
        self.poll_queue(self.hmi_to_core_queue, self.handle_hmi_event)
        self.poll_queue(self.sequencer_to_core_queue, self.handle_sequencer_event)
        self.poll_queue(self.report_to_core_queue, self.handle_report_event)

    # --- Event handlers ---
    def handle_hmi_event(self, event: HMIToCoreEvent):
        log.info(f"Received HMI event: {event}")
        match event.cmd:
            case HMIToCoreCommand.EXIT:
                self.stop_all_modules()
            case HMIToCoreCommand.STOP:
                self.hmi_stopped()
            case HMIToCoreCommand.LOAD_RECIPE:
                pass
            case HMIToCoreCommand.START_SEQUENCE:
                pass
            case _:
                pass

    def handle_sequencer_event(self, event: SequencerToCoreEvent):
        log.info(f"Received sequencer event: {event}")
        match event.cmd:
            case SequencerToCoreCommand.STOP:
                self.sequencer_stopped()
                pass
            case SequencerToCoreCommand.SEQUENCE_RESULT:
                pass
            case _:
                pass

    def handle_report_event(self, event: ReportToCoreEvent):
        log.info(f"Received report event: {event}")
        match event.cmd:
            case ReportToCoreCommand.STOP:
                self.report_stopped()
            case ReportToCoreCommand.REPORT_GENERATED:
                pass
            case ReportToCoreCommand.REPORT_EXPORTED:
                pass
            case _:
                log.error(f"Unknown event: {event}")

    # --- Background tasks ---
    def do_periodic_tasks(self):
        pass

    def stop_all_modules(self):
        self.report.stop()
        self.sequencer.stop()
        self.hmi.stop()

    def report_stopped(self):
        self.report_running = False

    def sequencer_stopped(self):
        self.sequencer_running = False

    def hmi_stopped(self):
        self.hmi_running = False

    def check_stop_status(self):
        # todo - add timeout mechanism. Normally we expect clean closing of the modules,
        # but if module silently died already, we need to stop after 10s of timeout.
        if (self.hmi_running or self.report_running or self.sequencer_running):
            pass
        else:
            log.info("All modules stopped cleanly")
            self.running = False
