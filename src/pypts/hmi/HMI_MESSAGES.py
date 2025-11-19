# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages that HMI (Human Machine Interface) modules can send.
Messages are grouped by module scope, i.e., the target module.
Since HMI modules communicate only with the Core, only HMIToCoreEvent and HMIInternalEvent
classes are defined here.

Workflow for adding a HMI-to-Core message:
1. Define the new message enum entry in this file.
2. Update the interface in core/HMI_to_core_interface.py:
   - Add the corresponding abstract method in HMIToCoreInterface.
   - Add the data layer method in HMIToCoreQueue.
3. Add handling for the new message in core.py within handle_HMI_event().

Note:
Internal HMI events are currently disabled and can be added if necessary.
"""

### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL DEVELOPMENT REQUIRES THAT
# class HMIInternalCommand(Enum):
#     pass  # Placeholder for possible internal HMI commands
#
# @dataclass
# class HMIInternalEvent:
#     """Message sent internally within the HMI module."""
#     cmd: HMIInternalCommand
#     payload: dict | None = None

### HMI -> Core events
class HMIToCoreCommand(Enum):
    STOP = auto()  # Message sent when the HMI module crashes or stops
    LOAD_RECIPE = auto()  # Command to load a recipe in core
    START_SEQUENCE = auto()  # Command to start a sequence operation
    EXIT = auto()  # Command to exit the HMI module or application
    ERROR = auto()

@dataclass
class HMIToCoreEvent:
    """
    Represents a message sent from an HMI module to Core.
    Attributes:
      - cmd: Command type from the HMIToCoreCommand enum
      - payload: Optional dictionary carrying additional event details
    """
    cmd: HMIToCoreCommand
    payload: dict | None = None
