# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The HMI <-> CORE link. The only process boundary in the framework.

Everything below is pickled in GUI mode, so it must stay a frozen dataclass of
plain values - no live queues, no Qt objects, no device handles. Nothing here
enforces that by itself, so unit_tests/unit_tests/test_message_pickling.py
round-trips every member of both unions and fails if one of them stops being
pickle-safe.

Note the split the old enums did not make. A *command* is an instruction to one
recipient that may be refused; an *event* is a fact that has already happened.
The old HMIToCoreCommand had STOP ("I have stopped", a fact) sitting next to
EXIT ("shut the application down", an instruction) with nothing to tell them
apart, and both were spelled as if they were commands.
"""

from dataclasses import dataclass

from pypts.messages.common import Heartbeat, ModuleError
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


@dataclass(frozen=True, slots=True)
class SetConfigParameter:
    """
    Change one configuration value.

    Declared, not implemented: nothing sends this yet, and CORE's handler only
    says so. It exists because the write policy has to be decided before anyone
    writes rather than after - CORE is the single writer of config.ini, so a
    frontend that wants a setting changed asks for it here instead of opening
    the file itself.

    `value` is text because that is what an INI file holds; CORE validates it
    against the schema, which is where the key's real type lives.

    Two things are still open, and are why this is a placeholder: whether CORE
    answers with a confirmation or an error, and how a process already running
    learns that a value it read at startup has changed.
    """

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class ShutdownRequested:
    """
    Shut the whole application down. Was HMIToCoreCommand.EXIT.

    The launcher sends this too, on the same link, when the UI it was waiting
    on has gone: it is the supervisor of last resort, and CORE having exactly
    one shutdown path is worth more than the launcher having its own link.
    """


# --- HMI -> CORE: events ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HmiStopped:
    """
    The HMI's event loop has ended. Was HMIToCoreCommand.STOP.

    CORE waits for this from every module before it exits, which is why the CLI
    not sending it used to leave CORE unable to shut down on its own.
    """


# --- CORE -> HMI: commands ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class StopHmi:
    """Close the frontend. The HMI answers with HmiStopped once its loop has ended."""


# --- CORE -> HMI: events ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StatusChanged:
    """
    One line of human-readable state for the runtime log.

    This used to be the *only* thing CORE could tell a frontend, which is why
    everything the operator needed to see had to be squeezed into a string. It
    survives for genuine free text; anything with structure now has its own
    message in run_events.py.
    """

    text: str


@dataclass(frozen=True, slots=True)
class ModuleErrorReported:
    """
    A module failed and the operator should see it.

    CORE decides which errors are worth surfacing; it does not forward every
    ModuleError it receives. Before this existed, an error reaching CORE could
    only ever reach the log file.
    """

    error: ModuleError


# --- The link ------------------------------------------------------------------
#
# These two unions are the contract. `unhandled()` in a recipient's match is
# checked against them, and the protocol tests enumerate them with
# typing.get_args(), so a message added below is automatically covered by both.

HmiToCore = (
    LoadRecipe
    | StartSequence
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
