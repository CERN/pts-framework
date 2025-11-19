# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages that the sequencer module can send.
Messages are grouped according to the module scope, i.e., the destination module.
Since the sequencer only communicates with the core, only SequencerToCoreEvent and
SequencerInternalEvent classes are defined here.

Workflow for adding a sequencer-to-core message:
1. Define the new message enum entry in this file.
2. Update the interface core/sequencer_to_core_interface.py with a new abstract method
   in SequencerToCoreInterface and a data layer method in SequencerToCoreQueue.
3. Implement the message handling in core.py within handle_sequencer_event().

Note:
Internal events for the sequencer are currently disabled until development requires them.
"""

### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL DEVELOPMENT REQUIRES THAT
# class SequencerInternalCommand(Enum):
#     pass  # Placeholder for internal commands to the sequencer
#
# @dataclass
# class SequencerInternalEvent:
#     """Message sent internally within the Sequencer module."""
#     cmd: SequencerInternalCommand
#     payload: dict | None = None

### Sequencer -> Core events
class SequencerToCoreCommand(Enum):
    STOP = auto()  # Signals that the sequencer module has crashed or is stopping
    SEQUENCE_RESULT = auto()  # Conveys the result of a sequence execution

@dataclass
class SequencerToCoreEvent:
    """
    Represents a message sent from the Sequencer module to the Core module.
    Attributes:
      - cmd: Command type indicated by SequencerToCoreCommand enum
      - payload: Optional dictionary carrying additional event data
    """
    cmd: SequencerToCoreCommand
    payload: dict | None = None
