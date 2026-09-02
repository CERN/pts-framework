# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Who is alive, folded out of the run log.

None of CORE's liveness state ever leaves CORE. `module_running`,
`last_heartbeat` and `heartbeat_lost` are three dicts in `core.py`, a heartbeat
timeout produces a `log.warning` and nothing else, and no message on the
`core->hmi` link carries any of it. A frontend cannot ask.

It does not have to. Every `Heartbeat` is a message, every message crosses a
`QueueWrapper`, and every QueueWrapper traces itself - so the run log already contains
each module's pulse at 1 Hz. This module folds that stream back into the state
CORE keeps privately, from three sources:

  1. Heartbeat traces, which give last-seen directly.
  2. The stopped messages - `SequencerStopped`, `ReportStopped`, `HmiStopped` -
     which distinguish a module that said goodbye from one that vanished.
  3. CORE's own log lines, its warning when it declares a module late and its
     info when one comes back.

The third is kept *beside* the first two rather than replacing them, and that is
the interesting part: the derived state and CORE's verdict are computed from the
same evidence by different code, so a disagreement between them is a defect
worth seeing rather than a display glitch.

Two rules this module exists to hold:

  - **The timeout is imported, never copied.** `HEARTBEAT_TIMEOUT_S` and the
    three module names belong to `utilities/heartbeat_manager.py`, beside the
    interval they are the counterpart of. The debug console that was deleted
    from this repo declared its own copy, and the roadmap lists that duplication
    among the defects that died with it. One constant, one owner.

    They used to be imported from `core.py`, which pulled the Sequencer, the
    Report and the configuration into this tool's import graph - thirty modules
    for four constants, and directly against what `log_source.py` goes out of
    its way to avoid.
  - **"Now" is the last line in the file, not the wall clock.** Opening a log
    from last week must not paint every module dead. It also means a live tail
    and a replay are the same code path, because a live tail's last line is now.
"""

from dataclasses import dataclass, field
from datetime import datetime

from pypts.helper_applications.debug_monitor.trace_parser import LogLine, as_trace_event
from pypts.utilities.heartbeat_manager import HEARTBEAT_TIMEOUT_S, HMI, REPORT, SEQUENCER

#: The modules CORE watches, in the order they are worth reading.
MODULES = (HMI, SEQUENCER, REPORT)

#: States a module can be shown in.
#:
#: STOPPED and DEAD are deliberately different answers. CORE disarms the timeout
#: for a module that has reported itself stopped, so a Monitor that called a
#: clean shutdown "dead" would be contradicting the framework it is watching.
#: UNKNOWN is the third: nothing has been heard either way, which is what every
#: module looks like for the first second of a run.
ALIVE = "alive"
DEAD = "dead"
STOPPED = "stopped"
UNKNOWN = "unknown"

#: Message type -> the module it means has stopped. The name of the message is
#: all that survives in the trace, which is enough.
STOPPED_TYPES = {
    "HmiStopped": HMI,
    "SequencerStopped": SEQUENCER,
    "ReportStopped": REPORT,
}

#: CORE's own two opinions, as it writes them in core.py. Matched on the prefix
#: because the module name is appended to each.
#:
#: Both are DEBUG lines, which costs nothing: the Monitor has only ever had
#: something to show on a DEBUG run. CORE's operator-facing sentences about the
#: same two events name the module in plain language ("The test engine has
#: stopped responding") and cannot be parsed for a name - logger.md section 7.1.
TIMEOUT_PREFIX = "Heartbeat timeout for module: "
RESPONDING_PREFIX = "Module is responding again: "

#: What core_verdict() answers with, so a caller does not match on log text.
VERDICT_TIMEOUT = "timeout"
VERDICT_RESPONDING = "responding"

#: The message types that carry liveness, rather than merely proving traffic.
HEARTBEAT = "Heartbeat"
MODULE_ERROR = "ModuleError"


@dataclass(slots=True)
class ModuleState:
    """
    Everything known about one module. Mutable, unlike a parsed record: this is
    an accumulator, and the whole job is to keep folding into it.
    """

    last_heartbeat: datetime | None = None
    stopped: bool = False
    last_error: str = ""
    core_verdict: str = ""


@dataclass(slots=True)
class LivenessTracker:
    """
    The fold. Feed it every parsed line, ask it about any module.

    Feeding is cheap and unconditional - a line that says nothing about liveness
    simply moves the clock forward - so the caller does not have to pre-filter.
    """

    #: The timestamp of the most recent record seen. The tracker's only clock.
    now: datetime | None = None

    #: Whether any trace line has been seen at all. False for a whole run means
    #: the run was not started at DEBUG, which is worth saying out loud rather
    #: than showing an empty table over.
    trace_seen: bool = False

    _modules: dict[str, ModuleState] = field(default_factory=dict)

    def feed(self, line: LogLine) -> None:
        """
        Fold one parsed record in. Never raises, and ignores nothing silently
        that it could have used.
        """
        if line.timestamp is not None:
            self.now = line.timestamp

        event = as_trace_event(line)
        if event is None:
            self._note_core_opinion(line)
            return

        self.trace_seen = True

        # The sender's name is the left half of the link. Both the send and the
        # recv line of one heartbeat carry the same link, so folding either - or
        # both - gives the same answer.
        source = event.link.split("->")[0]
        if source not in MODULES:
            return

        state = self._state(source)
        if event.message_type == HEARTBEAT:
            state.last_heartbeat = line.timestamp
        elif event.message_type == MODULE_ERROR:
            state.last_error = event.payload

        # Keyed on the message rather than the link: a stopped message names the
        # module that sent it, and only ever travels one way.
        stopped_module = STOPPED_TYPES.get(event.message_type)
        if stopped_module is not None:
            self._state(stopped_module).stopped = True

    def state(self, module: str) -> str:
        """
        One of ALIVE, DEAD, STOPPED or UNKNOWN.

        Checked in that order deliberately: a module that stopped cleanly stays
        STOPPED however long ago its last heartbeat was, because the answer to
        "why is it quiet" is already known.
        """
        state = self._modules.get(module)
        if state is None:
            return UNKNOWN
        if state.stopped:
            return STOPPED
        if state.last_heartbeat is None or self.now is None:
            return UNKNOWN

        return ALIVE if self.age(module) <= HEARTBEAT_TIMEOUT_S else DEAD

    def age(self, module: str) -> float:
        """
        Seconds between this module's last heartbeat and the last line in the
        log. `inf` when it has never been heard from, so that a caller sorting
        or thresholding on this does not have to special-case None.
        """
        state = self._modules.get(module)
        if state is None or state.last_heartbeat is None or self.now is None:
            return float("inf")
        return (self.now - state.last_heartbeat).total_seconds()

    def last_heartbeat(self, module: str) -> datetime | None:
        """When this module was last heard from, or None."""
        state = self._modules.get(module)
        return None if state is None else state.last_heartbeat

    def last_error(self, module: str) -> str:
        """The repr of the last ModuleError this module reported, or ""."""
        state = self._modules.get(module)
        return "" if state is None else state.last_error

    def core_verdict(self, module: str) -> str:
        """
        What CORE last said about this module: VERDICT_TIMEOUT,
        VERDICT_RESPONDING, or "" if it has said nothing.
        """
        state = self._modules.get(module)
        return "" if state is None else state.core_verdict

    def _state(self, module: str) -> ModuleState:
        """The accumulator for one module, created on first mention."""
        return self._modules.setdefault(module, ModuleState())

    def _note_core_opinion(self, line: LogLine) -> None:
        """
        Pick CORE's two liveness statements out of the narrative.

        Matching on log text is fragile and known to be: these two strings live
        in `core.py` and nothing enforces that they stay as they are. It is worth
        it anyway, because CORE's opinion is the one thing here that cannot be
        derived - and if the text drifts, the verdict column goes blank rather
        than wrong.

        The logging sweep of September 2026 came within one edit of drifting
        them. They survive as DEBUG lines carrying nothing but the module name,
        with a comment in `core.py` saying why they are shaped that way.
        """
        if line.continuation or line.process != "Core":
            return

        if line.message.startswith(TIMEOUT_PREFIX):
            module = line.message[len(TIMEOUT_PREFIX) :].strip()
            if module in MODULES:
                self._state(module).core_verdict = VERDICT_TIMEOUT
        elif line.message.startswith(RESPONDING_PREFIX):
            module = line.message[len(RESPONDING_PREFIX) :].strip()
            if module in MODULES:
                self._state(module).core_verdict = VERDICT_RESPONDING
