# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The HMI <-> CORE link. The only process boundary in the framework.

Everything below is pickled, so it must stay a frozen dataclass of plain values
- no live queues, no Qt objects, no device handles. test_messages.py round-trips
every member of both unions and fails if one stops being pickle-safe.
"""

from dataclasses import dataclass

from pypts.messages.common_messages import Heartbeat, ModuleError
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    SerialNumberRequest,
    SerialNumberResponse,
    StepFinished,
    StepStarted,
    # Defined in run_events because it rides two links: a frontend sends it
    # here and CORE relays the very same object to the Sequencer.
    StopSequence,
    UserPromptRequest,
    UserPromptResponse,
)

# --- HMI -> CORE: commands ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadRecipe:
    """Load and validate a recipe. CORE answers with RecipeLoaded or ModuleError."""

    recipe_path: str


@dataclass(frozen=True, slots=True)
class StartSequence:
    """Run one named sequence of the loaded recipe."""

    sequence_name: str


# NOT SENT YET - and the only message in the system that is dead at *both* ends.
# No frontend constructs it, and CORE's branch for it
# (`core.py: handle_hmi_message()`) deliberately logs that it is ignoring the
# request rather than carrying it out. That refusal is the honest behaviour
# until two questions are answered: whether CORE replies with a confirmation or
# an error, and how a process that read a value at startup learns it changed.
# Until then a configuration change takes effect on the next start.
@dataclass(frozen=True, slots=True)
class SetConfigParameter:
    """
    Change one configuration value. Declared, not implemented.

    CORE is the single writer of config.ini, so a frontend asks instead of writing.
    """

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class ShutdownRequested:
    """Shut the whole application down. The launcher sends this too."""


# --- HMI -> CORE: events ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HmiStopped:
    """The HMI's event loop has ended. CORE waits for this before it may exit."""


# --- CORE -> HMI: commands ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class StopHmi:
    """Close the frontend. The HMI answers with HmiStopped once its loop has ended."""


# --- CORE -> HMI: events ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusChanged:
    """One line of free text. Anything with structure has its own message."""

    text: str


@dataclass(frozen=True, slots=True)
class ModuleErrorReported:
    """An error CORE decided the operator should see. Not every ModuleError is."""

    error: ModuleError


# --- The link ------------------------------------------------------------------
#
# The two unions are the contract: `unhandled()` is checked against them, and the
# protocol tests enumerate them with typing.get_args().

HmiToCore = (
    LoadRecipe
    | StartSequence
    | StopSequence
    | SetConfigParameter
    | ShutdownRequested
    | HmiStopped
    | UserPromptResponse
    | SerialNumberResponse
    | Heartbeat
    | ModuleError
)

CoreToHmi = (
    StopHmi
    | StatusChanged
    | ModuleErrorReported
    | RecipeLoaded
    | RunStarted
    | RunFinished
    | SequenceStarted
    | SequenceFinished
    | StepStarted
    | StepFinished
    | UserPromptRequest
    | SerialNumberRequest
)
