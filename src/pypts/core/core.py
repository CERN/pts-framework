from multiprocessing import Process, Queue
import time
from queue import Empty

from pypts.hmi.HMIInterface import CoreToHMIQueue
from pypts.hmi.HMI_MESSAGES import HMIToCoreCommand, HMIToCoreEvent

from pypts.sequencer.sequencer_interface import CoreToSequencerQueue
from pypts.sequencer.sequencer import sequencer_main
from pypts.sequencer.SEQUENCER_MESSAGES import SequencerToCoreCommand, SequencerToCoreEvent

from pypts.report.report_interface import CoreToReportQueue
from pypts.report.report import report_main
from pypts.report.REPORT_MESSAGES import ReportToCoreEvent, ReportToCoreCommand

from pypts.logger.log import log

"""Entry point for launcher"""
def core_main(
        coreToHMIInterface: CoreToHMIQueue,
        hmi_to_core_queue: Queue):
    core = Core(coreToHMIInterface, hmi_to_core_queue)
    core.start()


class Core:
    def __init__(self, coreToHMIInterface: CoreToHMIQueue, hmi_to_core_queue: Queue):
        self.coreToHMIInterface = coreToHMIInterface
        self.hmi_to_core_queue = hmi_to_core_queue

        self.sequencer = CoreToSequencerQueue
        self.sequencer_to_core_queue = Queue()

        self.report = CoreToReportQueue
        self.report_to_core_queue = Queue()

        self.running = True

    # --- Startup ---
    def start(self):
        log.info("[core] Starting module...")
        self.start_submodules()
        self.main_loop()
        log.info("[core] Stopping module...")

    def start_submodules(self):
        self.sequencer = Process(
            target=sequencer_main,
            args=(SequencerToCoreInterface, self.core_to_sequencer_queue)
        )
        self.sequencer.start()

        # def sequencer_main(core: SequencerToCoreInterface, core_to_sequencer_queue):


        self.report = Process(
            target=report_main,
            args=(self.report_to_core_queue, self.core_to_report_queue)
        )
        self.report.start()

    # --- Main loop ---
    def main_loop(self):
        log.info("[core] Starting main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("[core] Stopped main event loop.")

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
        log.info(f"[core] Handling HMI event: {event}")
        match event.cmd:
            case HMIToCoreCommand.STOP:
                pass
                # todo - implement action on stop
            case HMIToCoreCommand.LOAD_RECIPE:
                pass
                # todo - implement action
            case HMIToCoreCommand.START_SEQUENCE:
                pass
                # todo - implement action
            case _:
                pass
                # todo - implement action

    def handle_sequencer_event(self, event: SequencerToCoreEvent):
        log.info(f"[core] Handling Sequencer event: {event}")
        match event.cmd:
            case SequencerToCoreCommand.STOP:
                pass
                # todo - implement action on stop
            case SequencerToCoreCommand.SEQUENCE_RESULT:
                pass
            case _:
                pass
                # todo - implement action

    def handle_report_event(self, event: ReportToCoreEvent):
        log.info(f"[core] Handling Report event: {event}")
        match event.cmd:
            case ReportToCoreCommand.STOP:
                pass
                # todo - implement action on stop
            case ReportToCoreCommand.REPORT_GENERATED:
                # todo - implement action
                pass
            case _:
                # todo - implement action
                pass

    # --- Background tasks ---
    def do_periodic_tasks(self):
        pass
