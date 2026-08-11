# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The observer that copies channel traffic to the debug console.

One instance is built by the launcher under `--mode debug` and handed to every
tapped Channel, including the ones CORE builds for its submodules - which is how
traffic inside the engine process reaches a console process that has no other
route to it. Each process ends up with its own unpickled copy writing into the
same queue; none of them coordinate, and none of them need to.
"""

import time
from contextlib import contextmanager
from queue import Full

from pypts.messages.debug_link import TapRecord

#: repr() is truncated to this many characters. A RunFinished carrying a few
#: hundred StepOutcomes would otherwise put a screen-wide row in the trace and
#: pay to pickle it, for a payload nobody can read anyway.
MAX_PAYLOAD_CHARS = 2000


class ChannelTap:
    """
    Callable observer for Channel. Picklable, because it crosses to the engine
    process as a Process argument.

    Attributes:
        injecting: set by CORE around a send it is making on the console's
            behalf, so the resulting record is marked as simulated. It is a
            plain attribute rather than an argument because the tap is called
            from inside Channel.send(), which knows nothing about injection.
            Safe without a lock: an event loop sets it around one synchronous
            send on its own thread.
    """

    def __init__(self, records) -> None:
        """
        Args:
            records: a queue the console drains. Anything with put_nowait().
        """
        self._records = records
        self.injecting = False

    def __call__(self, link: str, message: object) -> None:
        """
        Record one send.

        Exceptions are not caught here - Channel.observe() already swallows
        everything on the tap's behalf, and catching twice would only hide which
        layer failed while debugging the debugger.
        """
        payload = repr(message)
        if len(payload) > MAX_PAYLOAD_CHARS:
            payload = f"{payload[:MAX_PAYLOAD_CHARS]}... [{len(payload)} chars]"

        try:
            self._records.put_nowait(
                TapRecord(
                    timestamp=time.time(),
                    link=link,
                    message_type=type(message).__name__,
                    payload=payload,
                    injected=self.injecting,
                )
            )
        except Full:
            # A bounded queue that has backed up. Dropping the trace line is
            # always better than delaying the message it describes.
            pass

    @contextmanager
    def marking_injected(self):
        """
        Mark every send made inside the block as simulated.

        Restores the previous value rather than setting False, so that a nested
        use - CORE injecting a message whose handling injects another - cannot
        clear the outer mark halfway through.
        """
        previous = self.injecting
        self.injecting = True
        try:
            yield
        finally:
            self.injecting = previous
