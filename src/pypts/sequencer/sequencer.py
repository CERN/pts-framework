from queue import Empty
import time
from pypts.core.CoreInterface import SequencerToCoreInterface
from pypts.logger import log
import time


def sequencer_main(core: SequencerToCoreInterface, core_to_sequencer_queue):
    """Entry point called by Core process"""
    seq = Sequencer(core, core_to_sequencer_queue)
    seq.start()


class Sequencer:
    def __init__(self, coreInterface: SequencerToCoreInterface, core_to_sequencer_queue):
        self.coreInterface = coreInterface
        self.core_to_sequencer_queue = core_to_sequencer_queue
        self.running = True

    def start(self):
        log.info("[sequencer] Starting module...")
        self.main_loop()
        log.info("[sequencer] Stopping module...")

    def main_loop(self):
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)

    def poll_core(self):
        try:
            cmd = self.core_to_sequencer_queue.get(timeout=0)
            if cmd:
                self.handle_command(cmd)
        except Empty:
            pass

    def handle_command(self, cmd):
        print(f"[sequencer] Handle event from core: {cmd}")
        if cmd == "run":
            self.run_sequence()
        elif cmd == "exit":
            self.running = False
        else:
            print(f"[sequencer] Unknown event: {cmd}")

    def run_sequence(self):
        print("[sequencer] Running sequence...")
        # simulate doing something
        time.sleep(2)
        self.coreInterface.sequence_result()

    def do_periodic_tasks(self):
        """Periodic checks, health updates, etc."""
        pass
