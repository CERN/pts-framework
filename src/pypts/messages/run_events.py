# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the engine reports while a recipe runs, and the two questions it asks back.

These originate in the Sequencer, travel to CORE, and CORE forwards them
unchanged to the HMI - so each one appears in both the sequencer link's union
and the HMI link's union, and is defined once here.

The set is a one-for-one port of the nine Qt signals in old_code/event_proxy.py,
which is the closest thing the project has to a requirements document for what a
frontend needs in order to draw a run:

    pre_run_recipe     -> RunStarted
    post_load_recipe   -> RecipeLoaded
    pre_run_sequence   -> SequenceStarted
    pre_run_step       -> StepStarted
    post_run_step      -> StepFinished
    post_run_sequence  -> SequenceFinished
    post_run_recipe    -> RunFinished
    user_interact      -> UserPromptRequest   / UserPromptResponse
    get_serial_number  -> SerialNumberRequest / SerialNumberResponse

Nothing sends most of these yet - the execution engine is still to be ported
(roadmap Phase 1). They are declared now because the CLI, the GUI and the Report
all have to agree on them, and agreeing before the call sites exist is much
cheaper than agreeing after.

The old code carried these as tuples of positional data behind a string event
name, transformed into dicts by a proxy class. The colour lookup that proxy did
(`get_step_result_colors`) is presentation and stays in the GUI: a message says
what happened, never how to draw it.
"""

from dataclasses import dataclass
from uuid import UUID

from pypts.messages.common import ResultType, StepOutcome

# --- Progress -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecipeLoaded:
    """A recipe file was parsed and validated. Emitted by CORE, not the Sequencer."""

    recipe_name: str
    recipe_version: str


@dataclass(frozen=True, slots=True)
class RunStarted:
    """Execution of a recipe has begun."""

    recipe_name: str
    recipe_description: str


@dataclass(frozen=True, slots=True)
class RunFinished:
    """
    Execution finished, for any reason including being stopped.

    `outcomes` is flat and in execution order. The old engine handed the GUI a
    nested tree of StepResults; nesting is a Report concern, and the HMI's
    results table only ever walked it flat.
    """

    result: ResultType
    outcomes: tuple[StepOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class SequenceStarted:
    """One named sequence within the recipe has begun."""

    sequence_name: str


@dataclass(frozen=True, slots=True)
class SequenceFinished:
    """One named sequence finished, with its aggregated result."""

    sequence_name: str
    result: ResultType


@dataclass(frozen=True, slots=True)
class StepStarted:
    """
    One step is about to run.

    `step_id` is the step's own UUID from the recipe, which is how a frontend
    finds the row to update. It is stable across a run; the outcome's id in
    StepFinished is the same one.
    """

    step_id: UUID
    step_name: str


@dataclass(frozen=True, slots=True)
class StepFinished:
    """One step finished. Carries the whole outcome so a frontend needs no lookup."""

    outcome: StepOutcome


# --- Questions the engine asks the operator -----------------------------------
#
# A request and its response are joined by `request_id`, which the *asking* side
# generates with uuid4(). That id is the whole reason these can cross a process
# boundary at all: the old engine put a live queue.SimpleQueue inside the event
# and had the GUI answer straight into it, which only ever worked because both
# ends were threads in one process.
#
# The waiting side is in requests.py.


@dataclass(frozen=True, slots=True)
class UserPromptRequest:
    """
    Show the operator a message and wait for one of `options` to be chosen.

    `image_path` is resolved to an absolute path by the sender, because the HMI
    may be a different process with a different working directory.
    """

    request_id: UUID
    message: str
    options: tuple[str, ...] = ()
    image_path: str | None = None


@dataclass(frozen=True, slots=True)
class UserPromptResponse:
    """
    The operator's answer. `choice` is None if they cancelled or the wait timed out.

    TODO (roadmap Phase 1): some old_code interaction steps read a *second*
    value off the same response queue after the first answer - a file path, a
    measured value, or a (port, baudrate, IDN) triple. That follow-up is not
    modelled here; when those steps are ported each follow-up needs to become
    its own request rather than an untyped extra read.
    """

    request_id: UUID
    choice: str | None


@dataclass(frozen=True, slots=True)
class SerialNumberRequest:
    """Ask the operator for the serial number of the unit under test."""

    request_id: UUID


@dataclass(frozen=True, slots=True)
class SerialNumberResponse:
    """The serial number, or None if the operator declined."""

    request_id: UUID
    serial_number: str | None
