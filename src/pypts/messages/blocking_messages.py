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

from queue import Empty, SimpleQueue
from threading import Lock
from uuid import UUID

#: How long wait() blocks before giving up - an operator standing at the bench.
DEFAULT_TIMEOUT_S = 300.0


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

    def wait(self, request_id: UUID, timeout_s: float | None = None):
        """Block until the answer arrives, then return it. None on timeout."""
        with self._lock:
            slot = self._waiting.get(request_id)
        if slot is None:
            raise KeyError(f"Request {request_id} was never started")

        try:
            return slot.get(timeout=self._timeout_s if timeout_s is None else timeout_s)
        except Empty:
            return None
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
