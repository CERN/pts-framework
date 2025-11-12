# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages that HMI modules can send.
Messages are grouped by the module scope - where the message goes.
As HMI can communicate with core, only the HMIToCoreEvent and HMIInternalEvent classes are defined.

Workflow for adding a HMI --> core message:
1. Define the message enum in this file
2. Go to the interface core/HMI_to_core_interface.py (messages that core accepts).
    Add new abstract method in interface class HMIToCoreInterface
    Add a data layer method in the HMIToCoreQueue class
3. Add the message handling in the core main loop - core.py --> handle_HMI_event()
"""

### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL THE DEVELOPMENT REQUIRES THAT
### HMI internal events
# class HMIInternalCommand(Enum):
#     pass  # no events defined yet, add internal events here if necessary
#
# @dataclass
# class HMIInternalEvent:
#     """Message sent from HMI back to HMI."""
#     cmd: HMIInternalCommand
#     payload: dict | None = None

### HMI -> Core events
class HMIToCoreCommand(Enum):
    STOP = auto()  # on the module crash
    LOAD_RECIPE = auto()
    START_SEQUENCE = auto()
    EXIT = auto()

@dataclass
class HMIToCoreEvent:
    """Message sent from HMI to Core."""
    cmd: HMIToCoreCommand
    payload: dict | None = None


