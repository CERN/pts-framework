# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages that modules can send.
Keep all messaging defined there first, then follow with the implementation
on the module side.

Messages are inspired from what is known from LabVIEW T-pattern design
"""
### Sequencer internal events
class SequencerInternalCommand(Enum):
    pass  # no events defined yet

@dataclass
class SequencerInternalEvent:
    cmd: SequencerInternalCommand
    payload: dict | None = None

### Sequencer -> Core events
class SequencerToCoreCommand(Enum):
    STOP = auto()  # message sent on the module crash
    SEQUENCE_RESULT = auto()

@dataclass
class SequencerToCoreEvent:
    """Message sent from Sequencer to Core."""
    cmd: SequencerToCoreCommand
    payload: dict | None = None