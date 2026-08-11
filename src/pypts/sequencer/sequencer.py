# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Sequencer - executes the sequences of a loaded recipe.

The event loop and the link to CORE are real; execution is not. run_sequence()
is where the engine in old_code/ is going to land (roadmap Phase 1).
"""

import time

from pypts.logger.log import init_logging, log
from pypts.messages import Channel, unhandled
from pypts.messages.requests import PendingRequests
from pypts.messages.run_events import SerialNumberResponse, UserPromptResponse
from pypts.messages.sequencer_link import (
    CoreToSequencer,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequence,
    StopSequencer,
)
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager

#: The name CORE knows this module by, and the `source` on its heartbeats.
MODULE_NAME = "sequencer"


def sequencer_main(to_core: Channel[SequencerToCore], from_core: Channel[CoreToSequencer], log_queue) -> None:
    """
    Entry point called by CORE. Runs in the Sequencer process.

    Log records are routed to the Logger before anything is logged.
    """
    init_logging(log_queue)
    Sequencer(to_core, from_core).start()


class Sequencer:
    """
    Attributes:
        core: outbox to CORE. Named `core` because @catch_and_report_errors()
              reports failures through it.
        inbox: commands from CORE.
        pending: questions this module has asked the operator and is waiting on.
    """

    def __init__(self, to_core: Channel[SequencerToCore], from_core: Channel[CoreToSequencer]) -> None:
        self.core = to_core
        self.inbox = from_core
        self.running = True
        self.stop_requested = False
        self.pending = PendingRequests()
        self.heartbeat_manager = HeartbeatManager(self.core, MODULE_NAME)

    def start(self) -> None:
        log.info("Starting module...")
        self.main_loop()
        log.info("Stopping module...")

    @catch_and_report_errors()
    def main_loop(self) -> None:
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("exited main event loop.")

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)

    @catch_and_report_errors()
    def handle_core_message(self, message: CoreToSequencer) -> None:
        log.info(f"Received core message: {message}")
        match message:
            case RunSequence(sequence_name=sequence_name):
                self.run_sequence(sequence_name)
            case StopSequence():
                self.stop_sequence()
            case StopSequencer():
                self.stop()
            case UserPromptResponse() | SerialNumberResponse():
                self.deliver_response(message)
            case _:
                unhandled(message)

    # --- Execution ------------------------------------------------------------

    @catch_and_report_errors()
    def run_sequence(self, sequence_name: str) -> None:
        """
        Run one named sequence.

        Not implemented: this is where the Recipe/Step/Runtime engine from
        old_code/ gets ported. When it does, it emits the progress events in
        messages/run_events.py as it goes, and answers with RunFinished.
        """
        log.warning(f"Cannot run '{sequence_name}': the execution engine is not ported yet.")

    @catch_and_report_errors()
    def stop_sequence(self) -> None:
        """
        Abort the running sequence, keeping the module alive.

        CORE has always had a method to send this command; until now the
        Sequencer had no branch for it and would have logged it as unknown while
        the sequence carried on. The flag is what the ported engine will check
        between steps.
        """
        log.info("Sequence stop requested.")
        self.stop_requested = True

    def deliver_response(self, message: UserPromptResponse | SerialNumberResponse) -> None:
        """
        Hand an operator's answer to the step waiting for it.

        A response nobody is waiting for means the two ends disagree about what
        is in flight - usually a request that already timed out - so it is worth
        a warning rather than a silent drop.
        """
        match message:
            case UserPromptResponse():
                value = message.choice
            case SerialNumberResponse():
                value = message.serial_number
            case _:
                unhandled(message)

        if not self.pending.resolve(message.request_id, value):
            log.warning(f"Nobody was waiting for response {message.request_id}")

    # --- Housekeeping ---------------------------------------------------------

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self) -> None:
        self.running = False
        log.info("stopping module")
        self.core.send(SequencerStopped())
