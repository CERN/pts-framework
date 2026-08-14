# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The CORE <-> Sequencer link. The Sequencer is a thread of the Core process.

Most of the traffic is the run-progress events in run_events.py: the Sequencer
emits them and CORE forwards them to the HMI, reacting on the way past.
"""

from dataclasses import dataclass

from pypts.messages.common_messages import Heartbeat, ModuleError
from pypts.messages.run_events import (
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

# --- CORE -> Sequencer: commands ----------------------------------------------


@dataclass(frozen=True, slots=True)
class RunSequence:
    """Run one named sequence of the recipe CORE has loaded."""

    sequence_name: str


@dataclass(frozen=True, slots=True)
class StopSequence:
    """Abort the running sequence but keep the module alive."""


@dataclass(frozen=True, slots=True)
class StopSequencer:
    """Shut the module down. The Sequencer answers with SequencerStopped."""


# --- Sequencer -> CORE: events ------------------------------------------------


@dataclass(frozen=True, slots=True)
class SequencerStopped:
    """The Sequencer's event loop has ended."""


# --- The link ------------------------------------------------------------------

CoreToSequencer = (
    RunSequence
    | StopSequence
    | StopSequencer
    # Answers to questions the Sequencer asked, relayed back by CORE.
    | UserPromptResponse
    | SerialNumberResponse
)

SequencerToCore = (
    SequencerStopped
    | RunStarted
    | RunFinished
    | SequenceStarted
    | SequenceFinished
    | StepStarted
    | StepFinished
    | UserPromptRequest
    | SerialNumberRequest
    | Heartbeat
    | ModuleError
)
