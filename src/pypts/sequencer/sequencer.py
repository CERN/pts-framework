# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty
from pypts.core.sequencer_to_core_interface import SequencerToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToSequencerEvent, CoreToSequencerCommand
from pypts.logger.log import log
import time
from pypts.utilities.error_handling import catch_and_report_errors

def sequencer_main(core: SequencerToCoreInterface, core_to_sequencer_queue):
    """
    Entry point called by the Core process to launch the Sequencer module.
    Creates a Sequencer instance with communication interfaces and starts its main loop.
    """
    seq = Sequencer(core, core_to_sequencer_queue)
    seq.start()


class Sequencer:
    """
    Main class encapsulating the sequencer module's functionality.

    Attributes:
      - core: Interface for sending messages back to Core.
      - core_to_sequencer_queue: Queue to receive commands from Core.
      - running: Flag controlling the main loop execution.
    """

    def __init__(self, coreInterface: SequencerToCoreInterface, core_to_sequencer_queue):
        self.core = coreInterface
        self.core_to_sequencer_queue = core_to_sequencer_queue
        self.running = True

    def start(self):
        """
        Starts the sequencer module and runs the main event loop.
        Logs entering and exiting states of the module.
        """
        log.info("Starting module...")
        self.main_loop()
        log.info("Stopping module...")

    @catch_and_report_errors()
    def main_loop(self):
        """
        Main event loop processes incoming commands and performs periodic tasks.
        Polls the Core message queue non-blocking and processes commands if present.
        Sleeps briefly within each iteration for CPU efficiency.
        Exits when 'running' flag is set to False.
        """
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("exited main event loop.")

    @catch_and_report_errors()
    def poll_core(self):
        """
        Attempts to get a command from core_to_sequencer_queue without waiting.
        If a command is received, passes it for handling.
        Ignores exception when queue is empty (no messages).
        """
        try:
            event = self.core_to_sequencer_queue.get(timeout=0)
            if event:
                self.handle_command(event)
        except Empty:
            pass

    @catch_and_report_errors()
    def handle_command(self, event: CoreToSequencerEvent):
        """
        Handle commands received from Core.
        Supports RUN_SEQUENCE to perform sequencing and STOP to end the module.
        Logs any unknown commands as errors.
        """
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToSequencerCommand.RUN_SEQUENCE:
                self.run_sequence()
            case CoreToSequencerCommand.STOP:
                self.stop()
            case _:
                log.error(f"Unknown event: {event}")

    @catch_and_report_errors()
    def run_sequence(self):
        """
        Placeholder method where sequencing operations should be implemented.
        """
        pass

    @catch_and_report_errors()
    def do_periodic_tasks(self):
        """
        Placeholder for periodic checks, health monitoring, or housekeeping tasks.
        """
        pass

    @catch_and_report_errors()
    def stop(self):
        """
        Stops the sequencer by disabling the running flag,
        logs the stopping event, and calls Core's stop method.
        Additional teardown or cleanup code can be added here.
        """
        self.running = False
        log.info("stopping module")
        self.core.stop()

    @catch_and_report_errors()
    def _test_all_messages(self):
        """
        Internal test method to send a sequence result and stop signal to Core.
        Useful for validating communication paths.
        """
        self.core.sequence_result(text="PASSED")
        self.core.stop()
