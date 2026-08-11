# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The waiting half of a request/response pair.

A module that asks a question sends a request carrying a fresh `request_id`,
then blocks until the matching response arrives on its inbox. The event loop
that drains that inbox hands the answer over by calling resolve(); the asking
code wakes up in wait().

    # asking side (a step, on its own worker thread)
    request_id = uuid4()
    pending.start(request_id)
    core.send(UserPromptRequest(request_id, "Connect the DUT", ("OK", "Abort")))
    answer = pending.wait(request_id)          # None if it timed out

    # event loop, draining the inbox
    case UserPromptResponse(request_id=rid, choice=choice):
        pending.resolve(rid, choice)

IMPORTANT: the thread that calls wait() must not be the thread that drains the
channel, or the answer can never arrive and the module deadlocks. The Sequencer
is single-threaded today, so porting user-interaction steps in Phase 1 means
running the sequence on its own worker thread while the event loop keeps
turning. This is noted as a TODO in the roadmap.

Nothing uses this yet - it lands with the execution engine.
"""

from queue import Empty, SimpleQueue
from threading import Lock
from uuid import UUID

#: How long wait() blocks before giving up. Five minutes matches the timeout the
#: old user-interaction steps used for an operator standing at the bench.
DEFAULT_TIMEOUT_S = 300.0


class PendingRequests:
    """
    Requests this module has sent and is still waiting on, keyed by request_id.

    Safe to use from two threads: the asker and the event loop.
    """

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._lock = Lock()
        self._waiting: dict[UUID, SimpleQueue] = {}

    def start(self, request_id: UUID) -> None:
        """
        Register a request before sending it.

        Call this first. Registering after the send would race a fast responder,
        and the answer would be dropped as unknown.
        """
        with self._lock:
            self._waiting[request_id] = SimpleQueue()

    def wait(self, request_id: UUID, timeout_s: float | None = None):
        """
        Block until the answer arrives, then return it. Returns None on timeout.

        The entry is always removed, so a late answer to a timed-out request is
        discarded by resolve() rather than being handed to nobody.
        """
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

    def resolve(self, request_id: UUID, value) -> bool:
        """
        Hand an answer to whoever is waiting for it.

        Returns False if nobody is - an answer to a request that already timed
        out, or one this module never sent. The caller should log that rather
        than ignore it; it means the two ends disagree about what is in flight.
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
