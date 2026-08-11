# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The one transport in the framework.

A Channel is a typed, one-way pipe with two operations: send() puts one message
in, receive() yields the ones waiting. Whoever holds it can only send messages
belonging to the link it was created for, and the recipient handles what it
receives with a `match` that the type checker verifies is complete.

Nothing ever blocks on a queue. Each module runs an event loop that polls its
inboxes, so receive() takes what is there at that moment and returns; a message
sent between two ticks simply arrives on the next one.

The Channel wraps *any* object offering `put()` and `get_nowait()`. That is
deliberate, and it is what keeps the roadmap's thread migration cheap:

  - today the launcher and CORE hand out `multiprocessing.Queue`;
  - once Sequencer and Report become threads inside the engine process, the
    launcher hands out `queue.Queue` instead;
  - a future `--mode connect` can hand out a socket-backed queue-alike.

No module ever learns which one it holds, so none of them has to change.
"""

from collections.abc import Iterator
from queue import Empty
from typing import Generic, Never, NoReturn, Protocol, TypeVar

# The union of messages this channel carries, e.g. Channel[HmiToCore].
Msg = TypeVar("Msg")


class Observer(Protocol):
    """
    Something that wants a copy of every message a Channel carries.

    The only implementation is the debug console's tap (hmi/debug/tap.py). It is
    a Protocol rather than an import so that the transport keeps knowing nothing
    about the debug tooling: `messages` does not depend on `hmi`.

    An observer must be picklable, because a Channel carrying one is passed to a
    child process as a Process argument.
    """

    def __call__(self, link: str, message: object) -> None: ...


class UnhandledMessage(Exception):
    """
    A handler received a message it has no branch for.

    Raised by unhandled() below. The event loops catch it, log it and carry on -
    a malformed or unexpected message must be loud, but it must not take the
    module down with it.
    """


def unhandled(message: Never) -> NoReturn:
    """
    Close a `match` over a link's message union. Always the last case.

    Two jobs in one call:

      - Statically, the parameter is typed `Never`. A type checker only accepts
        the call if every member of the union has already been matched by an
        earlier `case`, so forgetting one is a reported error rather than a
        silent no-op.
      - At runtime it raises, so the same mistake is still loud in a plain
        `python -m pypts` run where no checker was involved.

    This replaces the old `case _: pass`, under which CORE quietly discarded
    every error the HMI reported and the Sequencer ignored a command CORE had a
    method to send.
    """
    raise UnhandledMessage(f"No handler for message: {message!r}")


class Channel(Generic[Msg]):
    """
    A typed handle on one direction of one link.

    Built by whoever owns the link and passed to the module that uses it - the
    launcher builds the HMI <-> CORE pair, CORE builds its links to the
    Sequencer and the Report. A module therefore cannot invent a channel to
    somebody it has no business talking to: the topology is enforced by
    construction rather than by convention.
    """

    #: Messages one receive() call yields before stopping, so that a busy link
    #: cannot starve the other queues an event loop has to service.
    DEFAULT_BATCH = 64

    def __init__(self, queue, *, link: str = "", observer: "Observer | None" = None) -> None:
        """
        Args:
            queue: anything with `put()` and `get_nowait()` - see the module
                   docstring for why the type is not pinned down here.
            link: the name of the direction this channel is, e.g. "core->hmi".
                  Only ever used for display: it is what lets the debug console
                  say which link a message was on, since a Channel is otherwise
                  anonymous. Both arguments are keyword-only so that the ordinary
                  `Channel(queue)` construction is untouched.
            observer: optional tap, called with (link, message) on every send.
                  None in every normal run - see observe() for why that matters.
        """
        self._queue = queue
        self.link = link
        self._observer = observer

        #: How many messages this channel has carried, since construction.
        #:
        #: Counted here rather than returned from receive(), so that the number
        #: is available to anything holding the channel instead of only to the
        #: caller that happened to drive the loop.
        #:
        #: IMPORTANT: these are per-process. A Channel handed to a child process
        #: is pickled, and the child increments its own copy. That is not a
        #: defect but the useful reading: a channel is one direction, so `sent`
        #: is meaningful in the process that sends on it and `received` in the
        #: process that reads it, and neither is a number the other could have
        #: produced. For a whole-system view, use the debug console, whose tap
        #: sees every link from one place.
        self.sent = 0
        self.received = 0

    def send(self, message: Msg) -> None:
        """Hand one message to the other end. Never blocks, never inspects it."""
        if self._observer is not None:
            self.observe(message)
        self._queue.put(message)
        # After the put, so a failed send is not counted as a delivery.
        self.sent += 1

    def observe(self, message: Msg) -> None:
        """
        Give the tap its copy, and never let that hurt the caller.

        The tap is a development tool sitting on the path every message in the
        framework takes. A broken or full debug queue must therefore cost the
        sender nothing more than a lost trace line, so everything here is
        swallowed - including the pickling error a message that is not
        pickle-safe would raise on the way to the console process.

        The exception is deliberately not logged. Logging goes through a Channel
        of its own, and a tap that logged its own failures on a bad day would
        generate the traffic that keeps it failing.
        """
        try:
            self._observer(self.link, message)  # type: ignore[misc]
        except Exception:  # noqa: BLE001, S110 - a debug tap must never break a run
            pass

    def receive(self, limit: int = DEFAULT_BATCH) -> Iterator[Msg]:
        """
        Yield the messages waiting right now, up to `limit`. Never blocks.

        The counterpart of send(), and used the obvious way:

            for message in self.inbox.receive():
                self.handle_core_message(message)

        It stops as soon as the queue is empty, so an idle tick yields nothing
        and costs one failed get_nowait(). The `limit` is what stops a busy link
        starving the other inboxes an event loop has to service in the same
        tick; the messages beyond it stay queued for the next one.

        A generator rather than a list, so a caller that stops early - `next()`,
        a `break`, a `take-one` test - leaves the rest of the batch on the queue
        instead of having paid to remove it.

        An exception in the loop body propagates and abandons the generator: the
        event loop that owns the module decides what a failed message means, not
        the transport. Note that the failed message itself is already off the
        queue and will not be seen again, which was equally true before.
        """
        for _ in range(limit):
            try:
                message = self._queue.get_nowait()
            except Empty:
                return
            # Counted as it is handed over rather than as it is dequeued, so the
            # number never claims a message the caller was not actually given.
            #
            # Note there is no truthiness test on `message`. The old helper had
            # `if event:` and would have dropped any message whose dataclass
            # compared falsy.
            self.received += 1
            yield message
