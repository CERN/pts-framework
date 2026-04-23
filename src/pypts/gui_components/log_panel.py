# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from pypts.gui_components.styles import LOG_LEVEL_COLORS


class LogPanel(QPlainTextEdit):
    _LEVELS = tuple(LOG_LEVEL_COLORS.keys())

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFixedHeight(160)
        self.setFont(QFont("Courier New", 9))
        self._dark = False

    def set_dark(self, dark: bool):
        self._dark = dark

    def append_line(self, line: str):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        level_found = next((lvl for lvl in self._LEVELS if line.upper().startswith(lvl)), None)
        if level_found:
            fmt_level = QTextCharFormat()
            fmt_level.setForeground(QColor(LOG_LEVEL_COLORS[level_found]))
            fmt_level.setFontWeight(QFont.Medium)
            cursor.insertText(level_found, fmt_level)

            fmt_rest = QTextCharFormat()
            fmt_rest.setForeground(QColor("#b0b0b0" if self._dark else "#555555"))
            cursor.insertText(line[len(level_found):] + "\n", fmt_rest)
        else:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#b0b0b0" if self._dark else "#555555"))
            cursor.insertText(line + "\n", fmt)

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def load_lines(self, lines: list[str]):
        self.clear()
        for line in lines:
            self.append_line(line)
