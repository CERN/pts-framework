# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages that report module can send.
Messages are grouped by the module scope - where the message goes.
As report can communicate with core, only the ReportToCoreEvent and ReportInternalEvent classes are defined.

Workflow for adding a report --> core message:
1. Define the message enum in this file
2. Go to the interface core/report_to_core_interface.py (messages that core accepts).
    Add new abstract method in interface class ReportToCoreInterface
    Add new abstract method in interface class ReportToCoreInterface
    Add a data layer method in the ReportToCoreQueue class
3. Add the message handling in the core main loop - core.py --> handle_report_event()
"""
### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL THE DEVELOPMENT REQUIRES THAT
### Report internal events
# class ReportInternalCommand(Enum):
#     pass  # no events defined yet
#
# @dataclass
# class ReportInternalEvent:
#     """Message sent from Report back to Report."""
#     cmd: ReportInternalCommand
#     payload: dict | None = None

### Report -> Core events
class ReportToCoreCommand(Enum):
    STOP = auto() # message sent on the module crash
    REPORT_GENERATED = auto()
    REPORT_EXPORTED = auto()

@dataclass
class ReportToCoreEvent:
    """Message sent from Report to Core."""
    cmd: ReportToCoreCommand
    payload: dict | None = None