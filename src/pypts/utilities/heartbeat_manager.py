# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Periodic proof that a module's event loop is still turning.
"""

import time

from pypts.messages.common import Heartbeat

#: Seconds between heartbeats. CORE's timeout is several times this, so a single
#: slow loop iteration does not read as a dead module.
DEFAULT_INTERVAL_S = 1.0


class HeartbeatManager:
    """
    Sends a Heartbeat on `channel` at most once per interval.

    Call tick() from the module's periodic tasks; it is cheap enough to call on
    every loop iteration and decides for itself when a heartbeat is due.

    Args:
        channel: the module's outbox to CORE.
        source: the name CORE knows this module by. It travels on the message so
                that one CORE handler can serve every link, instead of three
                that differ only in which dict key they write.
        interval_s: minimum seconds between heartbeats.
    """

    def __init__(self, channel, source: str, interval_s: float = DEFAULT_INTERVAL_S) -> None:
        self.channel = channel
        self.source = source
        self.interval_s = interval_s
        self.last_sent = 0.0

    def tick(self) -> None:
        now = time.time()
        if now - self.last_sent > self.interval_s:
            self.channel.send(Heartbeat(source=self.source, timestamp=now))
            self.last_sent = now
