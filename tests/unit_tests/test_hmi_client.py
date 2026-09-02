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
