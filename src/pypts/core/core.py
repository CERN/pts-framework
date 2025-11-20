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
Entry point for launcher. Responsible for instantiating Core class 
and starting its execution thread.
"""
def core_main(coreToHMIInterface: CoreToHMIQueue,hmi_to_core_queue: Queue):
    core = Core(coreToHMIInterface, hmi_to_core_queue)
    core.start()


class Core:
    """
    Main central module managing communication and lifecycle of HMI, Sequencer, and Report modules.
    Maintains queues and interfaces for message passing and spawns subprocesses for submodules.
    """
    def __init__(self, coreToHMIInterface: CoreToHMIQueue, hmi_to_core_queue: Queue):
        """
        Initializes interfaces and communication queues for all submodules.
        Sets running flags and placeholders for watchdog/timeouts (to be implemented).
        """
        self.hmi = coreToHMIInterface
        self.hmi_to_core_queue = hmi_to_core_queue

        # Sequencer communication setup
        self.sequencer_to_core_queue = Queue()
        self.sequencerToCoreInterface = SequencerToCoreQueue(self.sequencer_to_core_queue)
        self.core_to_sequencer_queue = Queue()
        self.sequencer = CoreToSequencerQueue(self.core_to_sequencer_queue)

        # Report communication setup
        self.report_to_core_queue = Queue()
        self.reportToCoreInterface = ReportToCoreQueue(self.report_to_core_queue)
        self.core_to_report_queue = Queue()
        self.report = CoreToReportQueue(self.core_to_report_queue)

        self.running = True

        # Flags for module running statuses - for monitoring and graceful shutdown
        self.report_running = True
        self.sequencer_running = True
        self.hmi_running = True

        self.last_heartbeat = {
            "sequencer": time.time(),
            "report": time.time(),
            "hmi": time.time()
        }
        self.heartbeat_timeout = 5.0  # seconds, adjust as needed

    # --- Startup ---
    def start(self):
        """
        Begins Core module execution by spawning submodules and entering main event loop.
        Logs lifecycle events.
        """
        log.info("Starting module...")
        self.start_submodules()
        self.main_loop()
        log.info("Stopping module...")

    def start_submodules(self):
        """
        Spawns Sequencer and Report modules in separate processes.
        Passes their respective communication interfaces and queues.
        """
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

    # --- Main event loop ---
    def main_loop(self):
        """
        Continuously polls all message queues for incoming events from submodules.
        Executes periodic background tasks and checks stop conditions.
        Sleeps briefly to avoid busy waiting.
        """
        log.info("Starting main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            self.check_stop_status()
            time.sleep(0.01)

    # --- Event handlers ---
    def poll_queue(self, queue, handler):
        """
        Helper to poll a given queue non-blockingly and call handler on received event.
        Ignores queue.Empty exceptions silently.
        """
        try:
            event = queue.get_nowait()
            if event:
                handler(event)
        except Empty:
            pass

    def poll_all_sources(self):
        """
        Polls queues for HMI, Sequencer and Report events, dispatching to appropriate handlers.
        """
        self.poll_queue(self.hmi_to_core_queue, self.handle_hmi_event)
        self.poll_queue(self.sequencer_to_core_queue, self.handle_sequencer_event)
        self.poll_queue(self.report_to_core_queue, self.handle_report_event)

    def handle_hmi_event(self, event: HMIToCoreEvent):
        """
        Handles events from HMI module.
        Supports exit and stop commands.
        Placeholders for additional commands like load_recipe and start_sequence.
        """
        log.info(f"Received HMI event: {event}")
        match event.cmd:
            case HMIToCoreCommand.EXIT:
                self.stop_all_modules()
            case HMIToCoreCommand.STOP:
                self.hmi_stopped()
            case HMIToCoreCommand.LOAD_RECIPE:
                pass  # Implement recipe loading logic here
            case HMIToCoreCommand.START_SEQUENCE:
                pass  # Implement sequence starting logic here
            case HMIToCoreCommand.HEARTBEAT:
                self.last_heartbeat["hmi"] = time.time()
            case _:
                pass  # Unknown or unhandled command

    def handle_sequencer_event(self, event: SequencerToCoreEvent):
        log.info(f"Received sequencer event: {event}")
        match event.cmd:
            case SequencerToCoreCommand.STOP:
                self.sequencer_stopped()
            case SequencerToCoreCommand.SEQUENCE_RESULT:
                # handle sequence result here
                pass
            case SequencerToCoreCommand.ERROR:
                # Extract error details from payload
                error_info = event.payload
                # Decide on further action, e.g. notify, restart, alert, etc.
            case SequencerToCoreCommand.HEARTBEAT:
                self.last_heartbeat["sequencer"] = time.time()
            case _:
                pass  # Unknown command

    def handle_report_event(self, event: ReportToCoreEvent):
        """
        Handles events from Report module.
        Supports STOP, REPORT_GENERATED and REPORT_EXPORTED commands.
        Logs unknown events as errors.
        """
        log.info(f"Received report event: {event}")
        match event.cmd:
            case ReportToCoreCommand.STOP:
                self.report_stopped()
            case ReportToCoreCommand.REPORT_GENERATED:
                pass  # Handle report generated notification here
            case ReportToCoreCommand.REPORT_EXPORTED:
                pass  # Handle report exported notification here
            case ReportToCoreCommand.ERROR:
                # Extract error details from payload
                error_info = event.payload
                # Decide on further action, e.g. notify, restart, alert, etc.
                pass
            case ReportToCoreCommand.HEARTBEAT:
                self.last_heartbeat["report"] = time.time()
            case _:
                log.error(f"Unknown event: {event}")

    # --- Background tasks ---
    def do_periodic_tasks(self):
        """
        Placeholder for periodic background tasks, e.g., health monitoring or housekeeping.
        """
        now = time.time()
        for module, last_time in self.last_heartbeat.items():
            if now - last_time > self.heartbeat_timeout:
                log.warning(f"Heartbeat timeout detected for module: {module}!!!")
                # Example action: log, send restart command, alert, etc.

    # shutdown detection
    def stop_all_modules(self):
        """
        Commands all submodules to stop via their interfaces.
        """
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
        """
        Checks running flags of all modules; stops Core if all have cleanly exited.
        TODO: Implement watchdog timeout to handle silent module deaths.
        """
        if (self.hmi_running or self.report_running or self.sequencer_running):
            pass
        else:
            log.info("All modules stopped cleanly")
            self.running = False
