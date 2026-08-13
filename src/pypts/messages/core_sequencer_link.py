# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The CORE <-> Sequencer link.

Two processes today, two threads in one process after the roadmap's topology
change. Neither end knows the difference: the launcher decides which queue type
the QueueWrapper wraps.

Most of the traffic is the run-progress events in run_events.py. The Sequencer
emits them, CORE forwards them to the HMI unchanged, and CORE reacts to the ones
it cares about on the way past.
"""

from dataclasses import dataclass

from pypts.messages.common import Heartbeat, ModuleError
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
    """
    Run one named sequence of the recipe CORE has loaded.

    The old CoreToSequencerInterface.run_sequence() took no arguments at all,
    so the sequence name the operator picked had nowhere to go between the HMI
    and the Sequencer.
    """

    sequence_name: str


@dataclass(frozen=True, slots=True)
class StopSequence:
    """
    Abort the running sequence but keep the module alive.

    CORE had a method to send this and the Sequencer had no branch for it, so it
    would have been logged as an unknown event while the sequence carried on.
    """


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
