# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from enum import Enum, auto
from dataclasses import dataclass

class ErrorSeverity(Enum):
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()

@dataclass
class ModuleErrorEvent:
    source: str            # "sequencer", "report", etc.
    severity: ErrorSeverity
    message: str
    exception: str | None = None
    traceback: str | None = None