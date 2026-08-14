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


@dataclass(frozen=True, slots=True)
class SetStdoutEnabled:
    """Console echo for the whole application. The Logger owns that handler."""

    enabled: bool


@dataclass(frozen=True, slots=True)
class StopLogger:
    """Stop the Logger. Sent last, and queued, so pending records are written first."""


# --- The link ------------------------------------------------------------------

LoggerControl = SetStdoutEnabled | StopLogger
