# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the engine reports while a recipe runs, and the two questions it asks back.

Emitted by the Sequencer, forwarded unchanged by CORE to the HMI, so each one
belongs to two unions and is defined once here. A message says what happened,
never how to draw it. Nothing sends most of them yet - roadmap Phase 1.
"""

from dataclasses import dataclass
from uuid import UUID

from pypts.messages.common_messages import ResultType, StepOutcome

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
    """Execution finished, for any reason. `outcomes` is flat, in execution order."""

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
    """One step is about to run. `step_id` is how a frontend finds the row."""

    step_id: UUID
    step_name: str


@dataclass(frozen=True, slots=True)
class StepFinished:
    """One step finished. Carries the whole outcome so a frontend needs no lookup."""

    outcome: StepOutcome


# --- Questions the engine asks the operator -----------------------------------
#
# Joined by a `request_id` the asker generates, which is what lets these cross a
# process boundary. The waiting side is in blocking_messages.py.


@dataclass(frozen=True, slots=True)
class UserPromptRequest:
    """
    Show the operator a message and wait for one of `options` to be chosen.

    `image_path` is absolute: the HMI is a different process.
    """

    request_id: UUID
    message: str
    options: tuple[str, ...] = ()
    image_path: str | None = None


@dataclass(frozen=True, slots=True)
class UserPromptResponse:
    """The operator's answer. `choice` is None if they cancelled or it timed out."""

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
