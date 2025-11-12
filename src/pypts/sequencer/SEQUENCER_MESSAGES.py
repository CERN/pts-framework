# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages that sequencer module can send.
Messages are grouped by the module scope - where the message goes.
As sequencer can communicate with core, only the SequencerToCoreEvent and SequencerInternalEvent classes are defined.

Workflow for adding a sequencer --> core message:
1. Define the message enum in this file
2. Go to the interface core/sequencer_to_core_interface.py (messages that core accepts).
    Add new abstract method in interface class SequencerToCoreInterface
    Add a data layer method in the SequencerToCoreQueue class
3. Add the message handling in the core main loop - core.py --> handle_sequencer_event()
"""
### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL THE DEVELOPMENT REQUIRES THAT
### Sequencer internal events
# class SequencerInternalCommand(Enum):
#     pass  # no events defined yet, add internal events here if necessary
#
# @dataclass
# class SequencerInternalEvent:
#     """Message sent from Sequencer back to Sequencer."""
#     cmd: SequencerInternalCommand
#     payload: dict | None = None

### Sequencer -> Core events
class SequencerToCoreCommand(Enum):
    STOP = auto()  # message sent on the module crash
    SEQUENCE_RESULT = auto()

@dataclass
class SequencerToCoreEvent:
    """Message sent from Sequencer to Core."""
    cmd: SequencerToCoreCommand
    payload: dict | None = None


