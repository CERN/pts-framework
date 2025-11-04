from multiprocessing import Process, Queue
import time
from queue import Empty

from pypts.sandbox.hmi import QueueHMI
from pypts.messages.CORE_MESSAGES import CoreCommand, CoreMessage
from pypts.messages.HMI_MESSAGES import HMIEvent, HMIMessage
from sequencer import sequencer_main
from report import report_main


def core_main(hmi: QueueHMI):
    """Entry point for launcher"""
    core = Core(hmi)
    core.start()


class Core:
    def __init__(self, hmi: QueueHMI):
        self.hmi = hmi
        self.running = True

        # inter-module queues
        self.core_to_sequencer_queue = Queue()
        self.sequencer_to_core_queue = Queue()
        self.core_to_report_queue = Queue()
        self.report_to_core_queue = Queue()

        self.sequencer = None
        self.report = None

    # --- Startup ---
    def start(self):
        print("[core] Initializing subsystems...")

        self.start_submodules()
        self.main_loop()

    def start_submodules(self):
        self.sequencer = Process(
            target=sequencer_main,
            args=(self.sequencer_to_core_queue, self.core_to_sequencer_queue)
        )
        self.sequencer.start()

        self.report = Process(
            target=report_main,
            args=(self.report_to_core_queue, self.core_to_report_queue)
        )
        self.report.start()

    # --- Main loop ---
    def main_loop(self):
        print("[core] Starting main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            time.sleep(0.01)
        print("[core] Stopped main event loop.")

    def poll_queue(self, queue, handler):
        try:
            event = queue.get_nowait()
            if event:
                handler(event)
        except Empty:
            pass

    def poll_all_sources(self):
        self.poll_hmi()
        self.poll_queue(self.sequencer_to_core_queue, self.handle_sequencer_event)
        self.poll_queue(self.report_to_core_queue, self.handle_report_event)

    def poll_hmi(self):
        if not self.hmi:
            return
        event = self.hmi.receive_command_from_hmi(timeout=0.1)
        if event:
            self.handle_hmi_event(event)

    # --- Event handlers ---
    def handle_hmi_event(self, msg: CoreMessage):
        print(f"[core] HMI -> CORE: {msg}")
        match msg.cmd:
            case CoreCommand.EXIT:
                self.running = False
                self.hmi.send_command_to_hmi(HMIMessage(HMIEvent.INFO, {"text": "Core shutting down"}))
            case CoreCommand.RUN_SEQUENCE:
                self.hmi.send_command_to_hmi(HMIMessage(HMIEvent.SEQUENCE_STARTED, {}))
                self.core_to_sequencer_queue.put("run")
            case CoreCommand.GENERATE_REPORT:
                self.core_to_report_queue.put("generate")
            case _:
                self.hmi.send_command_to_hmi(
                    HMIMessage(HMIEvent.ERROR, {"text": f"Unknown command {msg.cmd}"})
                )

    def handle_sequencer_event(self, event):
        print(f"[core] SEQUENCER event: {event}")
        # translate low-level event into HMI message
        self.hmi.send_command_to_hmi(HMIMessage(HMIEvent.SEQUENCE_FINISHED, {"status": event}))

    def handle_report_event(self, event):
        print(f"[core] REPORT event: {event}")
        self.hmi.send_command_to_hmi(HMIMessage(HMIEvent.REPORT_GENERATED, {"status": event}))

    # --- Background tasks ---
    def do_periodic_tasks(self):
        pass
