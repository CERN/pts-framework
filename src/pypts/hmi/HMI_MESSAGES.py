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
class HMIToCoreCommand(Enum):
    STOP = auto()  # on the module crash
    LOAD_RECIPE = auto()
    START_SEQUENCE = auto()

@dataclass
class HMIToCoreEvent:
    cmd: HMIToCoreCommand
    payload: dict | None = None



