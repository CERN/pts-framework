# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The one transport: a typed, one-way pipe. Never blocks.

Wraps anything with put()/get_nowait(), which is why the same class serves the
HMI <-> CORE process boundary and the thread boundaries inside CORE. See
messages.md for the trace and the counters.
"""

import logging
from collections.abc import Iterator
from queue import Empty
from typing import Generic, Never, NoReturn, TypeVar

#: The union this wrapper carries, e.g. QueueWrapper[HmiToCore].
Msg = TypeVar("Msg")

# Own logger, not `from pypts.logger.log import log`: log.py imports this module.
_trace = logging.getLogger("pypts.trace")


class UnhandledMessage(Exception):
    """A handler received a message it has no branch for."""


def unhandled(message: Never) -> NoReturn:
    """
    Typed `Never`, so an unmatched member is a type error, and it raises here.
    """
    raise UnhandledMessage(f"No handler for message: {message!r}")


class QueueWrapper(Generic[Msg]):
    """A typed handle on one direction of one link. Built by whoever owns the link."""

    #: Cap on one receive(), so a busy link cannot starve the other inboxes.
    DEFAULT_BATCH = 64

    def __init__(self, queue, *, link: str = "") -> None:
        """
        Args:
            queue: anything with `put()` and `get_nowait()`.
            link: one of the constants in links.py. Names the trace lines; an
                  unnamed wrapper traces as "?".
        """
        self._queue = queue
        self.link = link
        #: Per holder, not per link: a wrapper pickled into a child process
        #: gives the child its own copy.
        self.sent = 0
        self.received = 0

    def send(self, message: Msg) -> None:
        """Hand one message to the other end. Never blocks, never inspects it."""
        # Traced before the put, so a message that fails to pickle is still recorded.
        _trace.debug("send %s %r", self.link or "?", message)
        self._queue.put(message)
        self.sent += 1

    def receive(self, limit: int = DEFAULT_BATCH) -> Iterator[Msg]:
        """
        Yield the messages waiting right now, up to `limit`. Never blocks.

        A generator, so a caller that stops early leaves the rest queued.
        """
        for _ in range(limit):
            try:
                message = self._queue.get_nowait()
            except Empty:
                return
            # Counted and traced on hand-over, not on dequeue.
            self.received += 1
            _trace.debug("recv %s %r", self.link or "?", message)
            yield message
