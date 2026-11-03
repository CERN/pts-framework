# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The LOG OUTPUT panel: the run log's lines, coloured by level and filtered by it.

`LogPanel` is the text. It is fed display lines (`log_tail.format_record()`:
level first) and decides two things per line:

* **Which filter group it belongs to.** DEBUG, INFO, WARNING (and WARN) or
  ERROR (and CRITICAL) - the four buttons over the panel. A line that does not start with
  a level - the traceback under an ERROR - belongs to the record above it, so it
  is shown and hidden with that record. A line with no record above it ("No run
  log to follow.") belongs to no group and is always shown.
* **The worst level seen** since the panel was last cleared - WARNING or ERROR -
  which `CenterContent` shows as an icon beside the panel's title. It counts
  every line, shown or hidden: a hidden error is exactly what the icon is for.

Filtering is display only. Every line is remembered (up to
`MAX_REMEMBERED_LINES`, hidden ones included), so turning a level back on brings
its lines back where they were.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from pypts.hmi.gui.palette import LOG_LEVEL_COLORS, get_palette

#: The filter groups, in the order their buttons are shown, and the levels in each.
LEVEL_GROUPS: dict[str, tuple[str, ...]] = {
    "DEBUG": ("DEBUG",),
    "INFO": ("INFO",),
    "WARNING": ("WARNING", "WARN"),
    "ERROR": ("ERROR", "CRITICAL"),
}

#: The groups the worst-level icon reports, least severe first.
ALERT_GROUPS = ("WARNING", "ERROR")

#: Lines shown at most - the widget's own rolling buffer.
MAX_SHOWN_LINES = 2000

#: Lines remembered at most, shown or hidden. Larger than MAX_SHOWN_LINES
#: because hidden DEBUG lines are remembered too: with the same limit, a run
#: chatty at DEBUG would push the INFO backlog out while DEBUG is off.
MAX_REMEMBERED_LINES = 10000


def group_of_level(level: str) -> str | None:
    """The filter group a level belongs to, or None for a level in no group."""
    for group, levels in LEVEL_GROUPS.items():
        if level in levels:
            return group
    return None


class LogPanel(QPlainTextEdit):
    #: The worst level seen changed: "WARNING", "ERROR", or "" once cleared.
    worst_level_changed = Signal(str)

    _LEVELS = tuple(LOG_LEVEL_COLORS.keys())

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: Every line received, with its filter group, so a theme change or a
        #: filter change can redraw them. The widget itself only keeps the
        #: blocks it shows, and a QTextCharFormat that is already on screen
        #: cannot be re-coloured in place - so a switch to dark used to leave
        #: the whole backlog in the light theme's grey.
        self._lines: list[tuple[str, str | None]] = []
        #: The group of the last record line, which a continuation line joins.
        self._current_group: str | None = None
        #: Groups whose lines are not shown.
        self._hidden: set[str] = set()
        #: "WARNING" or "ERROR" once one was received, "" before.
        self._worst = ""
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_SHOWN_LINES)
        # Long lines wrap at the panel's edge - no horizontal scroll bar. A word
        # longer than the panel (a path) breaks anywhere rather than overflowing.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(160)
        # The style hint is what makes this work off Windows. Courier New is a
        # Microsoft font: on a Linux bench without msttcorefonts Qt finds no such
        # family and falls back to the default *proportional* face, which loses
        # the column alignment the log format depends on. Told the family is
        # meant to be monospace, Qt substitutes a real fixed-pitch one instead.
        font = QFont("Courier New", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self._dark = False

    # --- Theme -----------------------------------------------------------------

    def set_dark(self, dark: bool):
        if dark == self._dark:
            return
        self._dark = dark
        self.redraw()

    # --- Filter ----------------------------------------------------------------

    def set_group_shown(self, group: str, shown: bool) -> None:
        """
        Show or hide one filter group's lines - the ones already in the panel too.

        Args:
            group: a key of LEVEL_GROUPS.
            shown: False hides the group's lines; True brings them back.
        """
        if shown:
            if group not in self._hidden:
                return
            self._hidden.discard(group)
        else:
            if group in self._hidden:
                return
            self._hidden.add(group)
        self.redraw()

    def is_group_shown(self, group: str) -> bool:
        return group not in self._hidden

    @property
    def worst_level(self) -> str:
        """The worst level since the last clear: ERROR, WARNING, or "" for neither."""
        return self._worst

    # --- Lines -----------------------------------------------------------------

    def redraw(self) -> None:
        """Rebuild the shown text from every remembered line, in the current
        theme's colours and the current filter."""
        super().clear()
        for line, group in self._lines:
            if group not in self._hidden:
                self._insert(line)
        self._scroll_to_end()

    def append_line(self, line: str):
        level = self._level_of(line)
        if level is not None:
            self._current_group = group_of_level(level)
            group = self._current_group
            self._note_level(group)
        else:
            group = self._current_group

        self._lines.append((line, group))
        # Bounded, or the remembered list grows without limit over a long run.
        if len(self._lines) > MAX_REMEMBERED_LINES:
            del self._lines[: len(self._lines) - MAX_REMEMBERED_LINES]

        if group in self._hidden:
            return
        self._insert(line)
        self._scroll_to_end()

    def load_lines(self, lines: list[str]):
        self.clear()
        for line in lines:
            self.append_line(line)

    def clear(self) -> None:
        """Empty the panel. Overridden so the remembered lines and the worst
        level seen go with it; the filter stays as the operator set it."""
        self._lines = []
        self._current_group = None
        super().clear()
        if self._worst:
            self._worst = ""
            self.worst_level_changed.emit("")

    def _level_of(self, line: str) -> str | None:
        """The level a display line starts with, or None for a continuation line."""
        return next((lvl for lvl in self._LEVELS if line.upper().startswith(lvl)), None)

    def _note_level(self, group: str | None) -> None:
        if group is None or group not in ALERT_GROUPS:
            return
        if self._worst and ALERT_GROUPS.index(self._worst) >= ALERT_GROUPS.index(group):
            return
        self._worst = group
        self.worst_level_changed.emit(group)

    def _insert(self, line: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        level_found = self._level_of(line)
        if level_found:
            fmt_level = QTextCharFormat()
            fmt_level.setForeground(QColor(LOG_LEVEL_COLORS[level_found]))
            fmt_level.setFontWeight(QFont.Weight.Medium)
            cursor.insertText(level_found, fmt_level)

            fmt_rest = QTextCharFormat()
            fmt_rest.setForeground(QColor(get_palette(self._dark).log_text_muted))
            cursor.insertText(line[len(level_found):] + "\n", fmt_rest)
        else:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(get_palette(self._dark).log_text_muted))
            cursor.insertText(line + "\n", fmt)

        self.setTextCursor(cursor)

    def _scroll_to_end(self) -> None:
        self.ensureCursorVisible()
