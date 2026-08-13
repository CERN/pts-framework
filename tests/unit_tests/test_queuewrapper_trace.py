# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the message trace (src/pypts/messages/queuewrapper.py).

The trace is the whole-system view of the framework. Core <-> Sequencer and
Core <-> Report never leave the engine process, so a run log at DEBUG is the
only place their traffic can be seen at all - which is why these tests are less
about formatting than about three properties the diagnosis rests on:

  - both directions are recorded, so a message sent and never received is
    visible as a `send` with no matching `recv`;
  - nothing is recorded above DEBUG, so the trace costs a normal run nothing;
  - a message is delivered whatever the trace does, including nothing.

Everything asserts through `caplog.at_level(..., logger="pypts.trace")` rather
than a bare caplog: that sets the level on the trace logger itself, so the tests
do not depend on whatever the root level happens to be under pytest.
"""

import logging
import logging.handlers
import queue

import pytest

from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_link import StatusChanged
from pypts.messages.links import CORE_TO_HMI

TRACE_LOGGER = "pypts.trace"


def build_channel(link: str = CORE_TO_HMI) -> QueueWrapper:
    """A QueueWrapper over a plain in-process queue - no processes, no launcher."""
    return QueueWrapper(queue.Queue(), link=link)


def trace_lines(caplog) -> list[str]:
    """The rendered trace records, in order."""
    return [r.getMessage() for r in caplog.records if r.name == TRACE_LOGGER]


def test_send_is_traced_with_its_link_and_message(caplog):
    """One line per send, naming the direction and the message itself."""
    channel = build_channel()

    with caplog.at_level(logging.DEBUG, logger=TRACE_LOGGER):
        channel.send(StatusChanged("ready"))

    lines = trace_lines(caplog)
    assert len(lines) == 1, f"expected one trace line, got {lines}"
    assert lines[0].startswith("send ")
    assert CORE_TO_HMI in lines[0]
    assert "StatusChanged" in lines[0]
    assert "ready" in lines[0]


def test_send_is_traced_at_debug(caplog):
    """The trace is DEBUG, which is what makes one --log-level enough to gate it."""
    channel = build_channel()

    with caplog.at_level(logging.DEBUG, logger=TRACE_LOGGER):
        channel.send(StatusChanged("ready"))

    records = [r for r in caplog.records if r.name == TRACE_LOGGER]
    assert records[0].levelno == logging.DEBUG


def test_receive_is_traced_once_per_message(caplog):
    """Both directions, so a send with no matching recv stands out."""
    channel = build_channel()
    channel.send(StatusChanged("one"))
    channel.send(StatusChanged("two"))

    with caplog.at_level(logging.DEBUG, logger=TRACE_LOGGER):
        drained = list(channel.receive())

    assert len(drained) == 2
    received = [line for line in trace_lines(caplog) if line.startswith("recv ")]
    assert len(received) == 2, f"expected two recv lines, got {received}"
    assert all(CORE_TO_HMI in line for line in received)


def test_a_message_left_on_the_queue_is_not_traced_as_received(caplog):
    """
    `recv` means the caller was given the message, not that it was dequeued.

    receive() is a generator, so a caller that stops early leaves the rest of
    the batch queued - and therefore untraced. The trace has to agree with the
    `received` counter about what "received" means, or a reader chasing a lost
    message is misled about where it stopped.
    """
    channel = build_channel()
    channel.send(StatusChanged("one"))
    channel.send(StatusChanged("two"))

    with caplog.at_level(logging.DEBUG, logger=TRACE_LOGGER):
        first = next(iter(channel.receive()))

    assert first == StatusChanged("one")
    received = [line for line in trace_lines(caplog) if line.startswith("recv ")]
    assert len(received) == 1, f"expected one recv line, got {received}"
    assert "one" in received[0]


def test_nothing_is_traced_above_debug(caplog):
    """The one-dial guarantee: at the default level a run carries no trace."""
    channel = build_channel()

    with caplog.at_level(logging.INFO, logger=TRACE_LOGGER):
        channel.send(StatusChanged("ready"))
        list(channel.receive())

    assert trace_lines(caplog) == []


def test_the_message_is_not_formatted_when_the_trace_is_off(caplog):
    """
    The repr is only paid when a record is actually going to be emitted.

    This is what %-style arguments buy over an f-string, and it is the reason
    the trace can sit on the path of every message in the framework. The day
    someone tidies `_trace.debug("send %s %r", ...)` into an f-string, every run
    starts formatting every message at every level, and this test is what says
    so.
    """

    class CountingMessage:
        def __init__(self) -> None:
            self.reprs = 0

        def __repr__(self) -> str:
            self.reprs += 1
            return "CountingMessage()"

    channel = build_channel()

    quiet = CountingMessage()
    with caplog.at_level(logging.INFO, logger=TRACE_LOGGER):
        channel.send(quiet)
    assert quiet.reprs == 0, "the message was formatted even though the trace was off"

    loud = CountingMessage()
    with caplog.at_level(logging.DEBUG, logger=TRACE_LOGGER):
        channel.send(loud)
    # Not an exact count: every handler that renders the record calls repr, and
    # under pytest there are several. One or more is the whole claim - the
    # message is formatted when, and only when, something is going to emit it.
    assert loud.reprs >= 1


@pytest.fixture
def broken_log_queue_handler():
    """
    The real destination, with its queue broken: a QueueHandler over a queue
    whose put_nowait() always raises.

    This is the failure worth testing rather than an arbitrary exploding
    handler. logging does *not* wrap Handler.emit() in a try/except - each emit
    implementation is responsible for calling handleError() itself - so a
    hand-written broken handler would take the sender down, and saying otherwise
    would be a false guarantee. QueueHandler, which is what init_logging()
    actually installs, does guard its enqueue, and that is the path every
    message in a real run takes.

    Removed again whatever the test does, so it cannot leak into the suite.
    """

    class BrokenQueue:
        def put_nowait(self, item):
            raise RuntimeError("the log queue is broken")

    handler = logging.handlers.QueueHandler(BrokenQueue())
    logger = logging.getLogger(TRACE_LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)


def test_a_failing_log_queue_does_not_stop_the_message(broken_log_queue_handler):
    """
    The property the whole design rests on: diagnosis must never break a run.

    The old tap bought this with a try/except of its own around every send. On
    the logging path it comes from QueueHandler.emit(), so the property survives
    and the framework stopped paying code for it - but it is worth a test,
    because it is the reason it is acceptable to put the trace on the path of
    every message in the system.
    """
    channel = build_channel()

    channel.send(StatusChanged("ready"))

    assert list(channel.receive()) == [StatusChanged("ready")]


def test_an_unnamed_channel_still_delivers(caplog):
    """`QueueWrapper(queue)` with no link is legal, and traces as "?" rather than raising."""
    channel = QueueWrapper(queue.Queue())

    with caplog.at_level(logging.DEBUG, logger=TRACE_LOGGER):
        channel.send(StatusChanged("ready"))
        drained = list(channel.receive())

    assert drained == [StatusChanged("ready")]
    assert channel.link == ""
    assert all(line.split()[1] == "?" for line in trace_lines(caplog))
