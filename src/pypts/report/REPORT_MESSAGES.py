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
### Report internal events
class ReportInternalCommand(Enum):
    pass  # no events defined yet

@dataclass
class ReportInternalEvent:
    cmd: ReportInternalCommand
    payload: dict | None = None

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