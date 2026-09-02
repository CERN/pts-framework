# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the engine reports while a recipe runs, and the two questions it asks back.

Emitted by the Sequencer, forwarded unchanged by CORE to the HMI, so each one
belongs to two unions and is defined once here. A message says what happened,
never how to draw it.

`NOT SENT YET` means one thing throughout `messages/`: **the receiving end is
written and works; nothing constructs the message.** Grep for it to find the
whole set. The receivers were built first on purpose - the Sequencer, CORE, the
CLI and the GUI all had to agree on the contract before the engine existed, and
`mypy` plus `test_messages.py` keep every branch honest in the meantime. The
seven progress events below carried the marker until the first slice of the
engine port landed, `UserPromptRequest` until the UserInteraction step type
landed and `UserTextRequest` until the UserWrite one did. Nothing in this module
carries the marker any more.
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
    """
    Execution of a recipe has begun.

    Carries everything about the run that is knowable before the first step,
    because the Report opens report.csv on this message and every one of
    these becomes a column. `metadata_names` is the recipe's
    `report_metadata` header - the *names* are known now even though the
    values arrive later, as RunMetadata, which is what lets the header row
    be written once and stay correct.
    """

    recipe_name: str
    recipe_description: str
    recipe_version: str = ""
    pypts_version: str = ""
    metadata_names: tuple[str, ...] = ()


# Sender: Sequencer.execute_sequence(). Receiver: hmi_client.py show_run_finished()
@dataclass(frozen=True, slots=True)
class RunFinished:
    """Execution finished, for any reason. `outcomes` is flat, in execution order."""

    result: ResultType
    outcomes: tuple[StepOutcome, ...] = ()


# Sender: Sequencer, from the emit seam it wraps. Receivers: report.py
# record_metadata() and hmi_client.py show_run_metadata()
@dataclass(frozen=True, slots=True)
class RunMetadata:
    """
    The current value of one or more of the run's metadata globals.

    The Report cannot see the Runtime - it is a thread of the Core process
    fed by events, while the globals live on the sequence thread - so the
    Sequencer sends them. Emitted whenever a global the recipe named in
    `report_metadata` appears or changes, so a run that sets its serial
    number in step 1 has it from step 1 on.

    Pairs rather than a dict, so the message stays a frozen value that
    compares and pickles like every other one.
    """

    values: tuple[tuple[str, str], ...] = ()


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
# Both pairs are live end to end: UserInteractionStep and UserWriteStep ask
# through Runtime.ask, and the frontends answer.
#
# There is deliberately no message for a *particular* question. An earlier
# SerialNumberRequest hard-coded one - the engine went and fetched the serial
# number of the unit under test whether or not the recipe wanted one. Asking is
# the recipe's job: a UserWrite step named `get_serial_number` puts the answer in
# a global, and the framework supplies the prompt, not the policy. See
# resources/roadmap/best_practices.md.


# Sent by: step/user_interaction_step.py, via Runtime.ask -> Sequencer.ask_operator()
# Receiver: hmi_client.py ask_user()
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


# Sent by: step/user_write_step.py, via Runtime.ask -> Sequencer.ask_operator()
# Receiver: hmi_client.py ask_user_text()
@dataclass(frozen=True, slots=True)
class UserTextRequest:
    """
    Show the operator a message and wait for a line of text to be typed.

    The free-text counterpart of UserPromptRequest, and deliberately as
    unopinionated: the recipe decides what is being asked for. `image_path`
    is absolute, for the same reason - the HMI is a different process.
    """

    request_id: UUID
    message: str
    image_path: str | None = None


@dataclass(frozen=True, slots=True)
class UserTextResponse:
    """What the operator typed. `text` is None if they cancelled or it timed out."""

    request_id: UUID
    text: str | None
