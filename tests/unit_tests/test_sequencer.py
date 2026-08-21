# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Sequencer module (src/pypts/sequencer/).

Two halves. The first is real and tests the *threading shape*: a sequence runs
on a thread of its own, and the event loop keeps turning while it does. That
shape exists before the engine does, because the engine cannot be dropped into
the other one - see the module docstring in sequencer.py.

Every test here drives the loop by hand, calling `poll_core()` the way
`main_loop()` would. That is deliberate: it makes "the loop is still able to
run" an assertion rather than a hope, and it keeps the tests free of sleeps
waiting for a background loop to come round.

The second half tests the engine itself, by handing the Sequencer a recipe
with UseRecipe and calling `execute_sequence()` directly on the test thread -
it is a plain instance method, so asserting on event ordering needs no thread
behind it. The threading half already proves it runs on its own thread.
"""

import queue
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from pypts.messages import QueueWrapper
from pypts.messages.common_messages import Heartbeat, ModuleError, ResultType
from pypts.messages.core_sequencer_communication import (
    RunSequence,
    SequencerStopped,
    StopSequence,
    StopSequencer,
    UseRecipe,
)
from pypts.messages.run_events import (
    RunFinished,
    RunStarted,
    SequenceFinished,
    SerialNumberResponse,
    StepFinished,
    StepStarted,
)
from pypts.recipe.recipe import Recipe
from pypts.sequencer.sequencer import Sequencer

WAIT_RECIPE = Path(__file__).parent / "data" / "wait_recipe.yml"

#: A recipe whose first step errors (negative wait), so the second never runs.
FAILING_RECIPE = """\
name: Fails
description: The error path.
main_sequence: Main
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Bad wait
    wait_time: '-1'
  - steptype: Wait
    step_name: Never runs
    wait_time: '0'
"""

PLACEHOLDER = "placeholder - test not implemented yet"

#: How long a test waits for the sequence thread to reach a point. Generous,
#: because a loaded CI runner is slow; nothing here waits for it on the happy
#: path, so a passing run does not pay it.
REACHED_TIMEOUT_S = 5.0


@pytest.fixture
def sequencer():
    """
    A Sequencer wired to plain queues, plus those queues.

    `outbox` is what the Sequencer sends to CORE; `inbox` is what CORE sends it.
    Returned raw so a test can put a command in and read the answers out without
    going through the module under test.
    """
    outbox: queue.Queue = queue.Queue()
    inbox: queue.Queue = queue.Queue()
    instance = Sequencer(QueueWrapper(outbox), QueueWrapper(inbox))

    yield instance, outbox, inbox

    # A test that fails part way through must not leave a thread running into
    # the next one.
    instance.stop_requested = True
    if instance.sequence_thread is not None:
        instance.sequence_thread.join(timeout=REACHED_TIMEOUT_S)


def drain(a_queue):
    """Everything waiting on a queue right now, as a list."""
    messages = []
    while True:
        try:
            messages.append(a_queue.get_nowait())
        except queue.Empty:
            return messages


def blocks_until(event: threading.Event, reached: threading.Event):
    """A fake sequence body: says it started, then waits to be let go."""

    def execute(sequence_name: str) -> None:
        reached.set()
        event.wait(timeout=REACHED_TIMEOUT_S)

    return execute


def start_a_blocking_sequence(instance, inbox):
    """
    Put a sequence in flight and return the handle that ends it.

    Every test below needs a sequence that is genuinely still running while the
    assertions happen, which a stub that returns immediately cannot provide.
    """
    release = threading.Event()
    reached = threading.Event()
    instance.execute_sequence = blocks_until(release, reached)

    inbox.put(RunSequence("power_on"))
    instance.poll_core()

    assert reached.wait(timeout=REACHED_TIMEOUT_S), "the sequence thread never started"
    return release


# --------------------------------------------------------------------------
# The threading shape
# --------------------------------------------------------------------------


def test_run_sequence_returns_while_the_sequence_is_still_running(sequencer):
    """
    The command is not the run. poll_core() has to come back so the loop can
    service the next tick; if RunSequence blocked, everything below would follow.
    """
    instance, _outbox, inbox = sequencer
    release = start_a_blocking_sequence(instance, inbox)

    assert instance.sequence_is_running()

    release.set()


def test_heartbeats_keep_going_while_a_sequence_runs(sequencer):
    """
    The defect this shape exists to prevent: a sequence on the loop thread stops
    do_periodic_tasks(), CORE stops hearing from the module, and every real run
    logs "Heartbeat timeout for module: sequencer" after HEARTBEAT_TIMEOUT_S.
    """
    instance, outbox, inbox = sequencer
    release = start_a_blocking_sequence(instance, inbox)

    # The manager rate-limits itself; a test must not wait a real second for it.
    instance.heartbeat_manager.interval_s = 0.0
    instance.do_periodic_tasks()

    release.set()

    beats = [message for message in drain(outbox) if isinstance(message, Heartbeat)]
    assert beats, "the event loop sent no heartbeat while a sequence was running"
    assert beats[0].source == "sequencer"


def test_stop_sequence_is_received_while_a_sequence_runs(sequencer):
    """
    The abort path. StopSequence has to be *read* mid-run, which is only
    possible because the inbox is drained by a thread the sequence is not on.
    """
    instance, _outbox, inbox = sequencer

    reached = threading.Event()

    def waits_for_the_flag(sequence_name: str) -> None:
        reached.set()
        deadline = time.time() + REACHED_TIMEOUT_S
        while not instance.stop_requested and time.time() < deadline:
            time.sleep(0.01)

    instance.execute_sequence = waits_for_the_flag
    inbox.put(RunSequence("power_on"))
    instance.poll_core()
    assert reached.wait(timeout=REACHED_TIMEOUT_S)

    inbox.put(StopSequence())
    instance.poll_core()

    assert instance.stop_requested
    instance.sequence_thread.join(timeout=REACHED_TIMEOUT_S)
    assert not instance.sequence_is_running()


def test_a_step_waiting_for_an_answer_is_woken_by_the_event_loop(sequencer):
    """
    The deadlock blocking_messages.py warns about, made a test.

    The sequence thread blocks in PendingRequests.wait(); the answer arrives on
    the inbox and is handed over by the loop thread. On one thread this hangs
    until the five-minute timeout and the step gets None.
    """
    instance, _outbox, inbox = sequencer

    request_id = uuid4()
    reached = threading.Event()
    answer = {}

    def asks_the_operator(sequence_name: str) -> None:
        instance.pending.start(request_id)
        reached.set()
        answer["value"] = instance.pending.wait(request_id, timeout_s=REACHED_TIMEOUT_S)

    instance.execute_sequence = asks_the_operator
    inbox.put(RunSequence("power_on"))
    instance.poll_core()
    assert reached.wait(timeout=REACHED_TIMEOUT_S)

    inbox.put(SerialNumberResponse(request_id=request_id, serial_number="SN-0001"))
    instance.poll_core()

    instance.sequence_thread.join(timeout=REACHED_TIMEOUT_S)
    assert answer["value"] == "SN-0001"


def test_a_second_run_sequence_is_refused_rather_than_queued(sequencer):
    """
    Two sequences at once would interleave their progress events, so the second
    request is refused - and refused *loudly*, since the operator asked for it.
    """
    instance, outbox, inbox = sequencer
    release = start_a_blocking_sequence(instance, inbox)

    inbox.put(RunSequence("power_off"))
    instance.poll_core()

    release.set()

    errors = [message for message in drain(outbox) if isinstance(message, ModuleError)]
    assert len(errors) == 1
    assert "already running" in errors[0].message
    assert errors[0].source == "pypts.sequencer.sequencer"


def test_stop_reports_stopped_only_after_the_sequence_thread_has_ended(sequencer):
    """
    CORE exits as soon as all three modules have reported themselves stopped, so
    SequencerStopped while a sequence was still touching hardware would be a lie
    CORE acts on.
    """
    instance, outbox, inbox = sequencer

    reached = threading.Event()

    def waits_for_the_flag(sequence_name: str) -> None:
        reached.set()
        deadline = time.time() + REACHED_TIMEOUT_S
        while not instance.stop_requested and time.time() < deadline:
            time.sleep(0.01)

    instance.execute_sequence = waits_for_the_flag
    inbox.put(RunSequence("power_on"))
    instance.poll_core()
    assert reached.wait(timeout=REACHED_TIMEOUT_S)

    inbox.put(StopSequencer())
    instance.poll_core()

    assert not instance.sequence_is_running()
    assert not instance.running
    assert any(isinstance(message, SequencerStopped) for message in drain(outbox))


def test_stopping_with_no_sequence_running_is_immediate(sequencer):
    """The ordinary case: nothing to wait for, and no join budget spent."""
    instance, outbox, inbox = sequencer

    inbox.put(StopSequencer())
    started = time.time()
    instance.poll_core()

    assert time.time() - started < 1.0
    assert any(isinstance(message, SequencerStopped) for message in drain(outbox))


def test_a_stop_from_a_finished_sequence_does_not_abort_the_next_one(sequencer):
    """
    `stop_requested` is cleared when a sequence starts, not when one ends, so a
    late StopSequence cannot kill the run that follows it.
    """
    instance, _outbox, inbox = sequencer

    inbox.put(StopSequence())
    instance.poll_core()
    assert instance.stop_requested

    release = start_a_blocking_sequence(instance, inbox)
    assert not instance.stop_requested

    release.set()


def test_an_abandoned_sequence_is_reported_critical_before_sequencer_stopped(
    sequencer, monkeypatch
):
    """
    A sequence thread that outlives the join is left running, possibly mid-step
    with no teardown behind it. That is a fact about the bench, so the operator
    hears it as a CRITICAL ModuleError - and hears it *before* CORE is told the
    module stopped, or the report would read as a clean exit.
    """
    from pypts.messages.common_messages import ErrorSeverity

    instance, outbox, inbox = sequencer

    # The real 2 s budget is not worth a test's time; the code reads the module
    # global, so shortening it here exercises exactly the same branch.
    monkeypatch.setattr("pypts.sequencer.sequencer.SEQUENCE_JOIN_TIMEOUT_S", 0.05)

    # Deliberately not released: the fake body ignores stop_requested, so the
    # join times out and the thread is abandoned.
    release = start_a_blocking_sequence(instance, inbox)

    instance.stop()

    messages = [m for m in drain(outbox) if not isinstance(m, Heartbeat)]
    assert [type(m) for m in messages] == [ModuleError, SequencerStopped]
    reported = messages[0]
    assert reported.severity is ErrorSeverity.CRITICAL
    assert reported.operation == "Sequencer.stop_running_sequence"
    assert "bench state is unknown" in reported.message

    # Let the abandoned thread go, so the fixture's teardown join returns.
    release.set()


# --------------------------------------------------------------------------
# The engine itself - Phase 1
# --------------------------------------------------------------------------


def load_wait_recipe(instance, inbox, recipe_text=None):
    """Hand the Sequencer a recipe the way CORE does: UseRecipe on the inbox."""
    if recipe_text is None:
        recipe = Recipe.from_file(str(WAIT_RECIPE))
    else:
        recipe = Recipe.from_yaml_text(recipe_text)
    inbox.put(UseRecipe(recipe))
    instance.poll_core()
    return recipe


def test_use_recipe_stores_the_live_recipe(sequencer):
    instance, _outbox, inbox = sequencer
    recipe = load_wait_recipe(instance, inbox)
    assert instance.recipe is recipe


def test_run_sequence_executes_steps_in_order(sequencer):
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox)

    instance.execute_sequence("Main")

    started = [m.step_name for m in drain(outbox) if isinstance(m, StepStarted)]
    assert started == ["First wait", "Second wait"]


def test_each_step_result_is_reported_to_core(sequencer):
    """Per-step StepFinished events, so an HMI can update live."""
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox)

    instance.execute_sequence("Main")

    finished = [m.outcome for m in drain(outbox) if isinstance(m, StepFinished)]
    assert [o.step_name for o in finished] == ["First wait", "Second wait"]
    assert all(o.result is ResultType.DONE for o in finished)


def test_a_failing_step_produces_a_step_result_not_a_silent_continue(sequencer):
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox, FAILING_RECIPE)

    instance.execute_sequence("Main")

    messages = drain(outbox)
    finished = [m.outcome for m in messages if isinstance(m, StepFinished)]
    assert [o.step_name for o in finished] == ["Bad wait"], "the error must stop the sequence"
    assert finished[0].result is ResultType.ERROR
    assert "wait_time" in finished[0].error_info
    run_finished = [m for m in messages if isinstance(m, RunFinished)]
    assert [m.result for m in run_finished] == [ResultType.ERROR]


def test_stop_requested_is_checked_between_steps_not_inside_one(sequencer):
    """A step must be allowed to leave its hardware in a known state."""
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox)
    instance.stop_requested = True

    instance.execute_sequence("Main")

    messages = drain(outbox)
    assert not [m for m in messages if isinstance(m, StepStarted)]
    run_finished = [m for m in messages if isinstance(m, RunFinished)]
    assert [m.result for m in run_finished] == [ResultType.STOP]


def test_an_abort_between_steps_reports_the_finished_steps(sequencer, monkeypatch):
    """
    A mid-run abort is not an empty run: the steps that did complete are facts
    about the bench and have to reach CORE, or the report of an aborted run
    would show nothing at all.

    The sibling test above sets the flag before the run, so no step executes and
    the outcome tuple is empty either way. Here the flag is set from *inside*
    step 1, which is where the between-steps check in Step.run_steps() is the
    only thing keeping step 2 from starting.
    """
    from pypts.step.wait_step import WaitStep

    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox)

    real_step = WaitStep._step
    first_call = []

    def stops_after_the_first_step(self, runtime, step_input):
        """Completes normally - the abort must land at the boundary, not in here."""
        if not first_call:
            first_call.append(self.name)
            instance.stop_requested = True
        return real_step(self, runtime, step_input)

    monkeypatch.setattr(WaitStep, "_step", stops_after_the_first_step)

    instance.execute_sequence("Main")

    assert first_call == ["First wait"]

    messages = [m for m in drain(outbox) if not isinstance(m, Heartbeat)]
    started = [m for m in messages if isinstance(m, StepStarted)]
    finished = [m for m in messages if isinstance(m, StepFinished)]
    assert [m.step_name for m in started] == ["First wait"]
    assert [m.outcome.step_name for m in finished] == ["First wait"]

    assert isinstance(messages[-1], RunFinished)
    assert messages[-1].result is ResultType.STOP
    assert [o.step_name for o in messages[-1].outcomes] == ["First wait"]


def test_sequence_result_is_sent_once_at_the_end(sequencer):
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox)

    instance.execute_sequence("Main")

    messages = drain(outbox)
    assert len([m for m in messages if isinstance(m, RunStarted)]) == 1
    assert len([m for m in messages if isinstance(m, SequenceFinished)]) == 1
    run_finished = [m for m in messages if isinstance(m, RunFinished)]
    assert len(run_finished) == 1
    assert run_finished[0].result is ResultType.DONE
    assert [o.step_name for o in run_finished[0].outcomes] == ["First wait", "Second wait"]
    # RunFinished is the last thing a run says.
    assert isinstance(messages[-1], RunFinished)


def test_running_without_a_recipe_is_refused_with_an_error(sequencer):
    instance, outbox, _inbox = sequencer

    instance.execute_sequence("Main")

    messages = drain(outbox)
    errors = [m for m in messages if isinstance(m, ModuleError)]
    assert len(errors) == 1
    assert "No recipe" in errors[0].message
    assert not [m for m in messages if isinstance(m, RunStarted)], (
        "a refused run must not start reporting one"
    )


def test_an_unknown_sequence_name_is_refused_listing_the_real_ones(sequencer):
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox)

    instance.execute_sequence("Setup")

    errors = [m for m in drain(outbox) if isinstance(m, ModuleError)]
    assert len(errors) == 1
    assert "Setup" in errors[0].message
    assert "Main" in errors[0].message
