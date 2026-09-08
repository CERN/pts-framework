# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Vocabulary shared by more than one link.

A type belongs here when at least two link modules use it - because every
module sends it, or because CORE forwards it from one link to another.

The file has two halves, and the difference matters more than it looks.
A **message** is a member of a link union: something `QueueWrapper.send()`
takes, that a handler answers with a `case`. A **payload** is only ever a
field of a message; it reaches no union and no handler. Both are plain
dataclasses, so nothing in the syntax tells them apart - the banners below
and the first line of each docstring do, and
`test_messages.py: test_no_payload_is_on_a_union` keeps it true.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from uuid import UUID

# --- Payloads: carried inside a message, never sent alone ---------------------


class ErrorSeverity(Enum):
    """
    Payload of ModuleError.severity. Never sent alone.

    How bad a ModuleError is. CORE decides what to do about it.
    """

    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class ResultType(IntEnum):
    """
    Payload of RunFinished.result, SequenceFinished.result and
    StepOutcome.result. Never sent alone.

    Outcome of a step, a sequence, or a whole run.

    The integer order is load-bearing: a group aggregates to its highest
    member, so one FAIL among PASSes makes the group FAIL. Keep the order if
    you add a member.
    """

    SKIP = 0
    DONE = 1
    PASS = 2
    FAIL = 3
    ERROR = 4
    STOP = 5

    def __str__(self) -> str:
        return self.name


@dataclass
class StepOutcome:
    """
    Payload of StepFinished.outcome, StepExecuted.outcome and
    RunFinished.outcomes. Never sent alone.

    The pickle-safe summary of one executed step.

    Not a StepResult - that holds the live Step and must not cross the HMI
    process boundary. The Report gets the rich object in-engine.
    """

    step_id: UUID
    step_name: str
    result: ResultType
    error_info: str = ""


# --- Messages: on a link union, sent on their own -----------------------------


@dataclass
class ModuleError:
    """
    A failure a module wants CORE to know about.

    Sent by the decorators in utilities/error_handling.py, and by
    report_error()/report_problem(). Every field is a string because this
    crosses the pickled HMI link.

    Args:
        source: dotted module name of whatever failed, e.g. "pypts.report.report".
        severity: how the sender rates it.
        message: str(exception), the one-line summary.
        exception: repr(exception), kept separately so the type survives.
        traceback: the formatted traceback, or None if there was no exception.
        operation: qualified name of the method that failed, e.g.
                   "Sequencer.poll_core". Empty when the sender did not say.
        error_type: type(exception).__name__, or "" if there was no exception.
    """

    source: str
    severity: ErrorSeverity
    message: str
    exception: str | None = None
    traceback: str | None = None
    operation: str = ""
    error_type: str = ""


@dataclass
class Heartbeat:
    """Still alive. `source` travels on it so one CORE handler serves all links."""

    source: str
    timestamp: float
