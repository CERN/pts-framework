# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from enum import Enum, auto
from dataclasses import dataclass

"""
This file defines all possible messages that modules can exchange.
Keep all messaging defined there first, then follow with the implementation
on the module side.

Messages are inspired from what is known from LabVIEW T-pattern design
"""
### Core internal events
class CoreInternalCommand(Enum):
    LOAD_RECIPE = auto()
    STOP = auto() # to stop the module

@dataclass
class CoreInternalEvent:
    cmd: CoreInternalCommand
    payload: dict | None = None

### Core -> Sequencer events
class CoreToSequencerCommand(Enum):
    RUN_SEQUENCE = auto()
    STOP_SEQUENCE = auto()
    STOP = auto() # to stop the module

@dataclass
class CoreToSequencerEvent:
    cmd: CoreToSequencerCommand
    payload: dict | None = None

### Core -> Report events
class CoreToReportCommand(Enum):
    GENERATE = auto()
    EXPORT = auto()
    STOP = auto() # to stop the module

@dataclass
class CoreToReportEvent:
    cmd: CoreToReportCommand
    payload: dict | None = None

### Core -> HMI events
class CoreToHMICommand(Enum):
    UPDATE_STATUS = auto() # to show message on the runtime log
    STOP = auto() # to stop the module

@dataclass
class CoreToHMIEvent:
    cmd: CoreToHMICommand
    payload: dict | None = None
