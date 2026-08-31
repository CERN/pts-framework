# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Periodic proof that a module's event loop is still turning.

Both halves of the heartbeat protocol are named here: how often a module sends
one, how long CORE waits before presuming it dead, and what the three modules
are called. They belong together because they only mean anything as a set - a
timeout shorter than the interval declares every module dead, and a module name
that does not match the key in CORE's tables is a heartbeat CORE cannot place.

The names in particular used to be spelled four times: once as `MODULE_NAME` in
each of the three modules and again as three constants in `core.py`. Nothing
checked that they agreed.

This module imports almost nothing on purpose. The Debug Monitor needs the
timeout and the names to fold liveness out of a run log, and it used to reach
them through `pypts.core.core` - which loads the Sequencer, the Report, the
configuration and every link module, thirty in all, for four constants.
"""

import time

from pypts.messages.common_messages import Heartbeat

#: Seconds between heartbeats. The timeout below is several times this, so a
#: single slow loop iteration does not read as a dead module.
DEFAULT_INTERVAL_S = 1.0

#: How long CORE waits before presuming a module dead. Only armed for modules
#: still expected to be running: one that has reported itself stopped is quiet
#: for a known reason.
HEARTBEAT_TIMEOUT_S = 5.0

#: The names CORE knows the modules by. Each module puts its own name on every
#: Heartbeat as `source`, which is what lets one CORE handler serve all three
#: links instead of three that differ only in which dict key they write.
HMI = "hmi"
SEQUENCER = "sequencer"
REPORT = "report"


class HeartbeatManager:
    """
    Sends a Heartbeat on `outbox` at most once per interval.

    Call tick() from the module's periodic tasks; it is cheap enough to call on
    every loop iteration and decides for itself when a heartbeat is due.

    Args:
        outbox: the module's QueueWrapper towards CORE.
        source: the name CORE knows this module by. It travels on the message so
                that one CORE handler can serve every link, instead of three
                that differ only in which dict key they write.
        interval_s: minimum seconds between heartbeats.
    """

    def __init__(self, outbox, source: str, interval_s: float = DEFAULT_INTERVAL_S) -> None:
        self.outbox = outbox
        self.source = source
        self.interval_s = interval_s
        self.last_sent = 0.0

    def tick(self) -> None:
        now = time.time()
        if now - self.last_sent > self.interval_s:
            self.outbox.send(Heartbeat(source=self.source, timestamp=now))
            self.last_sent = now
