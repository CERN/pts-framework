# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from dataclasses import dataclass
from enum import Enum, auto

"""
This file defines all possible messages the report module can send.
Messages are grouped by their destination module scope.
Since the report module communicates only with the core, only ReportToCoreEvent
and ReportInternalEvent classes are defined here.

Workflow for adding a report-to-core message:
1. Define the new message enum entry in this file.
2. Modify the interface in core/report_to_core_interface.py:
   - Add corresponding abstract methods in ReportToCoreInterface.
   - Implement matching methods in ReportToCoreQueue.
3. Add handling for the new message in the core main loop (core.py -> handle_report_event()).

Note:
Internal report events are currently disabled and can be added if needed.
"""

### INTERNAL EVENTS DISABLED AT THE MOMENT, UNTIL DEVELOPMENT REQUIRES THAT
# class ReportInternalCommand(Enum):
#     pass  # Placeholder for internal commands within the report module
#
# @dataclass
# class ReportInternalEvent:
#     """Message sent internally within the Report module."""
#     cmd: ReportInternalCommand
#     payload: dict | None = None

### Report -> Core events
class ReportToCoreCommand(Enum):
    STOP = auto()  # Message sent when the report module crashes or stops
    REPORT_GENERATED = auto()  # Indicates a report has been generated
    REPORT_EXPORTED = auto()   # Indicates a report has been exported
    ERROR = auto()  # Add this for error messages

@dataclass
class ReportToCoreEvent:
    """
    Represents a message sent from the Report module to the Core module.
    Attributes:
      - cmd: Command type from the ReportToCoreCommand enum
      - payload: Optional dictionary with additional event data
    """
    cmd: ReportToCoreCommand
    payload: dict | None = None
