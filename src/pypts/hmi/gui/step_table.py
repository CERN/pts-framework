# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The LeftSidebar content: the step table, which *is* the run's result view.

The one mechanic everything hangs on, inherited from the old GUI (gui.md
section 2): **rows are keyed by step id, not by index.** Each name cell
carries its step's UUID in the UserRole, and every update finds its row by
that id - so the table tolerates any event order, and a step is updated twice
(Running... then the verdict) without anyone tracking a cursor.
"""

from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.result_colors import FALLBACK_COLORS, RESULT_COLORS
from pypts.logger.log import log
from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import SequenceSummary, StepStarted


def read_only(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
    return item


class StepTableContent(QWidget):
    """Three columns: Step name (bold), Description, Result."""

    def __init__(self) -> None:
        super().__init__()
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Step name", "Description", "Result"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 300)
        self.table.horizontalHeader().setStretchLastSection(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.table)

    # --- Filling ---------------------------------------------------------------

    def show_sequence(self, sequence: SequenceSummary) -> None:
        """One row per step, Result 'Pending', the step id stored in the row."""
        self.table.setRowCount(len(sequence.steps))
        for row, step in enumerate(sequence.steps):
            name_item = read_only(QTableWidgetItem(step.step_name))
            name_item.setData(Qt.ItemDataRole.UserRole, str(step.step_id))
            name_font = name_item.font()
            name_font.setBold(True)
            name_item.setFont(name_font)
            self.table.setItem(row, 0, name_item)

            self.table.setItem(row, 1, read_only(QTableWidgetItem(step.description)))
            self.table.setItem(row, 2, self._pending_item())
        self.table.resizeRowsToContents()

    def reset_to_pending(self) -> None:
        """Back to 'Pending' everywhere - a re-run starts from a clean table."""
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 2, self._pending_item())

    # --- Updating, by step id --------------------------------------------------

    def mark_running(self, event: StepStarted) -> None:
        row = self._find_row(event.step_id)
        if row is None:
            return
        item = read_only(QTableWidgetItem("Running..."))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, item)
        self.table.scrollToItem(
            self.table.item(row, 0), QAbstractItemView.ScrollHint.EnsureVisible
        )

    def show_outcome(self, outcome: StepOutcome) -> None:
        row = self._find_row(outcome.step_id)
        if row is None:
            return
        background, text_color = RESULT_COLORS.get(outcome.result, FALLBACK_COLORS)
        item = read_only(QTableWidgetItem(str(outcome.result)))
        item.setBackground(QColor(background))
        item.setForeground(QColor(text_color))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if outcome.error_info:
            item.setToolTip(outcome.error_info)
        self.table.setItem(row, 2, item)

    def _pending_item(self) -> QTableWidgetItem:
        item = read_only(QTableWidgetItem("Pending"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _find_row(self, step_id: UUID) -> int | None:
        """The UserRole scan. A miss is logged, not raised - the run goes on."""
        wanted = str(step_id)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == wanted:
                return row
        log.warning("No table row for step %s - a different sequence is displayed?", step_id)
        return None
