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
  land between them and return half a line. Anything not ending in a newline is
  held back until the rest arrives, so a caller never sees half a record.
* **Volume.** `config.ini` ships DEBUG for the refactor, so the file carries the
  full message trace - every message twice, sent and received. That is what the
  Debug Monitor is for; the operator panel filters to `PANEL_LOG_LEVEL` and up.
"""

from __future__ import annotations

import logging
from pathlib import Path

#: Lowest level the operator's panel shows, whatever the file holds.
PANEL_LOG_LEVEL = logging.INFO

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
        dropped: they are what the Debug Monitor is for. None when the record is
        below `min_level`.

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
        self._handle = None
        #: The tail of the file that is not yet a whole line.
        self._partial = ""
        #: Whether the record the panel last showed is still being written to,
        #: i.e. whether a continuation line now belongs to a shown record.
        self._in_shown_record = False

    def open(self) -> None:
        """
        Open the log for reading, positioned at its start.

        `errors="replace"` rather than the default: the Logger pins UTF-8 when it
        writes, but a log truncated mid-character must still be readable. A panel
        that goes blank on one bad byte is useless exactly when it is needed.

        Raises:
            OSError: if the log cannot be opened. The caller decides what that
                means - in the GUI, a panel that stays empty, not a dead window.
        """
        self.close()
        self._handle = self.path.open("r", encoding="utf-8", errors="replace")
        self._partial = ""
        self._in_shown_record = False

    def new_lines(self) -> list[str]:
        """
        Display lines for every whole record that appeared since the last call.

        Returns:
            The lines, ready for `LogPanel.append_line()`. Empty when nothing was
            written, or when everything written was below `min_level`.
        """
        if self._handle is None:
            return []

        text = self._partial + self._handle.read()
        if not text:
            return []

        raw_lines = text.split("\n")
        # The last element is whatever followed the final newline: "" when the
        # file ends cleanly, the start of the next record when it does not.
        self._partial = raw_lines.pop()

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
        if self._handle is not None:
            self._handle.close()
            self._handle = None
