# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The HMI <-> CORE link, across a process boundary (the other message link that
crosses one is the Logger's heartbeat, logger_core_communication.py).

Everything below is pickled, so it must stay a plain dataclass of plain values
- no live queues, no Qt objects, no device handles. test_messages.py round-trips
every member of both unions and fails if one stops being pickle-safe.
"""

from dataclasses import dataclass
from uuid import UUID

from pypts.messages.common_messages import Heartbeat, ModuleError
from pypts.messages.run_events import (
    # PauseSequence, ResumeSequence and StopSequence are defined in run_events
    # because they ride two links: a frontend sends them here and CORE relays
    # the very same object to the Sequencer.
    PauseSequence,
    RecipeLoaded,
    ResumeSequence,
    RunFinished,
    RunMetadata,
    RunPaused,
    RunResumed,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    StepFinished,
    StepStarted,
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
class UnloadRecipe:
    """
    Forget the loaded recipe. CORE answers with RecipeUnloaded.

    Only offered while no run is in progress - CORE does not check, the
    frontend not offering it is the rule, as for LoadRecipe (roadmap §1.42).
    Asking with nothing loaded is harmless and answered the same way.
    """


@dataclass
class StartSequence:
    """
    Run one named sequence of the loaded recipe.

    The two optional fields are the GUI's engineering mode; every other sender
    leaves the defaults. `excluded_step_ids` are steps to record SKIP instead
    of running. `write_report` False runs without a report and without a run
    folder - the run is logged in the session log.
    """

    sequence_name: str
    excluded_step_ids: tuple[UUID, ...] = ()
    write_report: bool = True


@dataclass
class SetConfigParameter:
    """
    Change one configuration value in config.ini. CORE answers ConfigParameterResult.

    CORE is the single runtime writer of config.ini, so a frontend asks instead
    of writing. `value` is the text as it should appear in the file ("true",
    "1280", an absolute path). The change is written straight away and the next
    read of the file sees it; a value read once at startup (the log level, the
    window) takes effect on the next start, since nothing tells a running module
    that a value changed.
    """

    key: str
    value: str


@dataclass
class RestoreDefaultConfig:
    """
    Rewrite config.ini with the template defaults. CORE answers DefaultConfigRestored.

    A frontend asks, as for SetConfigParameter, because CORE is the single
    runtime writer of config.ini. Every user change in the file is lost; the
    defaults take effect on the next start, so the GUI restarts pypts once CORE
    confirms. bench.ini is never touched.
    """


@dataclass
class ShutdownRequested:
    """
    Shut the whole application down. The launcher sends this too.

    `immediate` picks the close. False, the orderly close: CORE stops the
    Sequencer, then the Report, then the HMI, each after the one before has
    stopped, and a running test finishes first. True, the crash close: every
    module is told to stop at once and nothing is waited for - the CLI's Ctrl+C,
    and the launcher once the frontend has ended.
    """

    immediate: bool = False


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
class RecipeUnloaded:
    """
    CORE holds no recipe any more: the answer to UnloadRecipe.

    The frontend returns to its no-recipe state on this, not on its own
    click, so what it shows always matches what CORE holds.
    """


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

    `accepted` True: the value is in config.ini now, for the next read of it.
    False: the file was not touched, and `reason` says why in words meant for
    whoever made the change - a value of the wrong type, a key that does not
    exist, a read-only section, or a settings file that cannot be used.
    `key` and `value` repeat the request, so a frontend waiting on several
    answers can tell them apart.
    """

    key: str
    value: str
    accepted: bool
    reason: str = ""


@dataclass
class DefaultConfigRestored:
    """
    CORE's answer to RestoreDefaultConfig.

    `accepted` True: config.ini now holds the template defaults, in force from
    the next start. False: the file was not rewritten, and `reason` says why in
    words meant for the operator.
    """

    accepted: bool
    reason: str = ""


# --- The link ------------------------------------------------------------------
#
# The two unions are the contract: `unhandled()` is checked against them, and the
# protocol tests enumerate them with typing.get_args().

HmiToCore = (
    LoadRecipe
    | UnloadRecipe
    | StartSequence
    | StopSequence
    | PauseSequence
    | ResumeSequence
    | SetConfigParameter
    | RestoreDefaultConfig
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
    | DefaultConfigRestored
    | RecipeLoaded
    | RecipeUnloaded
    | RunStarted
    | RunFinished
    | RunPaused
    | RunResumed
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
