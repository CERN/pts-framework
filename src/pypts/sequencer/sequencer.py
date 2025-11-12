# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty
from pypts.core.sequencer_to_core_interface import SequencerToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToSequencerEvent, CoreToSequencerCommand
from pypts.logger.log import log
import time

def sequencer_main(core: SequencerToCoreInterface, core_to_sequencer_queue):
    """Entry point called by Core process"""
    seq = Sequencer(core, core_to_sequencer_queue)
    seq.start()

class Sequencer:
    def __init__(self, coreInterface: SequencerToCoreInterface, core_to_sequencer_queue):
        self.core = coreInterface
        self.core_to_sequencer_queue = core_to_sequencer_queue
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
            cmd = self.core_to_sequencer_queue.get(timeout=0)
            if cmd:
                self.handle_command(cmd)
        except Empty:
            pass

    def handle_command(self, event: CoreToSequencerEvent):
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToSequencerCommand.RUN_SEQUENCE:
                self.run_sequence()
            case CoreToSequencerCommand.STOP:
                self.stop()
            case _:
                log.error(f"Unknown event: {event}")

    def run_sequence(self):
        pass

    def do_periodic_tasks(self):
        """Periodic checks, health updates, etc."""
        pass

    def stop(self):
        self.running = False
        log.info("stopping module")

        self.core.stop()
        # add any teardown methods here

    def _test_all_messages(self):
        self.core.sequence_result(text = "PASSED")
        self.core.stop()