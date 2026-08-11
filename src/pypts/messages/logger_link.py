# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The any-module -> Logger link. The one link that does not go through CORE.

That exception is deliberate and worth keeping: every module needs to log, and a
log record must not depend on CORE being alive to be written. See logger/log.py
for why a single writer process owns the file.

This link is also the only one whose queue carries two kinds of item. Ordinary
log records are put on it by logging's own QueueHandler as plain
logging.LogRecord objects; the control messages below travel the same queue and
steer the Logger itself. The Logger tells them apart by type, which is why the
control messages must stay dataclasses rather than anything LogRecord-shaped.
"""

from dataclasses import dataclass

# --- any module -> Logger: commands -------------------------------------------


@dataclass(frozen=True, slots=True)
class SetStdoutEnabled:
    """
    Turn the console echo on or off for the whole application.

    The Logger owns the console handler, so this has to be a message: a local
    handler change in one process would not affect any other.
    """

    enabled: bool


@dataclass(frozen=True, slots=True)
class StopLogger:
    """
    Stop the Logger. Sent last, by the launcher.

    Being queued rather than immediate is the point: the Logger drains
    everything already in flight before it acts on this, so records emitted
    while the other modules shut down still reach the file.
    """


# --- The link ------------------------------------------------------------------

LoggerControl = SetStdoutEnabled | StopLogger
