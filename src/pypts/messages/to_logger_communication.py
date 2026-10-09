# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The any-module -> Logger link. The one link that does not go through CORE, so a
log record does not depend on CORE being alive.

Its queue carries two kinds of item: LogRecords put there by QueueHandler, and
the control messages below. The Logger tells them apart by type.
"""

from dataclasses import dataclass

# --- any module -> Logger: commands -------------------------------------------


@dataclass
class SetStdoutEnabled:
    """Console echo for the whole application. The Logger owns that handler."""

    enabled: bool


@dataclass
class SwitchLogFile:
    """
    Close the run log and carry on in a new file at `log_file_path`.

    Queued like everything else, so every record put on the queue before it
    lands in the old file and every record after it in the new one. The old
    file is closed and never written again. Sent by the GUI when the operator
    unloads the recipe; the sender decides the new path.
    """

    log_file_path: str


@dataclass
class StartRunLog:
    """
    Carry on in the run log at `log_file_path` until EndRunLog.

    The Logger remembers the file it was writing - the session log - and
    returns to it on EndRunLog. The Logger, not the sender, remembers it,
    because only the Logger knows which file the session is in after an
    unload has switched it. Sent by the Sequencer before RunStarted.
    """

    log_file_path: str


@dataclass
class EndRunLog:
    """
    Close the run log and carry on in the session log, appending to it.

    Sent by the Sequencer before RunFinished. Without a run log open it
    changes nothing.
    """


@dataclass
class StopLogger:
    """Stop the Logger. Sent last, and queued, so pending records are written first."""


# --- The link ------------------------------------------------------------------

LoggerControl = SetStdoutEnabled | SwitchLogFile | StartRunLog | EndRunLog | StopLogger
