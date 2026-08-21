# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Sequencer - executes the sequences of a loaded recipe.

Runs as a thread of the Core process. CORE hands it the validated recipe with
UseRecipe; RunSequence starts one of its sequences, and execute_sequence()
drives the step layer (pypts.step) through a Runtime whose emit/should_stop
seams point back here. 

A sequence runs on a thread of its own, not on the event loop. 
"""

import threading
import time

from pypts.logger.log import log
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.blocking_messages import PendingRequests
from pypts.messages.common_messages import ResultType
from pypts.messages.core_sequencer_communication import (
    CoreToSequencer,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequence,
    StopSequencer,
    UseRecipe,
)
from pypts.messages.run_events import (
    RunFinished,
    RunStarted,
    SerialNumberResponse,
    UserPromptResponse,
)
from pypts.recipe.recipe import Recipe
from pypts.step.runtime import Runtime

# Aliased: run_sequence() here is the loop-thread method that *starts* a run;
# the step layer's run_sequence() is the sequence body itself.
from pypts.step.step import StepResult
from pypts.step.step import run_sequence as run_sequence_body
from pypts.utilities.error_handling import catch_and_report_errors, report_error, report_problem
from pypts.utilities.heartbeat_manager import SEQUENCER, HeartbeatManager

#: The name CORE knows this module by the name
MODULE_NAME = SEQUENCER

#: How long stop() waits for a sequence that is still running.
SEQUENCE_JOIN_TIMEOUT_S = 2.0


def sequencer_main(
    to_core: QueueWrapper[SequencerToCore],
    from_core: QueueWrapper[CoreToSequencer],
) -> None:
    """
    Entry point called by CORE. Runs on the Sequencer thread
    """
    Sequencer(to_core, from_core).start()


class Sequencer:
    """
    Attributes:
        core: outbox to CORE. Named `core` because @catch_and_report_errors()
              reports failures through it.
        inbox: commands from CORE.
        pending: questions this module has asked the operator and is waiting on.
        stop_requested: set by StopSequence, read by the sequence thread between
              steps. One writer, one reader, one bool - no lock needed.
        sequence_thread: the thread a sequence is running on, or None if none
              has been started yet.
        recipe: the validated Recipe CORE handed over with UseRecipe, or None
              until it does. A live object, not a copy - the two threads share
              one process.
    """

    def __init__(
        self,
        to_core: QueueWrapper[SequencerToCore],
        from_core: QueueWrapper[CoreToSequencer],
    ) -> None:
        self.core = to_core
        self.inbox = from_core
        self.running = True
        self.stop_requested = False
        self.pending = PendingRequests()
        self.heartbeat_manager = HeartbeatManager(self.core, MODULE_NAME)
        self.sequence_thread: threading.Thread | None = None
        self.recipe: Recipe | None = None

    def start(self) -> None:
        log.info("Starting module.")
        self.main_loop()
        log.info("Module stopped.")

    @catch_and_report_errors()
    def main_loop(self) -> None:
        log.info("Starting main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.info("Left main event loop.")

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)

    @catch_and_report_errors()
    def handle_core_message(self, message: CoreToSequencer) -> None:
        match message:
            case UseRecipe(recipe=recipe):
                self.take_recipe(recipe)
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
    def take_recipe(self, recipe: Recipe) -> None:
        """Store the validated recipe subsequent RunSequence commands run."""
        self.recipe = recipe
        log.info(
            "Recipe '%s' (version %s) received. Sequences: %s",
            recipe.name,
            recipe.version,
            ", ".join(recipe.sequences),
        )

    @catch_and_report_errors()
    def run_sequence(self, sequence_name: str) -> None:
        """
        Start one named sequence, on a thread of its own, so it does not interfere with the main loop.
        """
        if self.sequence_is_running():
            report_problem(
                self,
                f"Cannot start '{sequence_name}': a sequence is already running. "
                f"Send StopSequence first.",
                operation="Sequencer.run_sequence",
            )
            return

        # Cleared here rather than at the end of a run
        self.stop_requested = False

        self.sequence_thread = threading.Thread(
            target=self.execute_sequence,
            name="Sequence",
            args=(sequence_name,),
            daemon=True,
        )
        self.sequence_thread.start()

    def sequence_is_running(self) -> bool:
        """Whether a sequence thread exists and has not finished."""
        return self.sequence_thread is not None and self.sequence_thread.is_alive()

    @catch_and_report_errors()
    def execute_sequence(self, sequence_name: str) -> None:
        """
        Run one named sequence.

        Emits RunStarted/RunFinished itself; everything in between
        (SequenceStarted, the step events, SequenceFinished) comes out of the
        step layer through the Runtime's messages.
        """
        if self.recipe is None:
            report_problem(
                self,
                f"No recipe loaded - cannot run '{sequence_name}'. Send LoadRecipe first.",
                operation="Sequencer.execute_sequence",
            )
            return
        sequence = self.recipe.sequences.get(sequence_name)
        if sequence is None:
            report_problem(
                self,
                f"Recipe '{self.recipe.name}' has no sequence '{sequence_name}'. "
                f"Sequences: {', '.join(self.recipe.sequences)}",
                operation="Sequencer.execute_sequence",
            )
            return

        log.info("Run started: sequence '%s' of recipe '%s'.", sequence_name, self.recipe.name)
        runtime = Runtime(
            globals=dict(self.recipe.globals),
            emit=self.core.send,
            should_stop=lambda: self.stop_requested,
            base_dir=self.recipe.base_dir,
        )
        self.core.send(
            RunStarted(
                recipe_name=self.recipe.name, recipe_description=self.recipe.description
            )
        )
        step_results: list[StepResult] = []
        try:
            result, step_results = run_sequence_body(runtime, sequence)
        except Exception as error:  
            report_error(self, error, operation="Sequencer.execute_sequence")
            result = ResultType.ERROR
        if self.stop_requested:
            result = ResultType.STOP
        self.core.send(
            RunFinished(result=result, outcomes=tuple(r.to_outcome() for r in step_results))
        )
        log.info("Run finished: %s.", result)

    @catch_and_report_errors()
    def stop_sequence(self) -> None:
        """
        Abort the running sequence, keeping the module alive.

        Sets the flag and returns; it does not wait. The sequence thread checks
        `stop_requested` between steps, so the abort takes effect at the next
        step boundary rather than in the middle of one 
        """
        log.info("Sequence stop requested.")
        self.stop_requested = True

    def deliver_response(self, message: UserPromptResponse | SerialNumberResponse) -> None:
        """
        Hand an operator's answer to the step waiting for it.
        """
        match message:
            case UserPromptResponse():
                value = message.choice
            case SerialNumberResponse():
                value = message.serial_number
            case _:
                unhandled(message)

        if not self.pending.return_caller(message.request_id, value):
            log.warning("Nobody was waiting for response %s", message.request_id)

    # --- Housekeeping ---------------------------------------------------------

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self) -> None:
        """
        Shut the module down, bringing a running sequence with it.
        """
        self.running = False
        log.info("Stopping module.")
        self.stop_running_sequence()
        self.core.send(SequencerStopped())

    def stop_running_sequence(self) -> None:
        """
        Ask a running sequence to stop, and wait for its thread to end.
        """
        thread = self.sequence_thread
        if thread is None or not thread.is_alive():
            return

        log.info("Waiting for the running sequence to stop.")
        self.stop_requested = True
        thread.join(timeout=SEQUENCE_JOIN_TIMEOUT_S)

        if thread.is_alive():
            log.error(
                "The running sequence did not stop within %.0fs; abandoning it.",
                SEQUENCE_JOIN_TIMEOUT_S,
            )
