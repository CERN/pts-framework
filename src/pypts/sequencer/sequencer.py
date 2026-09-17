# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Sequencer - executes the sequences of a loaded recipe.

Runs as a thread of the Core process. RunSequence brings both the validated
recipe and the name of the sequence to run, and execute_sequence() drives the
step layer (pypts.step) through a Runtime whose emit/should_stop seams point
back here. CORE owns the recipe between runs; this module keeps only the one
it was last asked to run. 

A sequence runs on a thread of its own, not on the event loop. 
"""

import threading
import time
from collections.abc import Callable
from typing import Any

from pypts._version import __version__
from pypts.logger.log import log
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.blocking_messages import PendingRequests
from pypts.messages.common_messages import ErrorSeverity, ResultType
from pypts.messages.core_sequencer_communication import (
    CoreToSequencer,
    PauseSequence,
    ResumeSequence,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequence,
    StopSequencer,
)
from pypts.messages.run_events import (
    RunFinished,
    RunMetadata,
    RunPaused,
    RunResumed,
    RunStarted,
    UserPathResponse,
    UserPromptResponse,
    UserTextResponse,
)
from pypts.recipe.recipe import Recipe
from pypts.step.runtime import Runtime

# Aliased: run_sequence() here is the loop-thread method that *starts* a run;
# the step layer's run_sequence() is the sequence body itself.
from pypts.step.step import StepResult, count_verdicts, describe_counts, real_step_results
from pypts.step.step import run_sequence as run_sequence_body
from pypts.utilities.error_handling import catch_and_report_errors, report_error, report_problem
from pypts.utilities.heartbeat_manager import SEQUENCER, HeartbeatManager

#: How long stop() waits for a sequence that is still running.
SEQUENCE_JOIN_TIMEOUT_S = 2.0

#: How often a held run looks at the pause and stop flags. Short enough that
#: Resume and Stop feel immediate; the hold is on the sequence thread, so this
#: costs the event loop nothing.
HOLD_POLL_S = 0.05


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
        pause_requested: set by PauseSequence and cleared by ResumeSequence,
              both on the event loop; read by the sequence thread before each
              main step, which also clears it once the main steps are over.
              A plain bool for the same reason as stop_requested: every write
              is a whole assignment, and a read that is one poll late only
              moves the hold by one step boundary or one HOLD_POLL_S.
        sequence_thread: the thread a sequence is running on, or None if none
              has been started yet.
        recipe: the validated Recipe that came with the last RunSequence, or
              None until one has. A live object, not a copy - the two threads
              share one process. CORE holds the loaded recipe; this is only
              what the current run was given.
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
        self.pause_requested = False
        self.pending = PendingRequests()
        self.heartbeat_manager = HeartbeatManager(self.core, SEQUENCER)
        self.sequence_thread: threading.Thread | None = None
        self.recipe: Recipe | None = None
        self.goodbye_sent = False

    @catch_and_report_errors()
    def start(self) -> None:
        """
        The thread's entry point, and the module's last-ditch error boundary.

        The decorator sits here rather than on main_loop() because the `while`
        is *inside* main_loop: catching there would end the loop it looks like
        it protects, and then report a clean stop. Almost nothing can get this
        far - poll_core() and do_periodic_tasks() are the loop body and both
        carry their own net - so this is the net for the loop itself dying.
        """
        log.debug("SEQUENCER module starting.")
        log.info("SEQUENCER module started.")
        try:
            self.main_loop()
        finally:
            # A loop that died instead of ending still owes CORE the goodbye:
            # without it CORE waits out its whole shutdown budget and then names
            # this module as one that would not stop. The ModuleError the
            # decorator sends right behind this says it went badly.
            self.send_goodbye()
        log.info("SEQUENCER module stopped.")

    def send_goodbye(self) -> None:
        """
        Tell CORE this module has stopped - at most once.

        Two callers: stop(), which is how this normally happens, and start()'s
        finally, for the loop that died rather than ended. CORE needs to hear it
        once; a second copy would only show up in every ordinary run's trace.
        """
        if self.goodbye_sent:
            return
        self.goodbye_sent = True
        self.core.send(SequencerStopped())

    def main_loop(self) -> None:
        log.debug("SEQUENCER entered its main event loop.")
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.01)
        log.debug("SEQUENCER left its main event loop.")

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)

    @catch_and_report_errors()
    def handle_core_message(self, message: CoreToSequencer) -> None:
        match message:
            case RunSequence(recipe=recipe, sequence_name=sequence_name):
                # The only place `recipe` is written: a run always uses the
                # recipe its own command carried.
                self.recipe = recipe
                self.run_sequence(sequence_name)
            case StopSequence():
                self.stop_sequence()
            case PauseSequence():
                self.pause_sequence()
            case ResumeSequence():
                self.resume_sequence()
            case StopSequencer():
                self.stop()
            case UserPromptResponse() | UserTextResponse() | UserPathResponse():
                self.deliver_response(message)
            case _:
                unhandled(message)

    # --- Execution ------------------------------------------------------------

    def run_sequence(self, sequence_name: str) -> None:
        """Start one named sequence on a thread of its own, so the event loop keeps turning."""
        if self.sequence_is_running():
            report_problem(
                self,
                f"Cannot start '{sequence_name}': a test is already running. "
                f"Stop the running test first.",
                operation="Sequencer.run_sequence",
            )
            return

        # Cleared here rather than at the end of a run
        self.stop_requested = False
        self.pause_requested = False

        log.debug("Starting the sequence thread for '%s'.", sequence_name)
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
        # Unreachable through the protocol - RunSequence carries the recipe, and
        # CORE refuses the command when it has none. Kept as the guard for a
        # direct call, and because `recipe` is Recipe | None until the first run.
        if self.recipe is None:
            report_problem(
                self,
                f"Cannot run '{sequence_name}': no recipe is loaded. Open a recipe first.",
                operation="Sequencer.execute_sequence",
            )
            return
        sequence = self.recipe.sequences.get(sequence_name)
        if sequence is None:
            report_problem(
                self,
                f"Recipe '{self.recipe.name}' has no sequence called '{sequence_name}'. "
                f"It has: {', '.join(self.recipe.sequences)}.",
                operation="Sequencer.execute_sequence",
            )
            return

        log.debug(
            "Running sequence '%s' of recipe '%s' on the sequence thread.",
            sequence_name,
            self.recipe.name,
        )
        run_began = time.perf_counter()
        # One dict for the whole run: the Runtime writes into it and the
        # metadata watcher reads it, so the two see the same values.
        run_globals = dict(self.recipe.globals)
        metadata_names = self.recipe.report_metadata
        reported_metadata: dict[str, str] = {}
        runtime = Runtime(
            globals=run_globals,
            # The Report cannot read globals - it is a thread fed by events -
            # so the emit seam is wrapped to notice when one the recipe named
            # in report_metadata changes, and to send it on. The step layer
            # knows nothing about this: it emits what it always emitted.
            emit=self.make_metadata_watcher(run_globals, metadata_names, reported_metadata),
            should_stop=lambda: self.stop_requested,
            ask=self.ask_operator,
            base_dir=self.recipe.base_dir,
            hold_if_paused=self.hold_if_paused,
            drop_pending_pause=self.drop_pending_pause,
        )
        self.core.send(
            RunStarted(
                recipe_name=self.recipe.name,
                recipe_description=self.recipe.description,
                recipe_version=self.recipe.version,
                pypts_version=__version__,
                metadata_names=metadata_names,
            )
        )
        # A metadata global may be set in the recipe's own header rather than
        # by a step, so the first look happens before anything runs.
        self.send_changed_metadata(run_globals, metadata_names, reported_metadata)
        step_results: list[StepResult] = []
        try:
            result, step_results = run_sequence_body(runtime, sequence)
        except Exception as error:  # noqa: BLE001 - step failures must not crash the sequencer
            report_error(self, error, operation="Sequencer.execute_sequence")
            result = ResultType.ERROR
        if self.stop_requested:
            result = ResultType.STOP
        # Totals count real steps: a called sequence's row only stands for the
        # steps inside it, which are listed themselves.
        real_results = real_step_results(step_results)
        self.core.send(
            RunFinished(result=result, outcomes=tuple(r.to_outcome() for r in real_results))
        )
        self.log_run_summary(
            self.recipe.name, sequence_name, result, real_results, time.perf_counter() - run_began
        )

    def log_run_summary(
        self,
        recipe_name: str,
        sequence_name: str,
        result: ResultType,
        step_results: list[StepResult],
        elapsed_s: float,
    ) -> None:
        """
        The three lines that close the operator's account of the run.

        Three records rather than one multi-line record: each then carries its
        own timestamp, and neither the GUI's log panel nor the Debug Monitor
        has to treat the second and third as continuations of a traceback.
        See logging_rules.md section 6.

        Args:
            recipe_name: the recipe the run came from.
            sequence_name: the sequence that was run.
            result: the verdict the whole run aggregated to.
            step_results: every real step that produced one, at every depth, in order.
            elapsed_s: wall clock across the whole run.
        """
        log.info("Run summary: %s.", result.name)
        log.info(
            "Run summary: %s of %d steps in %.1f s.",
            describe_counts(count_verdicts(step_results)),
            len(step_results),
            elapsed_s,
        )
        log.info(
            "Run summary: recipe '%s', sequence '%s'.", recipe_name, sequence_name
        )

    def make_metadata_watcher(
        self,
        run_globals: dict[str, Any],
        metadata_names: tuple[str, ...],
        reported: dict[str, str],
    ) -> Callable[[Any], None]:
        """
        The Runtime's emit seam, plus a look at the metadata globals.

        Every event is forwarded first and unchanged, so nothing about the
        run's reporting depends on this; the look happens afterwards, which
        is why a run with no metadata names costs one `if` per event.
        """

        def emit(event: Any) -> None:
            self.core.send(event)
            if metadata_names:
                self.send_changed_metadata(run_globals, metadata_names, reported)

        return emit

    def send_changed_metadata(
        self,
        run_globals: dict[str, Any],
        metadata_names: tuple[str, ...],
        reported: dict[str, str],
    ) -> None:
        """
        Send RunMetadata for every named global that appeared or changed.

        A name the recipe never sets is simply absent - it is a convention,
        not a requirement, and a run that ignores it is not an error. Values
        are stringified because the Report writes them into a CSV cell.
        """
        changed = []
        for name in metadata_names:
            if name not in run_globals:
                continue
            value = str(run_globals[name])
            if reported.get(name) != value:
                reported[name] = value
                changed.append((name, value))
        if changed:
            log.info(
                "Unit under test: %s.", ", ".join(f"{name} = {value}" for name, value in changed)
            )
            self.core.send(RunMetadata(values=tuple(changed)))

    def stop_sequence(self) -> None:
        """
        Abort the running sequence, keeping the module alive.

        Sets the flag and returns; it does not wait. The sequence thread checks
        `stop_requested` between steps, so the abort takes effect at the next
        step boundary rather than in the middle of one 
        """
        log.info("The operator asked to stop the run.")
        log.debug("The stop flag is set; the run ends at the next step boundary.")
        self.stop_requested = True

    def pause_sequence(self) -> None:
        """
        Ask the running sequence to hold before its next main step.

        Sets the flag and returns, like stop_sequence(). The step that is
        running finishes first; the hold itself, and the RunPaused that
        confirms it, happen on the sequence thread in hold_if_paused().
        """
        if not self.sequence_is_running():
            log.debug("Pause requested with no sequence running; nothing to do.")
            return
        log.info("The operator asked to pause the run.")
        log.debug("The pause flag is set; the run holds before its next main step.")
        self.pause_requested = True

    def resume_sequence(self) -> None:
        """
        End a hold, or cancel a pause whose hold has not begun yet.

        Only clears the flag. If the run is held, hold_if_paused() sees it on
        its next poll and sends RunResumed; if it is not held yet, nothing is
        sent at all.
        """
        if not self.sequence_is_running():
            log.debug("Resume requested with no sequence running; nothing to do.")
            return
        log.info("The operator asked to resume the run.")
        log.debug("The pause flag is cleared (it was %s).", self.pause_requested)
        self.pause_requested = False

    def hold_if_paused(self, step_name: str, position: int, total: int) -> None:
        """
        Handed to every Runtime as its `hold_if_paused` seam.

        Returns at once unless a pause is pending. Otherwise it holds the run
        here, before main step `position` of `total`, until ResumeSequence or
        StopSequence ends the hold. The hold is a poll on the sequence thread:
        the event loop keeps turning meanwhile, which is what keeps the
        heartbeats going and lets the Resume or the Stop be read at all.

        MUST be called from the sequence thread, for the same reason as
        ask_operator().
        """
        if not self.pause_is_in_force():
            return

        self.core.send(RunPaused(step_name=step_name, position=position, total=total))
        log.info("The run is paused before step %d/%d '%s'.", position, total, step_name)
        while self.pause_is_in_force():
            time.sleep(HOLD_POLL_S)

        self.core.send(RunResumed())
        if self.stop_requested:
            # The operator's stop has already been logged at INFO.
            log.debug("The hold before step '%s' ended because the run was stopped.", step_name)
        else:
            log.info("The run was resumed.")

    def drop_pending_pause(self) -> None:
        """
        Handed to every Runtime as its `drop_pending_pause` seam.

        Called once the main steps are over, before teardown. A pause that
        was asked for but never got a step to hold before lapses here, and
        the operator is told so - teardown is never held.
        """
        if self.pause_is_in_force():
            log.info("The run was not paused: no steps were left.")
        self.pause_requested = False

    def pause_is_in_force(self) -> bool:
        """
        Whether a pause is pending and no stop has overridden it.

        A method rather than the expression written out: the other thread
        changes both flags, and reading them through a call keeps mypy from
        narrowing an attribute across the hold's poll loop.
        """
        return self.pause_requested and not self.stop_requested

    def ask_operator(self, request: Any) -> Any:
        """
        Put one question to the operator and block until it is answered.

        Handed to every Runtime as its `ask` seam, so this is the only place
        that knows the ordering - register before sending, or an answer that
        beats the registration is dropped. A step just calls runtime.ask().

        MUST be called from the sequence thread. The answer is delivered by
        deliver_response() on the *event loop* thread; a caller on the event
        loop would block the very loop that has to wake it.

        Returns None when nobody answered - the timeout ran out, the operator
        declined, or the run was stopped. The three are deliberately not told
        apart here: what to do about it belongs to the step that asked.
        """
        request_id = request.request_id
        self.pending.start(request_id)
        self.core.send(request)
        return self.pending.wait(request_id, should_abort=lambda: self.stop_requested)

    def deliver_response(
        self, message: UserPromptResponse | UserTextResponse | UserPathResponse
    ) -> None:
        """
        Hand an operator's answer to the step waiting for it.
        """
        match message:
            case UserPromptResponse():
                value = message.choice
            case UserTextResponse():
                value = message.text
            case UserPathResponse():
                value = message.path
            case _:
                unhandled(message)  # unreachable; keeps mypy's exhaustiveness check live

        if not self.pending.return_caller(message.request_id, value):
            # Late, or answered twice. Nothing is broken and nothing is lost -
            # the step that asked has already moved on - so this is the
            # developer's business, not the operator's.
            log.debug("No step was waiting for the answer to request %s.", message.request_id)

    # --- Housekeeping ---------------------------------------------------------

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    def stop(self) -> None:
        """
        Shut the module down, bringing a running sequence with it.
        """
        self.running = False
        log.debug("SEQUENCER module stopping.")
        try:
            self.stop_running_sequence()
        finally:
            # The goodbye is not optional, and the send is *after* the line that
            # can fail: without the finally an exception on its way out to the
            # per-message boundary would skip it, costing CORE its whole shutdown
            # budget and having it name this module as the one that never
            # answered - which it did not.
            self.send_goodbye()

    def stop_running_sequence(self) -> None:
        """
        Ask a running sequence to stop, and wait for its thread to end.
        """
        thread = self.sequence_thread
        if thread is None or not thread.is_alive():
            return

        log.info("Waiting for the running test to stop.")
        log.debug("Joining the sequence thread, up to %.1f s.", SEQUENCE_JOIN_TIMEOUT_S)
        self.stop_requested = True
        thread.join(timeout=SEQUENCE_JOIN_TIMEOUT_S)

        if thread.is_alive():
            # The bench may be mid-step with teardown never run: the operator
            # must hear this, not just the log. What CORE *does* about it is
            # the open error-policy TODO; this only makes the abandonment loud.
            report_problem(
                self,
                f"The running sequence did not stop within "
                f"{SEQUENCE_JOIN_TIMEOUT_S:.0f}s and is being abandoned; "
                f"teardown steps have not run and the bench state is unknown.",
                severity=ErrorSeverity.CRITICAL,
                operation="Sequencer.stop_running_sequence",
            )
