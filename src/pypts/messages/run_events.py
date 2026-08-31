# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the engine reports while a recipe runs, and the two questions it asks back.

Emitted by the Sequencer, forwarded unchanged by CORE to the HMI, so each one
belongs to two unions and is defined once here. A message says what happened,
never how to draw it.

The two prompt *requests* are marked `NOT SENT YET`. That marker means one
thing throughout `messages/`: **the receiving end is written and works;
nothing constructs the message.** Grep for it to find the whole set. The
receivers were built first on purpose - the Sequencer, CORE, the CLI and the
GUI all had to agree on the contract before the engine existed, and `mypy`
plus `test_messages.py` keep every branch honest in the meantime. The seven
progress events below carried the marker until the first slice of the engine
port landed; now the Sequencer and the step layer send them on every run.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pypts.messages.common_messages import ResultType, StepOutcome

# --- Progress -----------------------------------------------------------------
#
# All seven are live. CORE relays them unchanged
# (`core.py: handle_sequencer_message()`) and both frontends render them
# through the presentation hooks in `hmi/hmi_client.py`. The senders:
# `Sequencer.execute_sequence()` for the run-level pair, the step layer
# (through `Runtime.emit`) for the sequence and step events, and
# `Core.load_recipe()` for `RecipeLoaded`.


@dataclass(frozen=True, slots=True)
class StepSummary:
    """
    One step, as a frontend needs to draw its table row before the run.

    `step_id` is the same UUID the step's StepStarted/StepFinished will carry,
    which is what lets a frontend find the row again. A summary, not the Step:
    the live object must never cross the HMI boundary.
    """

    step_id: UUID
    step_name: str
    description: str


@dataclass(frozen=True, slots=True)
class SequenceSummary:
    """
    One sequence's rows, in the order they will run.

    Includes the teardown steps at the end: they run through the same
    lifecycle and emit the same events, so they need rows too.
    """

    sequence_name: str
    steps: tuple[StepSummary, ...]


# Sender: Core.load_recipe(). Receiver: hmi_client.py show_recipe_loaded()
@dataclass(frozen=True, slots=True)
class RecipeLoaded:
    """
    A recipe file was parsed and validated. Emitted by CORE, not the Sequencer.

    Carries the whole pickle-safe summary of the recipe - every sequence and
    every step row - because the HMI is another process and this message is
    all it will ever know about the file: it is what fills the sequence
    chooser and pre-fills the step table before a run. `main_sequence` is the
    default a frontend offers; any sequence may be requested.
    """

    recipe_name: str
    recipe_version: str
    main_sequence: str
    sequences: tuple[SequenceSummary, ...]


# Sender: Sequencer.execute_sequence(). Receiver: hmi_client.py show_run_started()
@dataclass(frozen=True, slots=True)
class RunStarted:
    """Execution of a recipe has begun."""

    recipe_name: str
    recipe_description: str


# Sender: Sequencer.execute_sequence(). Receiver: hmi_client.py show_run_finished()
@dataclass(frozen=True, slots=True)
class RunFinished:
    """Execution finished, for any reason. `outcomes` is flat, in execution order."""

    result: ResultType
    outcomes: tuple[StepOutcome, ...] = ()


# Sender: step.run_sequence(). Receiver: hmi_client.py show_sequence_started()
@dataclass(frozen=True, slots=True)
class SequenceStarted:
    """One named sequence within the recipe has begun."""

    sequence_name: str


# Sender: step.run_sequence(). Receiver: hmi_client.py show_sequence_finished()
@dataclass(frozen=True, slots=True)
class SequenceFinished:
    """One named sequence finished, with its aggregated result."""

    sequence_name: str
    result: ResultType


# Sender: Step.run(). Receiver: hmi_client.py show_step_started()
@dataclass(frozen=True, slots=True)
class StepStarted:
    """One step is about to run. `step_id` is how a frontend finds the row."""

    step_id: UUID
    step_name: str


# Sender: Step.run(). Receiver: hmi_client.py show_step_finished()
@dataclass(frozen=True, slots=True)
class StepFinished:
    """One step finished. Carries the whole outcome so a frontend needs no lookup."""

    outcome: StepOutcome


# Sender: Step.run(). Receiver: report.py record_step()
@dataclass(frozen=True, slots=True)
class StepExecuted:
    """
    One step finished, with everything the Report writes about it.

    The rich sibling of StepFinished, and **engine-internal**: it rides
    Sequencer->CORE and CORE->Report only, two links that never leave the Core
    process, so `inputs` and `outputs` may hold whatever the step touched. It
    must never join the HMI unions - the flat StepOutcome is the projection
    that crosses the process boundary.

    `started_at` is epoch seconds (time.time()); `duration_s` is measured with
    a monotonic clock around the whole lifecycle - resolve inputs, _step(),
    judge outputs.
    """

    outcome: StepOutcome
    step_type: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    started_at: float
    duration_s: float


# --- Commands the operator gives about a run ----------------------------------


@dataclass(frozen=True, slots=True)
class StopSequence:
    """
    Abort the running sequence but keep the module alive.

    Rides two links, and CORE relays the same object: a frontend sends it
    (HmiToCore) and CORE forwards it to the Sequencer (CoreToSequencer), which
    checks the flag between steps - so the abort lands at the next step
    boundary, never in the middle of one. The confirmation a frontend gets is
    the run's own RunFinished with result STOP.
    """


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
