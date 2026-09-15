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
    RunMetadata,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    StepFinished,
    StepStarted,
    # Defined in run_events because it rides two links: a frontend sends it
    # here and CORE relays the very same object to the Sequencer.
    StopSequence,
    UserPathRequest,
    UserPathResponse,
    UserPromptRequest,
    UserPromptResponse,
    UserTextRequest,
    UserTextResponse,
)

# --- HMI -> CORE: commands ----------------------------------------------------


@dataclass
class LoadRecipe:
    """Load and validate a recipe. CORE answers with RecipeLoaded or ModuleError."""

    recipe_path: str


@dataclass
class StartSequence:
    """Run one named sequence of the loaded recipe."""

    sequence_name: str


@dataclass
class SetConfigParameter:
    """
    Change one configuration value in config.ini. CORE answers ConfigParameterResult.

    CORE is the single runtime writer of config.ini, so a frontend asks instead
    of writing. `value` is the text as it should appear in the file ("true",
    "1280", an absolute path). The change is written straight away but takes
    effect on the next start: every process read its configuration once, at
    startup, and nothing tells a running one that a value changed.
    """

    key: str
    value: str


@dataclass
class ShutdownRequested:
    """Shut the whole application down. The launcher sends this too."""


# --- HMI -> CORE: events ------------------------------------------------------


@dataclass
class HmiStopped:
    """The HMI's event loop has ended. CORE waits for this before it may exit."""


# --- CORE -> HMI: commands ----------------------------------------------------


@dataclass
class StopHmi:
    """Close the frontend. The HMI answers with HmiStopped once its loop has ended."""


# --- CORE -> HMI: events ------------------------------------------------------


@dataclass
class StatusChanged:
    """One line of free text. Anything with structure has its own message."""

    text: str


@dataclass
class ModuleErrorReported:
    """An error CORE decided the operator should see. Not every ModuleError is."""

    error: ModuleError


@dataclass
class ReportReady:
    """
    The report of the run that just finished is on disk.

    Sent by CORE when the Report answers ReportGenerated. Both paths are
    absolute strings: `report_path` is the HTML file, `report_dir` the run
    folder holding it and the CSV - what a frontend's "open report folder"
    control opens.
    """

    report_path: str
    report_dir: str


@dataclass
class ConfigParameterResult:
    """
    CORE's answer to one SetConfigParameter.

    `accepted` True: the value is in config.ini now and applies from the next
    start. False: the file was not touched, and `reason` says why in words meant
    for whoever made the change - a value of the wrong type, a key that does not
    exist, a read-only section, or a settings file that was discarded at startup.
    `key` and `value` repeat the request, so a frontend waiting on several
    answers can tell them apart.
    """

    key: str
    value: str
    accepted: bool
    reason: str = ""


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
    | UserTextResponse
    | UserPathResponse
    | Heartbeat
    | ModuleError
)

CoreToHmi = (
    StopHmi
    | StatusChanged
    | ModuleErrorReported
    | ReportReady
    | ConfigParameterResult
    | RecipeLoaded
    | RunStarted
    | RunFinished
    | RunMetadata
    | SequenceStarted
    | SequenceFinished
    | StepStarted
    | StepFinished
    | UserPromptRequest
    | UserTextRequest
    | UserPathRequest
    # The one heartbeat that travels away from CORE. The HMI is the only module
    # in a process of its own, so it is the only one that can still be running
    # with nothing on the other end of its link - CORE killed outright, or its
    # event loop wedged while the process stays up. The Sequencer and the Report
    # are threads of CORE's process and die with it, so neither is sent one.
    | Heartbeat
)
