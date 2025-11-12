# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from enum import Enum, auto
from dataclasses import dataclass

"""
This file defines all possible messages that core module can send.
Messages are grouped by the module scope - where the message goes.
As core can communicate with HMI, sequencer and report, multiple classes are defined here.

Workflow for adding a core --> sequencer/hmi/report message:
1. Define the message enum in this file
2. Go to the module interface (for example HMI/core_to_HMI_interface.py (messages that HMI accepts)).
    Add new abstract method in interface class CoreToHMIInterface
    Add a data layer method in the CoreToHMIQueue class
3. Add the message handling in the module specific main loop - in this case it will be the main loop of GUI or CLI --> handle_core_event()
"""
### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL THE DEVELOPMENT REQUIRES THAT
### Core internal events
# class CoreInternalCommand(Enum):
#     pass # no messages defined yet
#
# @dataclass
# class CoreInternalEvent:
#     cmd: CoreInternalCommand
#     payload: dict | None = None

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
