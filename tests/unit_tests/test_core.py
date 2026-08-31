# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the CORE module (src/pypts/core/).

SKELETON ONLY - placeholders declaring intended coverage. See
resources/roadmap/pypts_roadmap.md.

Note the agreed topology change: Sequencer and Report become *threads* inside
the engine process, with the same interface classes. Tests written here should
address the interfaces, not multiprocessing, so they survive that change.
"""

import logging
import queue
import time

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_core_starts_its_submodules():
    ...


def build_core_that_spawns_nothing():
    """
    A Core with every link wired up and nothing spawned.

    `Core.__init__` only builds the queues; `start_submodules()` is what starts
    the Sequencer and the Report threads. So a test can construct a Core, put a
    message on one of its links by hand and drive a single handler, with no
    thread running behind it.
    """
    from pypts.core.core import Core
    from pypts.messages import QueueWrapper

    return Core(
        to_hmi=QueueWrapper(queue.Queue()),
        from_hmi=QueueWrapper(queue.Queue()),
        log_queue=queue.Queue(),
    )


def test_heartbeat_timeout_warns_once_per_outage(caplog):
    """A timed-out module must not be re-reported on every tick of the main loop.

    The loop turns every 10 ms, so without a latch a single dead module writes
    ~100 identical warnings a second for the rest of the run.
    """
    from pypts.core.core import HEARTBEAT_TIMEOUT_S, SEQUENCER

    core = build_core_that_spawns_nothing()
    # Pretend the Sequencer was last heard from well past the timeout.
    core.last_heartbeat[SEQUENCER] = time.time() - (HEARTBEAT_TIMEOUT_S + 1)

    with caplog.at_level(logging.WARNING):
        for _ in range(50):
            core.do_periodic_tasks()

    timeouts = [r for r in caplog.records if "Heartbeat timeout" in r.message]
    assert len(timeouts) == 1, f"expected one warning, got {len(timeouts)}"
    assert SEQUENCER in timeouts[0].message


def test_heartbeat_timeout_is_reported_again_after_the_module_recovers(caplog):
    """The latch must clear when the module answers, so a second outage is seen."""
    from pypts.core.core import HEARTBEAT_TIMEOUT_S, SEQUENCER
    from pypts.messages.common_messages import Heartbeat

    core = build_core_that_spawns_nothing()
    stale = time.time() - (HEARTBEAT_TIMEOUT_S + 1)

    with caplog.at_level(logging.WARNING):
        core.last_heartbeat[SEQUENCER] = stale
        core.do_periodic_tasks()
        core.do_periodic_tasks()

        # The module comes back, then goes quiet a second time.
        core.note_heartbeat(Heartbeat(source=SEQUENCER, timestamp=time.time()))
        core.last_heartbeat[SEQUENCER] = stale
        core.do_periodic_tasks()

    timeouts = [r for r in caplog.records if "Heartbeat timeout" in r.message]
    assert len(timeouts) == 2, f"expected two warnings, got {len(timeouts)}"


def test_a_stopped_module_does_not_produce_timeout_warnings(caplog):
    """A module that reported itself stopped is not late, it is finished."""
    from pypts.core.core import HEARTBEAT_TIMEOUT_S, SEQUENCER

    core = build_core_that_spawns_nothing()
    core.last_heartbeat[SEQUENCER] = time.time() - (HEARTBEAT_TIMEOUT_S + 1)
    core.module_running[SEQUENCER] = False

    with caplog.at_level(logging.WARNING):
        core.do_periodic_tasks()

    assert not [r for r in caplog.records if "Heartbeat timeout" in r.message]


def test_core_records_heartbeats_from_each_module():
    """
    All three liveness tables are fed through the real routing.

    Each module's beat arrives on its own link and each link has its own
    handler, so "the HMI's beat is recorded" says nothing about the other two -
    the branch could be missing from either of the other handlers and every
    other test here would still pass.
    """
    from pypts.messages.common_messages import Heartbeat
    from pypts.utilities.heartbeat_manager import HMI, REPORT, SEQUENCER

    core = build_core_that_spawns_nothing()
    inboxes = {
        HMI: core.from_hmi,
        SEQUENCER: core.from_sequencer,
        REPORT: core.from_report,
    }
    # Distinct, and none of them "now", so a beat recorded against the wrong
    # module is a failure rather than a coincidence.
    timestamps = {HMI: 1_700_000_001.0, SEQUENCER: 1_700_000_002.0, REPORT: 1_700_000_003.0}

    for name, inbox in inboxes.items():
        inbox.send(Heartbeat(source=name, timestamp=timestamps[name]))
    core.poll_all_sources()

    assert core.last_heartbeat == timestamps


def test_a_poisoned_message_does_not_stop_the_mediator(caplog):
    """
    CORE is the module errors are reported *to*, so it cannot be allowed to die
    on one. A message with no branch is logged and dropped; the link keeps
    working, and what was behind the bad message is delivered on the next tick
    rather than lost.
    """
    from pypts.messages.common_messages import Heartbeat
    from pypts.utilities.heartbeat_manager import REPORT

    core = build_core_that_spawns_nothing()

    core.from_report.send("not a message")
    core.from_report.send(Heartbeat(source=REPORT, timestamp=1_700_000_003.0))

    with caplog.at_level(logging.ERROR):
        # The first poll trips over the poison and abandons the rest of the
        # batch; the second one finds the good message still queued.
        core.poll_all_sources()
        core.poll_all_sources()

    assert core.running is True
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, f"expected one error, got {len(errors)}"
    assert "No handler for message" in errors[0].getMessage()
    assert core.last_heartbeat[REPORT] == 1_700_000_003.0


def test_a_sequencer_event_is_routed_to_the_hmi():
    """
    Progress from the Sequencer reaches the frontend, through the real routing.

    Driven by putting the message on the real inbox and turning the loop once,
    rather than by calling the handler - so the drain, the `match` and the
    forward are all exercised. This is the seam that used to need the debug
    console's injection machinery; a Core with its links built and its threads
    not started is all it actually takes.
    """
    from uuid import uuid4

    from pypts.messages.common_messages import ResultType, StepOutcome
    from pypts.messages.run_events import StepFinished

    core = build_core_that_spawns_nothing()
    outcome = StepOutcome(
        step_id=uuid4(), step_name="measure", result=ResultType.PASS, error_info=""
    )

    core.from_sequencer.send(StepFinished(outcome=outcome))
    core.poll_all_sources()

    assert list(core.to_hmi.receive()) == [StepFinished(outcome=outcome)]


def test_load_recipe_command_is_handled():
    """
    LoadRecipe -> CORE parses and validates -> RecipeLoaded to the HMI, and the
    *live* Recipe object to the Sequencer.

    Identity, not equality, on the handoff: the Sequencer runs the very object
    CORE holds - one process, nothing pickled, which is the sanctioned way the
    engine gets rich objects (see core.py's module docstring).
    """
    from pathlib import Path

    from pypts.messages.core_hmi_communication import LoadRecipe
    from pypts.messages.core_sequencer_communication import UseRecipe
    from pypts.messages.run_events import RecipeLoaded

    recipe_path = Path(__file__).parent / "data" / "wait_recipe.yml"
    core = build_core_that_spawns_nothing()

    core.from_hmi.send(LoadRecipe(recipe_path=str(recipe_path)))
    core.poll_all_sources()

    to_hmi = list(core.to_hmi.receive())
    assert len(to_hmi) == 1
    loaded = to_hmi[0]
    assert isinstance(loaded, RecipeLoaded)
    assert loaded.recipe_name == "Wait demo"
    assert loaded.recipe_version == "1.0.0"
    assert loaded.main_sequence == "Main"
    # The summary describes the very recipe CORE holds - step ids are random
    # per parse, so compare against the live object, never literals.
    assert [s.sequence_name for s in loaded.sequences] == ["Main"]
    summary_steps = loaded.sequences[0].steps
    real_steps = core.recipe.sequences["Main"].steps
    assert [s.step_name for s in summary_steps] == ["First wait", "Second wait"]
    assert [s.step_id for s in summary_steps] == [step.id for step in real_steps]
    handoff = list(core.to_sequencer.receive())
    assert len(handoff) == 1
    assert isinstance(handoff[0], UseRecipe)
    assert handoff[0].recipe is core.recipe


def test_start_sequence_command_is_handled():
    from pypts.messages.core_hmi_communication import StartSequence
    from pypts.messages.core_sequencer_communication import RunSequence

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(StartSequence(sequence_name="Main"))
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == [RunSequence(sequence_name="Main")]


def test_stop_sequence_from_hmi_is_forwarded_to_the_sequencer():
    """The operator's abort: CORE relays the same object, like the responses."""
    from pypts.messages.run_events import StopSequence

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(StopSequence())
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == [StopSequence()]


def test_a_module_error_is_logged_naming_the_method_and_shown_to_the_operator(caplog):
    """
    The whole error path, through the real routing: reported by a module, logged
    by CORE, forwarded to the frontend.

    The line has to name the *method*, not just the module - `source` alone says
    "pypts.sequencer.sequencer", and a module has twenty methods.
    """
    from pypts.messages.common_messages import ErrorSeverity, ModuleError
    from pypts.messages.core_hmi_communication import ModuleErrorReported

    core = build_core_that_spawns_nothing()
    error = ModuleError(
        source="pypts.sequencer.sequencer",
        severity=ErrorSeverity.ERROR,
        message="the DUT did not answer",
        operation="Sequencer.execute_sequence",
        error_type="TimeoutError",
    )

    core.from_sequencer.send(error)
    with caplog.at_level(logging.WARNING):
        core.poll_all_sources()

    assert list(core.to_hmi.receive()) == [ModuleErrorReported(error)]

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "Sequencer.execute_sequence" in logged
    assert "TimeoutError: the DUT did not answer" in logged


def test_the_log_level_and_the_operator_both_follow_the_severity(caplog):
    """
    The sender rates its own failure - it is the only one who can - and CORE
    takes it at its word. Until the severity meant something, every reported
    failure was an ERROR in the log whatever the sender thought of it.

    A WARNING stays in the log and is deliberately *not* forwarded: that rule is
    what keeps the operator's runtime log readable during a long run.
    """
    from pypts.messages.common_messages import ErrorSeverity, ModuleError

    core = build_core_that_spawns_nothing()

    for severity, expected_level in (
        (ErrorSeverity.WARNING, logging.WARNING),
        (ErrorSeverity.CRITICAL, logging.CRITICAL),
    ):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            core.handle_module_error(
                ModuleError(source="pypts.report.report", severity=severity, message="disk full")
            )
        assert [record.levelno for record in caplog.records] == [expected_level]

    # One forwarded message in total: the CRITICAL. The WARNING stopped at CORE.
    assert len(list(core.to_hmi.receive())) == 1


def test_core_stops_when_all_modules_have_exited(caplog):
    """The clean path: everyone answered, so CORE leaves and says so."""
    core = build_core_that_spawns_nothing()

    with caplog.at_level(logging.INFO):
        core.stop_all_modules()
        for name in core.module_running:
            core.module_running[name] = False
        core.check_stop_status()

    assert core.running is False
    assert any("All modules stopped cleanly" in r.message for r in caplog.records)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_core_keeps_waiting_while_a_module_is_still_running():
    """Inside the budget, a module that has not answered yet is not late."""
    from pypts.core.core import SEQUENCER

    core = build_core_that_spawns_nothing()

    core.stop_all_modules()
    for name in core.module_running:
        core.module_running[name] = False
    core.module_running[SEQUENCER] = True

    core.check_stop_status()

    assert core.running is True


def test_a_module_that_never_answers_does_not_hold_core_forever(caplog):
    """
    The whole point of the deadline. Before it, a module that died without
    reporting left CORE in its loop until the launcher terminated the process -
    which took the log with it, losing the one fact worth keeping.
    """
    from pypts.core.core import REPORT, SEQUENCER

    core = build_core_that_spawns_nothing()

    core.stop_all_modules()
    for name in core.module_running:
        core.module_running[name] = False
    core.module_running[SEQUENCER] = True
    core.module_running[REPORT] = True

    # Pretend the budget has already run out, rather than sleeping through it.
    core.shutdown_deadline = time.time() - 1

    with caplog.at_level(logging.ERROR):
        core.check_stop_status()

    assert core.running is False

    abandoned = [r for r in caplog.records if "abandoned" in r.message]
    assert len(abandoned) == 1, f"expected one error, got {len(abandoned)}"
    # Naming them is most of the value: "something hung" is not actionable.
    assert SEQUENCER in abandoned[0].message
    assert REPORT in abandoned[0].message


def test_the_shutdown_budget_starts_when_the_stop_is_requested():
    """
    Not at the first unanswered check, or the budget would cover only the tail
    of a shutdown rather than the whole of it.
    """
    from pypts.core.core import Core

    core = build_core_that_spawns_nothing()

    assert core.shutdown_deadline is None

    before = time.time()
    core.stop_all_modules()

    assert core.shutdown_deadline is not None
    assert before + Core.SHUTDOWN_TIMEOUT_S <= core.shutdown_deadline
    assert core.shutdown_deadline <= time.time() + Core.SHUTDOWN_TIMEOUT_S


def test_a_module_still_running_before_any_stop_request_is_not_abandoned():
    """
    No stop asked for means no deadline. A CORE sitting idle in a long run must
    never decide on its own that the modules are late to a shutdown nobody
    requested.
    """
    core = build_core_that_spawns_nothing()

    core.check_stop_status()

    assert core.running is True
    assert core.shutdown_deadline is None


def test_shutdown_holds_stop_report_until_the_sequencer_has_stopped():
    """
    The Report is stopped LAST. Stopping it first threw away every step of a run
    aborted by shutdown: the Report closed within one 10 ms tick while the
    Sequencer was still unwinding, so the tail it emitted was never drained.
    """
    from pypts.messages.core_hmi_communication import ShutdownRequested, StopHmi
    from pypts.messages.core_report_communication import StopReport
    from pypts.messages.core_sequencer_communication import SequencerStopped, StopSequencer

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(ShutdownRequested())
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == [StopSequencer()]
    assert list(core.to_hmi.receive()) == [StopHmi()]
    assert list(core.to_report.receive()) == []

    core.from_sequencer.send(SequencerStopped())
    core.poll_all_sources()

    assert list(core.to_report.receive()) == [StopReport()]


def test_the_aborted_runs_tail_reaches_the_report_before_stop():
    """
    One queue, so the order is the guarantee: the aborted run's RunFinished and
    the GenerateReport behind it are both in front of the held StopReport.
    """
    from pypts.messages.common_messages import ResultType
    from pypts.messages.core_hmi_communication import ShutdownRequested
    from pypts.messages.core_report_communication import GenerateReport, StopReport
    from pypts.messages.core_sequencer_communication import SequencerStopped
    from pypts.messages.run_events import RunFinished

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(ShutdownRequested())
    core.poll_all_sources()

    finished = RunFinished(result=ResultType.STOP, outcomes=())
    core.from_sequencer.send(finished)
    core.from_sequencer.send(SequencerStopped())
    core.poll_all_sources()

    assert list(core.to_report.receive()) == [finished, GenerateReport(), StopReport()]


def test_shutdown_deadline_releases_the_held_stop_report(caplog):
    """
    A Sequencer that never answers must not leave the Report held open for ever.
    The deadline releases the stop it was holding, then abandons what is late.
    """
    from pypts.messages.core_hmi_communication import ShutdownRequested
    from pypts.messages.core_report_communication import StopReport

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(ShutdownRequested())
    core.poll_all_sources()

    # Pretend the budget has already run out, rather than sleeping through it.
    core.shutdown_deadline = time.time() - 1

    with caplog.at_level(logging.ERROR):
        core.check_stop_status()

    assert list(core.to_report.receive()) == [StopReport()]
    assert [r for r in caplog.records if "abandoned" in r.message]


def test_core_routes_hmi_exit_to_every_submodule():
    """
    The shutdown fan-out: each of the three gets exactly its own stop message
    and nothing else, across the two phases the handshake takes.

    Sibling of test_shutdown_holds_stop_report_until_the_sequencer_has_stopped,
    which pins *when* the Report is told; this one pins *that all three are
    told*, which is the claim a send dropped from stop_all_modules() or from
    release_stop_report() would break.
    """
    from pypts.messages.core_hmi_communication import ShutdownRequested, StopHmi
    from pypts.messages.core_report_communication import StopReport
    from pypts.messages.core_sequencer_communication import SequencerStopped, StopSequencer

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(ShutdownRequested())
    core.poll_all_sources()

    core.from_sequencer.send(SequencerStopped())
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == [StopSequencer()]
    assert list(core.to_hmi.receive()) == [StopHmi()]
    assert list(core.to_report.receive()) == [StopReport()]


def test_a_second_shutdown_request_sends_nothing_new():
    """
    Shutdown is legitimately asked for twice - by the frontend and again by the
    launcher - and the guard must still hold now that the sends have moved.
    """
    from pypts.messages.core_hmi_communication import ShutdownRequested, StopHmi
    from pypts.messages.core_sequencer_communication import StopSequencer

    core = build_core_that_spawns_nothing()

    core.from_hmi.send(ShutdownRequested())
    core.from_hmi.send(ShutdownRequested())
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == [StopSequencer()]
    assert list(core.to_hmi.receive()) == [StopHmi()]


# --------------------------------------------------------------------------
# Run events reach the Report (roadmap: the report wiring)
# --------------------------------------------------------------------------


def a_step_executed():
    from uuid import uuid4

    from pypts.messages.common_messages import ResultType, StepOutcome
    from pypts.messages.run_events import StepExecuted

    return StepExecuted(
        outcome=StepOutcome(step_id=uuid4(), step_name="measure", result=ResultType.PASS),
        step_type="WaitStep",
        inputs={"wait_time": "0.5"},
        outputs={},
        started_at=1_760_000_000.5,
        duration_s=0.5,
    )


def test_run_started_and_sequence_started_reach_report_and_hmi():
    """The Report needs the run brackets to open its folder and name its rows."""
    from pypts.messages.run_events import RunStarted, SequenceStarted

    core = build_core_that_spawns_nothing()
    started = RunStarted(recipe_name="Wait demo", recipe_description="")
    sequence = SequenceStarted(sequence_name="Main")

    core.from_sequencer.send(started)
    core.from_sequencer.send(sequence)
    core.poll_all_sources()

    assert list(core.to_report.receive()) == [started, sequence]
    assert list(core.to_hmi.receive()) == [started, sequence]


def test_run_finished_triggers_report_generation():
    """CORE forwards RunFinished to the Report and asks for the report in the
    same breath - the ordering on one queue is what lets the Report close the
    CSV before it is asked to generate."""
    from pypts.messages.common_messages import ResultType
    from pypts.messages.core_report_communication import GenerateReport
    from pypts.messages.run_events import RunFinished

    core = build_core_that_spawns_nothing()
    finished = RunFinished(result=ResultType.DONE)

    core.from_sequencer.send(finished)
    core.poll_all_sources()

    assert list(core.to_report.receive()) == [finished, GenerateReport()]
    assert list(core.to_hmi.receive()) == [finished]


def test_step_executed_goes_to_the_report_not_the_hmi():
    """The rich record stays inside the engine process; the HMI already got the
    flat StepFinished."""
    core = build_core_that_spawns_nothing()
    executed = a_step_executed()

    core.from_sequencer.send(executed)
    core.poll_all_sources()

    assert list(core.to_report.receive()) == [executed]
    assert list(core.to_hmi.receive()) == []


def test_report_generated_is_relayed_as_report_ready():
    """The operator learns where the report is, in a message a frontend can
    wire a button to."""
    from pathlib import Path

    from pypts.messages.core_hmi_communication import ReportReady, StatusChanged
    from pypts.messages.core_report_communication import ReportGenerated

    core = build_core_that_spawns_nothing()
    report_path = str(Path("reports") / "run_1" / "report.html")

    core.from_report.send(ReportGenerated(report_path=report_path))
    core.poll_all_sources()

    to_hmi = list(core.to_hmi.receive())
    assert [type(m) for m in to_hmi] == [StatusChanged, ReportReady]
    ready = to_hmi[1]
    assert ready.report_path == report_path
    assert ready.report_dir == str(Path("reports") / "run_1")
