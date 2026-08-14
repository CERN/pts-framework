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


@pytest.mark.skip(reason=PLACEHOLDER)
def test_core_routes_hmi_exit_to_every_submodule():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_core_records_heartbeats_from_each_module():
    ...


def build_core_that_spawns_nothing():
    """
    A Core wired to plain in-process queues, so nothing is spawned.

    This is what the queue_factory seam is for - see Core.__init__.
    """
    from pypts.core.core import Core
    from pypts.messages import QueueWrapper

    return Core(
        to_hmi=QueueWrapper(queue.Queue()),
        from_hmi=QueueWrapper(queue.Queue()),
        log_queue=queue.Queue(),
        queue_factory=queue.Queue,
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


def test_a_sequencer_event_is_routed_to_the_hmi():
    """
    Progress from the Sequencer reaches the frontend, through the real routing.

    Driven by putting the message on the real inbox and turning the loop once,
    rather than by calling the handler - so the drain, the `match` and the
    forward are all exercised. This is the seam that used to need the debug
    console's injection machinery; queue_factory is all it actually takes.
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


@pytest.mark.skip(reason=PLACEHOLDER)
def test_load_recipe_command_is_handled():
    """Currently a `pass` in handle_hmi_event - Phase 1."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_start_sequence_command_is_handled():
    """Currently a `pass` in handle_hmi_event - Phase 1."""


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
