# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the engine reports while a recipe runs, and the two questions it asks back.

Emitted by the Sequencer, forwarded unchanged by CORE to the HMI, so each one
belongs to two unions and is defined once here. A message says what happened,
never how to draw it.

Almost everything here is marked `NOT SENT YET`. That marker means one thing
throughout `messages/`: **the receiving end is written and works; nothing
constructs the message.** Grep for it to find the whole set. The receivers were
built first on purpose - the Sequencer, CORE, the CLI and the GUI all had to
agree on the contract before the engine existed, and `mypy` plus
`test_messages.py` keep every branch honest in the meantime.
"""

from dataclasses import dataclass
from uuid import UUID

from pypts.messages.common_messages import ResultType, StepOutcome

# --- Progress -----------------------------------------------------------------
#
# NOT SENT YET, all seven. The receiving end is complete: CORE relays them
# unchanged (`core.py: handle_sequencer_message()`) and both frontends render
# them through the presentation hooks in `hmi/hmi_client.py`. The sender is
# `Sequencer.execute_sequence()`, which is a stub - roadmap Phase 1.
# `RecipeLoaded` is the exception: its sender is `Core.load_recipe()`, equally a
# stub, which answers `StatusChanged` saying so instead.


# NOT SENT YET - receiver: hmi_client.py show_recipe_loaded()
@dataclass(frozen=True, slots=True)
class RecipeLoaded:
    """A recipe file was parsed and validated. Emitted by CORE, not the Sequencer."""

    recipe_name: str
    recipe_version: str


# NOT SENT YET - receiver: hmi_client.py show_run_started()
@dataclass(frozen=True, slots=True)
class RunStarted:
    """Execution of a recipe has begun."""

    recipe_name: str
    recipe_description: str


# NOT SENT YET - receiver: hmi_client.py show_run_finished()
@dataclass(frozen=True, slots=True)
class RunFinished:
    """Execution finished, for any reason. `outcomes` is flat, in execution order."""

    result: ResultType
    outcomes: tuple[StepOutcome, ...] = ()


# NOT SENT YET - receiver: hmi_client.py show_sequence_started()
@dataclass(frozen=True, slots=True)
class SequenceStarted:
    """One named sequence within the recipe has begun."""

    sequence_name: str


# NOT SENT YET - receiver: hmi_client.py show_sequence_finished()
@dataclass(frozen=True, slots=True)
class SequenceFinished:
    """One named sequence finished, with its aggregated result."""

    sequence_name: str
    result: ResultType


# NOT SENT YET - receiver: hmi_client.py show_step_started()
@dataclass(frozen=True, slots=True)
class StepStarted:
    """One step is about to run. `step_id` is how a frontend finds the row."""

    step_id: UUID
    step_name: str


# NOT SENT YET - receiver: hmi_client.py show_step_finished()
@dataclass(frozen=True, slots=True)
class StepFinished:
    """One step finished. Carries the whole outcome so a frontend needs no lookup."""

    outcome: StepOutcome


# --- Questions the engine asks the operator -----------------------------------
#
# Joined by a `request_id` the asker generates, which is what lets these cross a
# process boundary. The waiting side is in blocking_messages.py.
#
# Only half of this pair is asymmetric: the two *responses* are live - the
# frontends send them and the Sequencer receives them - while nothing has yet
# asked a question for them to answer. Both requests are therefore NOT SENT YET;
# their sender is an interactive step type, roadmap Phase 1 (see pypts/step).


# NOT SENT YET - receiver: hmi_client.py ask_user()
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


# NOT SENT YET - receiver: hmi_client.py ask_serial_number()
@dataclass(frozen=True, slots=True)
class SerialNumberRequest:
    """Ask the operator for the serial number of the unit under test."""

    request_id: UUID


@dataclass(frozen=True, slots=True)
class SerialNumberResponse:
    """The serial number, or None if the operator declined."""

    request_id: UUID
    serial_number: str | None
