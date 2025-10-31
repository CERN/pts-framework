from hmi import *
from queue import Empty, Full
from multiprocessing import Process, Queue
from sequencer import sequencer_main
from report import report_main
import time


def core_main(hmi):
    """Entry point for launcher"""
    core = Core(hmi)
    core.start()

# todo - spawn other modules
# todo - make the queues for them and hook onto them properly
class Core:
    def __init__(self, hmi):
        # hmi is defined by launcher
        self.hmi = hmi

        # standard private attributes
        self.running = True

        # singletons
        self.logger = None
        self.config_handler = None
        self.stream_container = None

        # standard classes
        self.recipe = None
        self.hw_layer = None

        # sequencer is another process
        self.core_to_sequencer_queue = Queue()
        self.sequencer_to_core_queue = Queue()
        self.sequencer = None

        # report is another process
        self.core_to_report_queue = Queue()
        self.report_to_core_queue = Queue()
        self.report = None


    def start(self):
        print("[core] Initializing subsystems...")
        # start the SEQUENCER module
        self.sequencer = Process(
            target=sequencer_main,
            args=(self.sequencer_to_core_queue, self.core_to_sequencer_queue)
        )
        self.sequencer.start()
        # start the REPORT module
        self.report = Process(
            target=report_main,
            args=(self.report_to_core_queue, self.core_to_report_queue)
        )
        self.report.start()
        # start the main CORE loop
        self.main_loop()

    def main_loop(self):
        print("[core] Starting main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            time.sleep(0.01)  # prevent CPU overuse
        print("[core] Stopped main event loop.")

    # --- Polling mechanism - to be able to handle multiple modules in a clean way ---
    def poll_all_sources(self):
        """Polls all communication sources (HMI, Sequencer, HW, etc.)"""
        self.poll_hmi()
        self.poll_sequencer()
        self.poll_report()

    def poll_hmi(self):
        if not self.hmi: return
        try:
            event = self.hmi.receive_command_from_hmi(timeout=0)
            if event:
                self.handle_hmi_event(event)
        except Empty:
            pass

    def poll_report(self):
        if not self.report: return
        try:
            event = self.report.receive_command_from_report(timeout=0)
            if event:
                self.handle_report_event(event)
        except Empty:
            pass

    def poll_sequencer(self):
        if not self.sequencer: return
        try:
            event = self.sequencer.receive_command_from_sequencer(timeout=0)
            if event:
                self.handle_sequencer_event(event)
        except Empty:
            pass

    # --- Periodic tasks - like send update to GUI ---
    def do_periodic_tasks(self):
        """Run background tasks, health checks, etc."""
        pass

    # todo - add all other event handlers
    # --- Event handlers - one per module ---
    def handle_hmi_event(self, event):
        print(f"[core] HMI event: {event}")
        # todo - change to case structure
        if event == "exit":
            self.running = False
            # todo: implement clean shutdown and propagate it
        else:
            # process commands or pass to subsystems
            pass

    def handle_sequencer_event(self, event):
        print(f"[core] SEQUENCER event: {event}")
        # todo - change to case structure
        if event == "exit":
            self.running = False
            # todo: implement clean shutdown and propagate it
        else:
            # process commands or pass to subsystems
            pass

    def handle_report_event(self, event):
        print(f"[core] REPORT event: {event}")
        # todo - change to case structure
        if event == "exit":
            self.running = False
            # todo: implement clean shutdown and propagate it
        else:
            # process commands or pass to subsystems
            pass
