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
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.palette import UNKNOWN_VERDICT, get_palette
from pypts.logger.log import log
from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import SequenceSummary, StepStarted

#: What the two pre-verdict states say in the cell. Upper-cased and stripped of
#: the dots, each is its own key in the chip table - so the Result column is
#: coloured from one place whatever state a row is in.
_PENDING_TEXT = "Pending"
_RUNNING_TEXT = "Running..."

#: Step name: wide enough for a generated name like "Add numbers [a=100, b=250]",
#: and draggable, because how much room a name needs is the operator's call.
_NAME_WIDTH = 220

#: Result: fixed and narrow. It only ever holds Pending / Running... / a verdict,
#: so every pixel beyond that is taken from the description.
_RESULT_WIDTH = 90


def read_only(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
    return item


class StepTableContent(QWidget):
    """Three columns: Step name (bold), Description, Result.

    Sizing: the name is draggable, the result is fixed and narrow, and the
    description stretches into what is left - so the one column with real prose
    in it gets the room. Rows are sized to their contents, so a description that
    wraps onto three lines gets a row three lines tall instead of being clipped.
    """

    def __init__(self) -> None:
        super().__init__()
        self._dark = False
        self.table = QTableWidget()
        self.table.setObjectName("stepTable")
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Step name", "Description", "Result"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Long text wraps onto more lines instead of being cut off with an
        # ellipsis - which is what makes the row heights below worth having.
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)

        # Rows grow to fit what is in them, and keep doing so afterwards: the
        # description rewraps whenever the window or a column is resized, and
        # ResizeToContents is what re-measures the row when it does.
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        # The description takes every pixel the other two do not: it is the
        # column whose text actually wraps.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, _NAME_WIDTH)
        self.table.setColumnWidth(2, _RESULT_WIDTH)

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

        # ResizeToContents keeps the heights right from here on; this one call
        # is for right now, before the table has been laid out and while the
        # stretch column still has its pre-layout width.
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
        item = self._state_item(_RUNNING_TEXT)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.table.setItem(row, 2, item)
        self.table.scrollToItem(
            self.table.item(row, 0), QAbstractItemView.ScrollHint.EnsureVisible
        )

    def show_outcome(self, outcome: StepOutcome) -> None:
        row = self._find_row(outcome.step_id)
        if row is None:
            return
        item = self._state_item(str(outcome.result))
        if outcome.error_info:
            item.setToolTip(outcome.error_info)
        self.table.setItem(row, 2, item)

    # --- Theme -----------------------------------------------------------------

    def set_dark(self, dark: bool) -> None:
        """
        Repaint the Result column for the new theme.

        The chips are the one thing in this table the stylesheet cannot reach -
        they are set per item - so a theme change has to come through here or the
        verdicts keep the old theme's colours for the rest of the run. The state
        each row is in is read back from the cell's own text: it is the verdict
        name, or Pending / Running..., which is exactly the chip key.
        """
        self._dark = dark
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 2)
            if cell is None:
                continue
            repainted = self._state_item(cell.text())
            repainted.setToolTip(cell.toolTip())
            self.table.setItem(row, 2, repainted)

    def _state_item(self, text: str) -> QTableWidgetItem:
        """One Result cell: the state's text on the current theme's chip."""
        chip = get_palette(self._dark).verdicts.get(text.upper().rstrip("."), None)
        if chip is None:
            chip = UNKNOWN_VERDICT
        item = read_only(QTableWidgetItem(text))
        item.setBackground(QColor(chip.background))
        item.setForeground(QColor(chip.text))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _pending_item(self) -> QTableWidgetItem:
        return self._state_item(_PENDING_TEXT)

    def _find_row(self, step_id: UUID) -> int | None:
        """The UserRole scan. A miss is logged, not raised - the run goes on."""
        wanted = str(step_id)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == wanted:
                return row
        log.warning("No table row for step %s - a different sequence is displayed?", step_id)
        return None
