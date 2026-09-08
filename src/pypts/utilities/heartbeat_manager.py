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

#: How long silence has to last before it *ends the run* rather than being
#: reported. Three times the timeout above, deliberately: the two thresholds do
#: different jobs and must not share a number.
#:
#: The timeout is a diagnostic - it costs a WARNING and nothing else, so it can
#: afford to be wrong. This one aborts a technician's test, so it must not be.
#: Five seconds of silence is a stall (a large recipe parsed inline in CORE's
#: loop, a native dialog starving a timer, a machine that swapped); fifteen is a
#: module that is not coming back. Anything acting on this reports at ERROR and
#: names what went quiet - see Core.do_periodic_tasks() and roadmap 1.38.
HEARTBEAT_FATAL_S = 15.0

#: The names CORE knows the modules by. Each module puts its own name on every
#: Heartbeat as `source`, which is what lets one CORE handler serve all three
#: links instead of three that differ only in which dict key they write.
HMI = "hmi"
SEQUENCER = "sequencer"
REPORT = "report"

#: CORE's own name, for the one heartbeat that travels the other way. Not in the
#: three above: those are the modules CORE *watches*, and it does not watch
#: itself. See HeartbeatWatch for why only the HMI is sent one.
CORE = "core"


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


class HeartbeatWatch:
    """
    The receiving half: how long is it since the other end last spoke?

    Where `HeartbeatManager` sends, this watches. It is deliberately small - a
    timestamp and two thresholds - because the only thing that varies between
    users is what they *do* about silence, and that is not this class's
    business.

    **Only the HMI watches CORE.** The Sequencer and the Report are threads of
    CORE's process: they cannot outlive it, so a heartbeat towards them would
    watch for something that cannot happen and double the trace traffic doing
    it. The HMI is the one module in a process of its own, and so the one that
    can be left running with nothing on the other end of its link - a CORE that
    was killed outright, or one whose event loop has wedged while the process
    stays up.

    Args:
        source: the name of the module being watched, for the caller's log line.
        timeout_s: silence after which `is_silent()` is True - worth reporting.
        fatal_s: silence after which `is_lost()` is True - worth acting on.
    """

    def __init__(
        self,
        source: str = CORE,
        timeout_s: float = HEARTBEAT_TIMEOUT_S,
        fatal_s: float = HEARTBEAT_FATAL_S,
    ) -> None:
        self.source = source
        self.timeout_s = timeout_s
        self.fatal_s = fatal_s

        # Construction time, not zero: a watch that starts at the epoch reads as
        # silent for fifty-odd years and fires before the first beat can arrive.
        self.last_seen = time.time()

        #: One report per outage, not one per loop iteration. The caller's loop
        #: turns every few milliseconds and silence persists, so without this the
        #: line explaining the failure is buried under thousands of copies of
        #: itself. note() clears it, so a second outage is reported afresh.
        self.reported = False

    def note(self) -> None:
        """Record that the watched module has just spoken."""
        self.last_seen = time.time()
        self.reported = False

    def silent_for(self) -> float:
        """Seconds since the last heartbeat."""
        return time.time() - self.last_seen

    def is_silent(self) -> bool:
        """True once the other end has missed the reporting threshold."""
        return self.silent_for() > self.timeout_s

    def is_lost(self) -> bool:
        """True once the silence has lasted long enough to act on."""
        return self.silent_for() > self.fatal_s
