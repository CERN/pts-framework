# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Vocabulary shared by more than one link.

A type belongs here when at least two link modules use it - because every
module sends it, or because CORE forwards it from one link to another.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from uuid import UUID


class ErrorSeverity(Enum):
    """How bad a ModuleError is. CORE decides what to do about it."""

    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """Still alive. `source` travels on it so one CORE handler serves all links."""

    source: str
    timestamp: float


class ResultType(IntEnum):
    """
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


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """
    The pickle-safe summary of one executed step.

    Not a StepResult - that holds the live Step and must not cross the HMI
    process boundary. The Report gets the rich object in-engine.
    """

    step_id: UUID
    step_name: str
    result: ResultType
    error_info: str = ""
