# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Reading this run's log back, for the operator's LOG OUTPUT panel.

The GUI does not tap the root logger to fill that panel. Its own records are the
only ones it would see that way, and they are the least interesting ones: what
the operator wants is the run, which happens in CORE and the engine. So the panel
shows the run log itself - the file the Logger process writes - read from the
outside like any other reader.

Reading a file the Logger holds open works on both platforms here: it opens the
log through `logging.FileHandler(mode="a", encoding="utf-8")`, which leaves the
default Windows share mode in place, so a reader is allowed. Nothing here writes,
locks or truncates, and closing the GUI cannot affect the run.

Two things need care:

* **Torn records.** A record is one `write()` followed by a flush, but a read can
  land between them and return half a line. `LineTail` (line_tail.py) holds back
  anything not ending in a newline until the rest arrives, so a caller never
  sees half a record.
* **Volume.** `config.ini` ships TRACE for the refactor, so the file carries the
  full message trace - every message twice, sent and received. The panel never
  sees it: this filters to `PANEL_LOG_LEVEL` (DEBUG) and up. DEBUG itself does
  reach the panel, which hides it unless its DEBUG button is on (log_panel.py).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pypts.hmi.gui.line_tail import LineTail

# Registers the TRACE name, so the message trace is filtered out by level
# rather than shown as a line with a level nobody knows.
from pypts.logger.levels import TRACE  # noqa: F401 - imported for its side effect

#: Lowest level that reaches the panel, whatever the file holds. DEBUG, so the
#: panel's DEBUG button has lines to show; TRACE never comes through.
PANEL_LOG_LEVEL = logging.DEBUG

#: `log.LOG_FORMAT` is `time;LEVEL;process;file:func;message`. Split with this
#: maxsplit so a message containing a semicolon stays in one piece.
_RECORD_FIELDS = 5

#: Width the level is padded to, so the timestamps line up under each other.
_LEVEL_WIDTH = 9


def format_record(line: str, min_level: int = PANEL_LOG_LEVEL) -> str | None:
    """
    One line of the log file as the panel shows it, or None to drop it.

    Args:
        line: a raw line of the run log, without its terminator.
        min_level: records below this level are dropped.

    Returns:
        `LEVEL     HH:MM:SS  message`, keeping the level first because that is
        what `LogPanel.append_line()` colours on. Process and source location are
        dropped: they are developer detail, read in the log file. None when the
        record is below `min_level`.

        A line that is not a record at all - the continuation lines of a
        traceback, which logging writes under the record they belong to - is
        returned unchanged. Deciding whether to show it needs the level of the
        record above it, which a single line does not carry; `LogTail` keeps
        that context and does the dropping.
    """
    fields = line.split(";", _RECORD_FIELDS - 1)
    if len(fields) < _RECORD_FIELDS:
        return line

    timestamp, level, _process, _location, message = fields

    level_number = logging.getLevelNamesMapping().get(level)
    if level_number is None:
        # A line shaped like a record but with a level nobody knows. Show it:
        # hiding something unrecognised is worse than showing one odd line.
        return line
    if level_number < min_level:
        return None

    # "2026-09-01 12:04:31.123" -> "12:04:31". The date is today's and the
    # milliseconds belong to the trace, so neither earns space in the panel.
    clock = timestamp.partition(" ")[2].partition(".")[0] or timestamp

    return f"{level:<{_LEVEL_WIDTH}}{clock}  {message}"


class LogTail:
    """
    The run log, read forwards, repeatedly, filtered for the operator.

    Open it once and call `new_lines()` as often as you like; each call returns
    the display lines for whatever whole records have appeared since the last
    one. An idle call costs one read that returns nothing.

    It does not poll on its own - the caller owns the timer. In the GUI that is a
    QTimer, so this never needs a thread and the window never waits on a file.
    """

    def __init__(self, path, min_level: int = PANEL_LOG_LEVEL) -> None:
        self.path = Path(path)
        self.min_level = min_level
        self._tail = LineTail(self.path)
        #: Whether the record the panel last showed is still being written to,
        #: i.e. whether a continuation line now belongs to a shown record.
        self._in_shown_record = False

    def open(self) -> None:
        """
        Open the log for reading, positioned at its start.

        Reading is `LineTail.open()`, which decodes with `errors="replace"`: the
        Logger pins UTF-8 when it writes, but a log truncated mid-character must
        still be readable. This also restarts the continuation-line context.

        Raises:
            OSError: if the log cannot be opened. The caller decides what that
                means - in the GUI, a panel that stays empty, not a dead window.
        """
        self._tail.open()
        self._in_shown_record = False

    def new_lines(self) -> list[str]:
        """
        Display lines for every whole record that appeared since the last call.

        Returns:
            The lines, ready for `LogPanel.append_line()`. Empty when nothing was
            written, or when everything written was below `min_level`.
        """
        raw_lines = self._tail.whole_lines()

        shown = []
        for raw_line in raw_lines:
            line = self._display_line(raw_line.rstrip("\r"))
            if line is not None:
                shown.append(line)
        return shown

    def _display_line(self, raw_line: str) -> str | None:
        """
        One raw line as the panel shows it, or None to drop it.

        Wraps `format_record()` with the one piece of state it cannot have: a
        continuation line - traceback text under an ERROR - is shown or dropped
        with the record it belongs to.
        """
        formatted = format_record(raw_line, self.min_level)
        is_record = raw_line.count(";") >= _RECORD_FIELDS - 1

        if is_record:
            self._in_shown_record = formatted is not None
            return formatted

        if self._in_shown_record:
            return formatted
        return None

    def close(self) -> None:
        """Release the file. Safe to call twice, and safe to call before open()."""
        self._tail.close()
