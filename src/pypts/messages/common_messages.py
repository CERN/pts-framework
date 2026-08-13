# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Vocabulary shared by more than one link.

A type belongs here when it appears in at least two link modules - either
because every module sends it (Heartbeat, ModuleError) or because CORE forwards
it from one link to another. Forwarding matters: CORE relays a Sequencer event
to the HMI by passing the same object on, not by unpacking it into a dict and
building a different one, which is how the old code lost the ErrorSeverity enum
on every hop.

Every message in the framework is a frozen slotted dataclass of plain values.
Frozen, because a message is a fact that has already happened and nobody
downstream should edit it; slotted, because it is cheap and it turns a typo in
an attribute name into an AttributeError instead of a silent new field.
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

    Sent by @catch_and_report_errors(). Replaces ModuleErrorEvent, which each
    sender flattened into a five-key dict - downgrading `severity` from an enum
    to a string on the way - and which CORE then never rebuilt.

    Args:
        source: dotted module name of whatever failed, e.g. "pypts.report.report".
        severity: how the sender rates it.
        message: str(exception), the one-line summary.
        exception: repr(exception), kept separately so the type survives.
        traceback: the formatted traceback, or None if there was no exception.
    """

    source: str
    severity: ErrorSeverity
    message: str
    exception: str | None = None
    traceback: str | None = None


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """
    Proof that a module's event loop is still turning.

    `source` looks redundant - CORE already knows which link it drained the
    message from - but it lets one handler serve all three links instead of
    three handlers that differ only in a dict key, and it survives being
    forwarded or logged out of context.
    """

    source: str
    timestamp: float


class ResultType(IntEnum):
    """
    Outcome of a step, a sequence, or a whole run.

    Ported unchanged from old_code/recipe.py. The integer order is load-bearing:
    the old engine aggregated a list of results by taking the highest value, so
    one FAIL among PASSes makes the group FAIL. Keep the order if you add a
    member.
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

    Deliberately *not* old_code's StepResult. That object holds a reference to
    the live Step and a tree of subresults, and neither should cross the HMI
    process boundary. The Report gets the rich object in-engine; the HMI gets
    this, which is everything a results table actually draws.
    """

    step_id: UUID
    step_name: str
    result: ResultType
    error_info: str = ""
