# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Who is alive, folded out of the run log.

None of CORE's liveness state ever leaves CORE. `module_running`,
`last_heartbeat` and `heartbeat_lost` are dicts in `core.py`, and no message on
the `core->hmi` link carries any of them. A frontend cannot ask.

What CORE *does* about silence changed in roadmap 1.38 - past the fatal
threshold it ends the run - but that did not change the sentence above. The
state is still private; only the consequence is new, and it reaches this module
the same way the timeout always did, as a line in the log.

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

Three rules this module exists to hold:

  - **Nothing is registered. Modules are discovered.** There is no list of the
    modules this tool knows about, and adding one to the framework requires no
    edit here. A name becomes a module the first time it is seen *sending* on a
    link, or the first time CORE names it in a liveness line of its own. That is
    the whole rule, and it is what lets a troubleshooting tool be useful about a
    part of the system that did not exist when the tool was written.

    Sending, specifically, because only a sender can prove it is alive. A name
    seen solely as a *receiver* - `logger`, which never answers, and `any`, the
    wildcard in `any->logger` that is not a module at all - would be a row that
    could never say anything but "unknown".

  - **The timeout is imported, never copied.** `HEARTBEAT_TIMEOUT_S` belongs to
    `utilities/heartbeat_manager.py`, beside the interval it is the counterpart
    of. The debug console that was deleted from this repo declared its own copy,
    and the roadmap lists that duplication among the defects that died with it.
    One constant, one owner.

    It used to be imported from `core.py`, which pulled the Sequencer, the
    Report and the configuration into this tool's import graph - thirty modules
    for a handful of constants, and directly against what `log_source.py` goes
    out of its way to avoid.
  - **"Now" is the last line in the file, not the wall clock.** Opening a log
    from last week must not paint every module dead. It also means a live tail
    and a replay are the same code path, because a live tail's last line is now.
"""

from dataclasses import dataclass, field
from datetime import datetime

from pypts.helper_applications.debug_monitor.trace_parser import LogLine, as_trace_event
from pypts.utilities.heartbeat_manager import HEARTBEAT_TIMEOUT_S

#: What separates the two halves of a link name. A trace whose link does not
#: contain it names no sender at all - an anonymous QueueWrapper traces as `?` -
#: and so contributes no module, however much it contributes to the trace table.
LINK_SEPARATOR = "->"

#: Names that appear where a module name would but are not modules. `any` is the
#: wildcard half of `any->logger` - every process logs, so the link is named for
#: the fact that its sender is not one particular module.
#:
#: This is the only name refused *by name*, and it is refused for being a
#: wildcard rather than for being unfamiliar. Anything else that sends gets a
#: row. Everything else is refused structurally, by not being a sender at all.
NOT_A_MODULE = frozenset({"any"})

#: The suffix a module's own goodbye ends in: HmiStopped, SequencerStopped,
#: ReportStopped, and whatever a module added tomorrow calls its own.
STOPPED_SUFFIX = "Stopped"

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

#: CORE's own three opinions, as it writes them in core.py. Matched on the
#: prefix because the module name is appended to each, and to nothing else -
#: which is why the fatal line's measurements are on a separate record.
#:
#: All three are DEBUG lines, which costs nothing: the Monitor has only ever had
#: something to show on a DEBUG run. CORE's operator-facing sentences about the
#: same events name the module in plain language ("The test engine has
#: stopped responding") and cannot be parsed for a name - logging_rules.md section 7.1.
#:
#: FATAL_PREFIX must not be a prefix of TIMEOUT_PREFIX or the reverse, since
#: these are matched with startswith in the order written below. "timeout" and
#: "fatal" share only "Heartbeat ", so they cannot collide.
TIMEOUT_PREFIX = "Heartbeat timeout for module: "
FATAL_PREFIX = "Heartbeat fatal for module: "
RESPONDING_PREFIX = "Module is responding again: "

#: What core_verdict() answers with, so a caller does not match on log text.
#:
#: TIMEOUT and FATAL are the same silence at two thresholds and are deliberately
#: distinct answers: a timeout is CORE reporting, and the run went on; a fatal is
#: CORE acting, and the run did not. A Monitor that showed one for the other
#: would hide the single most important thing that happened in the log.
VERDICT_TIMEOUT = "timeout"
VERDICT_FATAL = "fatal"
VERDICT_RESPONDING = "responding"

#: Prefix -> verdict, tried in order. A table rather than a chain of `elif`s so
#: that adding one of CORE's opinions is one line here and nothing else.
VERDICT_PREFIXES = (
    (TIMEOUT_PREFIX, VERDICT_TIMEOUT),
    (FATAL_PREFIX, VERDICT_FATAL),
    (RESPONDING_PREFIX, VERDICT_RESPONDING),
)

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
        #
        # This is where a module is *discovered*. Anything that sends gets a row,
        # whether or not this tool has ever heard of it: a link named `core->hmi`
        # is CORE saying it exists and its loop is turning, and that is exactly
        # what somebody troubleshooting needs to see, including for a module
        # added to the framework long after this file was written.
        #
        # A link with no separator in it names nobody: `?` is what a QueueWrapper
        # built without a link name traces as, and while that is a defect worth
        # seeing - it has a row in the trace table and a checkbox of its own - it
        # is not a module and must not become one.
        if LINK_SEPARATOR not in event.link:
            return

        source = event.link.split(LINK_SEPARATOR)[0]
        if source in NOT_A_MODULE:
            return

        state = self._state(source)
        if event.message_type == HEARTBEAT:
            state.last_heartbeat = line.timestamp
        elif event.message_type == MODULE_ERROR:
            state.last_error = event.payload

        # Keyed on the message rather than the link: a module's goodbye names
        # itself, and only ever travels one way.
        stopped = self.stopped_module(event.message_type)
        if stopped is not None:
            self._state(stopped).stopped = True

    def stopped_module(self, message_type: str) -> str | None:
        """
        The module a `<Name>Stopped` message says has stopped, or None.

        A convention rather than a table, so a module added tomorrow needs no
        edit here: `HmiStopped` is the HMI saying goodbye, and `WhateverStopped`
        would be Whatever saying it.

        **Guarded by what the log has already shown.** The name is only accepted
        if something by that name has been seen sending, which is what stops the
        convention over-reaching: a run-level event like `RunStopped` or
        `SequenceStopped` matches the suffix perfectly well and would otherwise
        conjure a module called "run" out of an event that has nothing to do with
        liveness. A real module has always spoken before it says goodbye.
        """
        if not message_type.endswith(STOPPED_SUFFIX):
            return None

        name = message_type[: -len(STOPPED_SUFFIX)].lower()
        return name if name in self._modules else None

    def modules(self) -> tuple[str, ...]:
        """
        Every module discovered so far, in the order they were first seen.

        First-seen rather than sorted: the order the run introduced them is
        roughly its startup order, which is itself worth reading. Insertion order
        comes free - `_modules` is a dict, and dicts have kept it since 3.7.
        """
        return tuple(self._modules)

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
        What CORE last said about this module: VERDICT_TIMEOUT, VERDICT_FATAL,
        VERDICT_RESPONDING, or "" if it has said nothing.

        Last, not worst. A module that timed out, was declared fatal and then -
        impossibly - answered again would read "responding", because that is
        what CORE last believed. The Monitor reports CORE's opinion; it does not
        hold one of its own.
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

        for prefix, verdict in VERDICT_PREFIXES:
            if not line.message.startswith(prefix):
                continue
            module = line.message[len(prefix) :].strip()
            # CORE naming a module is as good as that module speaking for
            # itself: these lines are written only about modules CORE watches.
            # So this discovers too - a module that died before it ever managed
            # a heartbeat still gets a row, which is the run where you most want
            # one. The name is a single word by construction, and the check keeps
            # a drifted format string from inventing a module out of a sentence.
            if module and " " not in module and module not in NOT_A_MODULE:
                self._state(module).core_verdict = verdict
            return
