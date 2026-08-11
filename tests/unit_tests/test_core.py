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
    from pypts.messages import Channel

    return Core(
        to_hmi=Channel(queue.Queue()),
        from_hmi=Channel(queue.Queue()),
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
    from pypts.messages.common import Heartbeat

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


@pytest.mark.skip(reason=PLACEHOLDER)
def test_load_recipe_command_is_handled():
    """Currently a `pass` in handle_hmi_event - Phase 1."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_start_sequence_command_is_handled():
    """Currently a `pass` in handle_hmi_event - Phase 1."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_module_error_events_are_aggregated_not_swallowed():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_core_stops_when_all_modules_have_exited():
    ...
