# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The waiting half of a request/response pair.

    pending.start(rid); core.send(UserPromptRequest(rid, ...))
    answer = pending.wait(rid)                 # asker, on a worker thread
    pending.return_caller(rid, choice)         # event loop, draining the inbox

IMPORTANT: the thread that calls wait() must not be the one draining the inbox,
or the answer can never arrive and the module deadlocks.
"""

import time
from collections.abc import Callable
from queue import Empty, SimpleQueue
from threading import Lock
from uuid import UUID

#: How long wait() blocks before giving up - an operator standing at the bench.
DEFAULT_TIMEOUT_S = 300.0

#: How often wait() surfaces to look at should_abort. Short enough that an
#: operator's Stop is honoured while a question is on screen, long enough that
#: waiting five minutes costs nothing measurable.
POLL_INTERVAL_S = 0.1


class PendingRequests:
    """Requests still in flight, keyed by request_id. Safe from two threads."""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._lock = Lock()
        self._waiting: dict[UUID, SimpleQueue] = {}

    def start(self, request_id: UUID) -> None:
        """Register a request before sending it, or a fast responder wins the race."""
        with self._lock:
            self._waiting[request_id] = SimpleQueue()

    def wait(
        self,
        request_id: UUID,
        timeout_s: float | None = None,
        should_abort: Callable[[], bool] | None = None,
    ):
        """
        Block until the answer arrives, then return it. None if none came.

        The wait is a poll rather than one long sleep so `should_abort` gets
        looked at every POLL_INTERVAL_S - without it, an operator pressing Stop
        while a question is on screen would wait out the whole timeout. The loop
        lives here rather than in the caller because the slot is registered once
        and cancelled once: a caller looping on short waits of its own would
        cancel its own request on the first empty turn.

        A returned value is the answer whatever it is - None is a real answer
        (the operator declined) and is indistinguishable from a timeout on
        purpose: the asker treats both the same.
        """
        with self._lock:
            slot = self._waiting.get(request_id)
        if slot is None:
            raise KeyError(f"Request {request_id} was never started")

        deadline = time.monotonic() + (self._timeout_s if timeout_s is None else timeout_s)
        try:
            while True:
                if should_abort is not None and should_abort():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    return slot.get(timeout=min(POLL_INTERVAL_S, remaining))
                except Empty:
                    continue
        finally:
            self.cancel(request_id)

    def return_caller(self, request_id: UUID, value) -> bool:
        """
        Wake whoever is waiting on this request. False if nobody is.

        Worth logging: it means the two ends disagree about what is in flight.
        """
        with self._lock:
            slot = self._waiting.get(request_id)
        if slot is None:
            return False
        slot.put(value)
        return True

    def cancel(self, request_id: UUID) -> None:
        """Forget a request. Idempotent, so wait() can call it unconditionally."""
        with self._lock:
            self._waiting.pop(request_id, None)
