# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from pypts.hmi.gui.palette import LOG_LEVEL_COLORS, get_palette


class LogPanel(QPlainTextEdit):
    _LEVELS = tuple(LOG_LEVEL_COLORS.keys())

    def __init__(self, parent=None):
        super().__init__(parent)
        #: Every line currently shown, so a theme change can redraw them. The
        #: widget itself only keeps formatted blocks, and a QTextCharFormat that
        #: is already on screen cannot be re-coloured in place - so a switch to
        #: dark used to leave the whole backlog in the light theme's grey,
        #: which on charcoal is barely readable.
        self._lines: list[str] = []
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFixedHeight(160)
        self.setFont(QFont("Courier New", 9))
        self._dark = False

    def set_dark(self, dark: bool):
        if dark == self._dark:
            return
        self._dark = dark
        self.redraw()

    def redraw(self) -> None:
        """Re-append every remembered line in the current theme's colours."""
        remembered = list(self._lines)
        super().clear()
        self._lines = []
        for line in remembered:
            self.append_line(line)

    def append_line(self, line: str):
        self._lines.append(line)
        # Mirror the widget's own rolling buffer, or the remembered list grows
        # without bound over a long run.
        if len(self._lines) > self.maximumBlockCount():
            del self._lines[: len(self._lines) - self.maximumBlockCount()]

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        level_found = next((lvl for lvl in self._LEVELS if line.upper().startswith(lvl)), None)
        if level_found:
            fmt_level = QTextCharFormat()
            fmt_level.setForeground(QColor(LOG_LEVEL_COLORS[level_found]))
            fmt_level.setFontWeight(QFont.Medium)
            cursor.insertText(level_found, fmt_level)

            fmt_rest = QTextCharFormat()
            fmt_rest.setForeground(QColor(get_palette(self._dark).log_text_muted))
            cursor.insertText(line[len(level_found):] + "\n", fmt_rest)
        else:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(get_palette(self._dark).log_text_muted))
            cursor.insertText(line + "\n", fmt)

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def load_lines(self, lines: list[str]):
        self.clear()
        for line in lines:
            self.append_line(line)

    def clear(self) -> None:
        """Empty the panel. Overridden so the remembered lines go with it."""
        self._lines = []
        super().clear()
