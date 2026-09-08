# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the shared frontend half (src/pypts/hmi/hmi_client.py).

Only the exit handshake so far. `wait_until_stopped()` is what a frontend's main
thread blocks in after asking CORE to shut down, so both of its branches decide
whether the application exits at all: the normal one returns as soon as the
polling thread has handled StopHmi, and the timeout one stops the frontend
itself rather than waiting for a CORE that will never answer.

The tests drive the client's real queues, and neither of them waits a real
grace period - the branch under test is chosen by how the client is driven, not
by how long the test is prepared to sit still.
"""

import logging
import queue
import threading
import time

import pytest

from pypts.hmi.hmi_client import HmiClient
from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import HmiStopped

#: What a frontend is expected to do in: the "returns at once" branch must not
#: come anywhere near this, let alone near the grace period it was given.
PROMPT_S = 1.0


@pytest.fixture
def client():
    """
    A bare HmiClient on plain queues - no window, no shell, no CORE - plus the
    queue it sends on, so a test can read what reached CORE without going
    through the module under test.
    """
    to_core: queue.Queue = queue.Queue()
    from_core: queue.Queue = queue.Queue()
    instance = HmiClient(to_core=QueueWrapper(to_core), from_core=QueueWrapper(from_core))
    return instance, to_core


def drain(a_queue):
    """Everything waiting on a queue right now, as a list."""
    messages = []
    while True:
        try:
            messages.append(a_queue.get_nowait())
        except queue.Empty:
            return messages


def test_wait_until_stopped_returns_as_soon_as_stop_arrives(client, caplog):
    """
    The normal exit. CORE answers, the polling thread calls stop(), and the wait
    must end there - not sit out the rest of the grace period, which the
    operator would see as the window refusing to close for five seconds.
    """
    instance, _to_core = client

    acknowledge = threading.Timer(0.05, instance.stop)
    acknowledge.start()
    try:
        started = time.monotonic()
        with caplog.at_level(logging.WARNING):
            instance.wait_until_stopped(grace_s=2.0)
        elapsed = time.monotonic() - started
    finally:
        acknowledge.cancel()

    assert elapsed < PROMPT_S, f"waited {elapsed:.2f}s for a stop that had already arrived"
    assert instance.running is False
    assert not [r for r in caplog.records if "did not confirm the shutdown" in r.getMessage()]


def test_wait_until_stopped_gives_up_after_the_grace_period(client, caplog):
    """
    The wedged-CORE exit. Nothing answers, so the frontend stops itself: without
    the bound the main thread would block for ever and the application could
    only be killed.
    """
    instance, to_core = client

    with caplog.at_level(logging.WARNING):
        instance.wait_until_stopped(grace_s=0.1)

    assert instance.running is False

    warnings = [r for r in caplog.records if "did not confirm the shutdown" in r.getMessage()]
    assert len(warnings) == 1, f"expected one warning, got {len(warnings)}"

    # stop() still runs in full, so CORE - if it is listening after all - is
    # told the frontend has gone rather than being left waiting for it.
    assert drain(to_core) == [HmiStopped()]


# --------------------------------------------------------------------------
# Watching CORE: the orphan case
# --------------------------------------------------------------------------


def test_a_heartbeat_from_core_is_noted(client):
    """
    The reverse direction of a protocol that used to run one way only. Without
    the branch this message would reach unhandled() and raise.
    """
    from pypts.messages.common_messages import Heartbeat
    from pypts.utilities.heartbeat_manager import CORE

    instance, _ = client
    instance.core_watch.last_seen = time.time() - 60

    instance.handle_core_message(Heartbeat(source=CORE, timestamp=time.time()))

    assert instance.core_watch.silent_for() < 1.0


def test_a_frontend_starts_with_a_watch_that_is_not_already_late(client):
    """
    A watch that began at the epoch reads as silent for fifty-odd years and
    closes the window before the first beat can arrive.
    """
    instance, _ = client

    assert not instance.core_watch.is_silent()
    assert not instance.core_watch.is_lost()


def test_a_briefly_quiet_core_is_reported_but_not_fatal(client, caplog):
    """
    Five seconds of quiet is as likely to be a stall as a death, and this
    threshold only costs a warning - so the frontend stays open.
    """
    from pypts.utilities.heartbeat_manager import HEARTBEAT_TIMEOUT_S

    instance, _ = client
    instance.core_watch.last_seen = time.time() - (HEARTBEAT_TIMEOUT_S + 1)

    with caplog.at_level(logging.DEBUG):
        instance.do_periodic_tasks()

    assert instance.running is True
    assert [r for r in caplog.records if "has stopped responding" in r.getMessage()]


def test_a_quiet_core_is_reported_once_not_once_per_tick(client, caplog):
    """
    The GUI's timer and the CLI's polling thread both call this repeatedly, and
    the silence persists. Without the latch the line explaining the failure is
    buried under copies of itself.
    """
    from pypts.utilities.heartbeat_manager import HEARTBEAT_TIMEOUT_S

    instance, _ = client
    instance.core_watch.last_seen = time.time() - (HEARTBEAT_TIMEOUT_S + 1)

    with caplog.at_level(logging.WARNING):
        for _ in range(30):
            instance.do_periodic_tasks()

    spoken = [r for r in caplog.records if "has stopped responding" in r.getMessage()]
    assert len(spoken) == 1, f"expected one warning, got {len(spoken)}"


def test_a_lost_core_closes_the_frontend(client, caplog):
    """
    The whole reason the reverse heartbeat exists. A CORE killed outright, or
    one whose loop has wedged, would otherwise leave this window open on a run
    that stopped long ago, with nobody left to send StopHmi.
    """
    from pypts.utilities.heartbeat_manager import HEARTBEAT_FATAL_S

    instance, to_core = client
    instance.core_watch.last_seen = time.time() - (HEARTBEAT_FATAL_S + 1)

    with caplog.at_level(logging.DEBUG):
        instance.do_periodic_tasks()

    assert instance.running is False
    assert any(isinstance(message, HmiStopped) for message in drain(to_core))
    assert [r for r in caplog.records if r.levelno == logging.ERROR]


def test_a_frontend_that_is_stopping_does_not_report_the_engine_as_lost(client, caplog):
    """
    A normal shutdown ends with CORE leaving its event loop, so its heartbeats
    stop by design - and the GUI's QTimer goes on firing after `running` is
    False. Without the guard every clean exit ended with a fabricated failure.
    """
    from pypts.utilities.heartbeat_manager import HEARTBEAT_FATAL_S

    instance, _ = client
    instance.running = False
    instance.core_watch.last_seen = time.time() - (HEARTBEAT_FATAL_S + 100)

    with caplog.at_level(logging.DEBUG):
        instance.do_periodic_tasks()

    assert not [r for r in caplog.records if "stopped responding" in r.getMessage()]
