from queue import Empty
import time


def sequencer_main(sequencer_to_core_queue, core_to_sequencer_queue):
    """Entry point called by Core process"""
    seq = Sequencer(sequencer_to_core_queue, core_to_sequencer_queue)
    seq.start()


class Sequencer:
    def __init__(self, sequencer_to_core_queue, core_to_sequencer_queue):
        self.sequencer_to_core_queue = sequencer_to_core_queue
        self.core_to_sequencer_queue = core_to_sequencer_queue
        self.running = True

    def start(self):
        print("[sequencer] Started.")
        self.main_loop()
        print("[sequencer] Stopped.")

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
        print(f"[sequencer] Command from core: {cmd}")
        if cmd == "run":
            self.run_sequence()
        elif cmd == "exit":
            self.running = False
        else:
            print(f"[sequencer] Unknown command: {cmd}")

    def run_sequence(self):
        print("[sequencer] Running sequence...")
        # simulate doing something
        time.sleep(2)
        self.sequencer_to_core_queue.put("Sequence complete.")

    def do_periodic_tasks(self):
        """Periodic checks, health updates, etc."""
        pass
