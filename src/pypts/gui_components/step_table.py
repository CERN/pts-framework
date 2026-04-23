# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QBrush
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from pypts.gui_components.styles import STATUS_COLORS


class StepTable(QTableWidget):
    COLUMNS = ["Step Name", "Description", "Result"]
    COL_NAME = 0
    COL_DESC = 1
    COL_RESULT = 2

    def __init__(self, parent=None):
        super().__init__(0, 3, parent)
        self._dark = False
        self._rows_by_id: dict[str, int] = {}

        self.setHorizontalHeaderLabels(self.COLUMNS)
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.Fixed)
        header.setSectionResizeMode(self.COL_DESC, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_RESULT, QHeaderView.Fixed)
        self.setColumnWidth(self.COL_NAME, 260)
        self.setColumnWidth(self.COL_RESULT, 110)

        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setShowGrid(False)

    def set_dark(self, dark: bool):
        self._dark = dark

    def load_steps(self, steps: list[dict]):
        self._rows_by_id.clear()
        self.setRowCount(0)

        name_font = QFont()
        name_font.setWeight(QFont.DemiBold)

        for step in steps:
            row = self.rowCount()
            step_id = str(step.get("id", ""))
            status = step.get("status", "PENDING")
            self.insertRow(row)
            self._rows_by_id[step_id] = row

            name_item = QTableWidgetItem(step.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, step_id)
            name_item.setFont(name_font)
            self.setItem(row, self.COL_NAME, name_item)

            desc_item = QTableWidgetItem(step.get("description", ""))
            self.setItem(row, self.COL_DESC, desc_item)

            status_item = QTableWidgetItem()
            self.setItem(row, self.COL_RESULT, status_item)

            self._apply_row_style(row, status)
            self.resizeRowToContents(row)

    def update_step_status(self, step_id: str, status: str, status_color: str | None = None, text_color: str | None = None):
        row = self._rows_by_id.get(str(step_id))
        if row is None:
            return False
        self._apply_row_style(row, status, status_color=status_color, text_color=text_color)
        return True

    def mark_running(self, step_id: str):
        row = self._rows_by_id.get(str(step_id))
        if row is None:
            return False
        self._apply_row_style(row, "RUNNING")
        self.scrollToItem(self.item(row, self.COL_NAME), QAbstractItemView.ScrollHint.EnsureVisible)
        return True

    def _apply_row_style(self, row: int, status: str, status_color: str | None = None, text_color: str | None = None):
        is_running = status == "RUNNING"
        row_bg = QColor("#1a2840" if self._dark and is_running else "#EEF5FF" if is_running else "#00000000")

        colors = STATUS_COLORS.get(status, STATUS_COLORS["PENDING"]).copy()
        if status_color is not None:
            colors["bg"] = status_color
        if text_color is not None:
            colors["text"] = text_color

        for col in (self.COL_NAME, self.COL_DESC):
            item = self.item(row, col)
            if item is not None:
                item.setBackground(QBrush(row_bg))

        status_item = self.item(row, self.COL_RESULT)
        if status_item is None:
            return
        label = "Running..." if is_running else status
        status_item.setText(label)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setBackground(QBrush(QColor(colors["bg"])))
        status_item.setForeground(QBrush(QColor(colors["text"])))

        font = status_item.font()
        font.setWeight(QFont.DemiBold)
        font.setItalic(is_running)
        status_item.setFont(font)
