# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The console's status glyphs, in one place.

A trace scrolling at a few hundred rows a second is read by shape, not by
reading. Three glyphs carry almost all of it - is this fine, should I look, has
something broken - and defining them here rather than inline keeps that
vocabulary consistent across the four tabs. A reader who learns that ❌ means
"broken" in the Run tab must not find it meaning something else in Modules.

Emoji only, never colour alone: the tables are also colour-coded, and a glyph is
what survives a colour-blind reader, a screenshot pasted into a ticket, and the
grey-on-grey a disabled row gets.

Deliberately not used by the CLI. `print()` on a Windows console in a non-UTF-8
code page raises UnicodeEncodeError, and a frontend that crashes while reporting
a failure is worse than one with plain text. Qt has no such problem.
"""

from pypts.messages.common import ErrorSeverity, ResultType

# --- The three that matter -----------------------------------------------------

OK = "✅"
WARNING = "⚠️"
ERROR = "❌"

# --- States that are neither good nor bad --------------------------------------

PENDING = "⏳"  # expected, not seen yet
STOPPED = "⏹️"  # ended on purpose
RUNNING = "▶️"  # in progress
INJECTED = "💉"  # simulated by this console rather than produced by a module

# --- Per outcome ---------------------------------------------------------------
#
# Keyed on ResultType, whose integer order is load-bearing elsewhere: the worst
# outcome wins when results are aggregated. The glyphs follow that severity.

RESULT_ICONS = {
    ResultType.SKIP: "⏭️",
    ResultType.DONE: "✔️",
    ResultType.PASS: OK,
    ResultType.FAIL: ERROR,
    ResultType.ERROR: "💥",  # distinct from FAIL: the step broke rather than failed
    ResultType.STOP: STOPPED,
}

SEVERITY_ICONS = {
    ErrorSeverity.WARNING: WARNING,
    ErrorSeverity.ERROR: ERROR,
    ErrorSeverity.CRITICAL: "🛑",
}

#: Message types worth marking in the trace. Everything else stays bare - if
#: every row had a glyph, none of them would draw the eye, which is the only
#: thing a glyph is for.
MESSAGE_ICONS = {
    "ModuleError": ERROR,
    "ModuleErrorReported": ERROR,
    "UserPromptRequest": "❓",
    "SerialNumberRequest": "❓",
    "Heartbeat": "💓",
    "RunStarted": RUNNING,
    "SequenceStarted": RUNNING,
    "StepStarted": RUNNING,
    "StopHmi": STOPPED,
    "StopSequencer": STOPPED,
    "StopReport": STOPPED,
    "StopSequence": STOPPED,
    "HmiStopped": STOPPED,
    "SequencerStopped": STOPPED,
    "ReportStopped": STOPPED,
    "ShutdownRequested": STOPPED,
}


def label(icon: str, text: str) -> str:
    """One space between glyph and text, so columns line up under each other."""
    return f"{icon} {text}"
