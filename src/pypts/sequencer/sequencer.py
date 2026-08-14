# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Sequencer - executes the sequences of a loaded recipe.

Runs as a thread of the Core process. The event loop and the link to CORE are
real; execution is not. execute_sequence() is where the engine in old_code/ is
going to land (roadmap Phase 1).

**A sequence runs on a thread of its own, not on the event loop.** That shape is
here before the engine is, because the engine cannot be dropped into the other
one. If a sequence ran on the loop thread, then for as long as it lasted:

  - do_periodic_tasks() would not run, so heartbeats would stop and CORE would
    declare the Sequencer dead after HEARTBEAT_TIMEOUT_S - on every real run;
  - StopSequence would sit unread in the inbox, so the abort path would be dead
    exactly when it is wanted;
  - UserPromptResponse would sit there too, and a step blocked in
    PendingRequests.wait() would never be answered. That is the deadlock
    blocking_messages.py warns about: the thread that calls wait() must not be
    the thread that drains the inbox.

So the loop thread only ever *starts* a sequence, and keeps turning while it
runs. The two threads share the outbox to CORE; `QueueWrapper.send()` puts onto
a `queue.Queue`, which is thread-safe, and its `sent` counter is a diagnostic
that may under-count by a message under contention. The run log is the accurate
whole-system view, as its docstring says.
"""

import threading
import time

from pypts.logger.log import log
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.blocking_messages import PendingRequests
from pypts.messages.core_sequencer_communication import (
    CoreToSequencer,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequence,
    StopSequencer,
)
from pypts.messages.run_events import SerialNumberResponse, UserPromptResponse
from pypts.utilities.error_handling import catch_and_report_errors, report_problem
from pypts.utilities.heartbeat_manager import SEQUENCER, HeartbeatManager

#: The name CORE knows this module by, and the `source` on its heartbeats.
#: Imported rather than spelled again: CORE keys its liveness tables on the
#: same string, and nothing would catch the two drifting apart.
MODULE_NAME = SEQUENCER

#: How long stop() waits for a sequence that is still running.
#:
#: Deliberately below CORE's SHUTDOWN_TIMEOUT_S (5 s): the join happens on the
#: event loop thread, so while it waits this module sends no heartbeats and
#: answers nothing. Leaving CORE some of its budget means a Sequencer whose
#: sequence will not stop still gets its SequencerStopped out, instead of being
#: named in CORE's "did not stop in time" line for a reason nobody can see.
SEQUENCE_JOIN_TIMEOUT_S = 2.0


def sequencer_main(
    to_core: QueueWrapper[SequencerToCore],
    from_core: QueueWrapper[CoreToSequencer],
) -> None:
    """
    Entry point called by CORE. Runs on the Sequencer thread.

    Deliberately does not call init_logging(): the root logger belongs to the
    Core process and core_main() has already pointed it at the Logger.
    Configuring it again from here would tear the handler off a logger the other
    threads are using at that moment.
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
        Start one named sequence, on a thread of its own, and return at once.

        Runs on the event loop thread and must stay short: everything this
        module does while a sequence runs - heartbeats, StopSequence, handing an
        operator's answer to a waiting step - happens on the loop this returns
        to. See the module docstring.

        A second request while one is running is refused rather than queued: two
        sequences at once would interleave their progress events. It is reported
        here rather than raised, because this module knows exactly what that
        failure is - the operator asked for something it cannot do - and a
        traceback through its own guard would tell them nothing. CORE still
        hears about it and still shows it; only the noise is gone.
        """
        if self.sequence_is_running():
            report_problem(
                self,
                f"Cannot start '{sequence_name}': a sequence is already running. "
                f"Send StopSequence first.",
                operation="Sequencer.run_sequence",
            )
            return

        # Cleared here rather than at the end of a run, so that a stop arriving
        # after the previous sequence finished cannot abort the next one.
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
        Run one named sequence. **On the sequence thread, not the event loop.**

        Not implemented: this is where the Recipe/Step/Runtime engine from
        old_code/ gets ported. When it does, it emits the progress events in
        messages/run_events.py as it goes, answers with RunFinished, and checks
        `stop_requested` between steps.

        It may block for as long as a run takes, and it may block *inside* a
        step waiting for the operator through PendingRequests.wait() - both are
        only safe because this is not the thread draining the inbox.
        """
        log.warning(
            "Cannot run '%s': the execution engine is not ported yet.", sequence_name
        )

    @catch_and_report_errors()
    def stop_sequence(self) -> None:
        """
        Abort the running sequence, keeping the module alive.

        Sets the flag and returns; it does not wait. The sequence thread checks
        `stop_requested` between steps, so the abort takes effect at the next
        step boundary rather than in the middle of one - which is what lets a
        step leave its hardware in a known state.

        CORE has always had a method to send this command; until now the
        Sequencer had no branch for it and would have logged it as unknown while
        the sequence carried on.
        """
        log.info("Sequence stop requested.")
        self.stop_requested = True

    def deliver_response(self, message: UserPromptResponse | SerialNumberResponse) -> None:
        """
        Hand an operator's answer to the step waiting for it.

        Runs on the event loop thread while the step is blocked in
        PendingRequests.wait() on the sequence thread - which is the whole
        reason the two are separate.

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

        SequencerStopped is sent last, after the sequence thread has ended:
        CORE treats that message as "this module is finished", and sending it
        while a sequence was still touching hardware would be a lie CORE acts
        on - it exits as soon as all three modules have reported.
        """
        self.running = False
        log.info("Stopping module.")
        self.stop_running_sequence()
        self.core.send(SequencerStopped())

    def stop_running_sequence(self) -> None:
        """
        Ask a running sequence to stop, and wait for its thread to end.

        The wait happens on the event loop thread, so nothing else this module
        does happens during it - see SEQUENCE_JOIN_TIMEOUT_S for why that budget
        is smaller than CORE's.

        A thread still alive at the end is abandoned rather than killed: Python
        threads cannot be killed, and the alternative - refusing to report
        SequencerStopped - would only mean CORE waits out its own timeout and
        learns less. It is a daemon thread, so it cannot hold the process open.
        """
        # Bound to a local rather than re-read: `sequence_is_running()` cannot
        # tell a type checker that the attribute is not None, and one read is
        # what makes it plain that this waits on the thread it checked.
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
