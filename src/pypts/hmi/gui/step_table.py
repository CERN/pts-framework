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

The second thing a name cell carries is that step's rendered YAML, which the
click panel shows (`step_yaml_popup.py`). It rides the same item as the id for
the same reason: one place per row, nothing parallel to keep in step with the
rows, and it survives the theme repaint, which only rebuilds the Result column.
"""

from uuid import UUID

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.palette import UNKNOWN_VERDICT, get_palette
from pypts.hmi.gui.step_yaml_popup import StepYamlPopup
from pypts.logger.log import log
from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import SequenceSummary, StepStarted
from pypts.utilities.common import describe_step_values

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

#: Where a row's rendered YAML lives, beside the step id in UserRole. Both are
#: on the name cell (column 0) - see the module docstring.
_YAML_ROLE = Qt.ItemDataRole.UserRole + 1

#: The columns a click in opens the panel: the step name and the description.
#: The Result column is left out on purpose - it carries its own tooltip with
#: the measured values in it, and a click there is a click on a verdict.
#:
#: They are also the columns the row highlight paints, for the same reason from
#: the other side: the Result cell's background *is* the verdict chip, so
#: tinting it would make PASS a different green on whichever row was clicked.
_POPUP_COLUMNS = (0, 1)


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
        self._running = False
        self.table = QTableWidget()
        self.table.setObjectName("stepTable")
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Step name", "Description", "Result"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Qt's own selection is off: it paints the whole row, the Result cell
        # included, and a selection tint over a verdict chip is a different
        # PASS green on the row that happens to be selected. The click
        # highlight below is painted per cell instead, so the chips are left
        # exactly as `_state_item()` made them.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

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

        # The panel. A click opens it; moving the pointer off the cell that was
        # clicked closes it again. Mouse tracking is what makes cellEntered fire
        # without a button held down, and the event filter is only for leaving
        # the table, which cellEntered cannot tell us about.
        self.yaml_popup = StepYamlPopup(self)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.cellClicked.connect(self._clicked_cell)
        self.table.cellEntered.connect(self._hover_cell)
        self.table.viewport().installEventFilter(self)

        # The row the panel is open on, and therefore the row the highlight is
        # painted on: -1 for none. One row at a time - the panel shows one step.
        self._active_row = -1

    # --- Filling ---------------------------------------------------------------

    def show_sequence(
        self, sequence: SequenceSummary, yaml_sources: tuple[str, ...] = ()
    ) -> None:
        """
        One row per step, Result 'Pending', the step id stored in the row.

        `yaml_sources` is one rendered fragment per row, in the same order, from
        `recipe.step_source`. It is optional and may be short: a row without one
        simply has no panel, which is what a recipe the GUI could not read back
        off disk gets.
        """
        self.hide_yaml_popup()
        self.table.setRowCount(len(sequence.steps))
        for row, step in enumerate(sequence.steps):
            name_item = read_only(QTableWidgetItem(step.step_name))
            name_item.setData(Qt.ItemDataRole.UserRole, str(step.step_id))
            if row < len(yaml_sources):
                name_item.setData(_YAML_ROLE, yaml_sources[row])
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
        self.hide_yaml_popup()
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 2, self._pending_item())

    # --- The click panel -------------------------------------------------------

    def set_running(self, running: bool) -> None:
        """
        Whether a recipe is executing. The panel is an idle-time affordance.

        A run is when the table is being written to and read for verdicts, and
        the operator wants an unobstructed view of it - so the panel is
        suppressed for the whole run, a hold included: paused is still running.
        """
        self._running = running
        if running:
            self.hide_yaml_popup()

    def hide_yaml_popup(self) -> None:
        """Close the panel and drop the row highlight - they are one gesture."""
        self.yaml_popup.hide()
        self._clear_highlight()

    def _clicked_cell(self, row: int, column: int) -> None:
        """
        A click in the name or the description: highlight the row, show its YAML.

        The one place that opens the panel, so it carries the idle gate and the
        no-fragment case too rather than trusting every caller to have checked.
        A click anywhere else - the Result column - closes whatever is open,
        which is also how the operator dismisses the panel without leaving the
        table.
        """
        if self._running or column not in _POPUP_COLUMNS:
            self.hide_yaml_popup()
            return
        item = self.table.item(row, 0)
        if item is None:
            self.hide_yaml_popup()
            return
        source = item.data(_YAML_ROLE)
        if not isinstance(source, str) or not source:
            self.hide_yaml_popup()
            return
        self._highlight_row(row)
        at = QCursor.pos()
        self.yaml_popup.show_for(source, at.x(), at.y())

    def _hover_cell(self, row: int, column: int) -> None:
        """
        The pointer moved onto another cell: the gesture the click started is over.

        Moving off the cell that was clicked is the dismissal, so the panel
        never outstays the pointer - and reading down the table does not drag a
        panel along with it, because the next row has to be clicked in turn.
        """
        if row != self._active_row or column not in _POPUP_COLUMNS:
            self.hide_yaml_popup()

    def _highlight_row(self, row: int) -> None:
        """
        Tint the row the panel is open on, in the row-number column's own blue.

        The Result cell is skipped - see `_POPUP_COLUMNS`.
        """
        self._clear_highlight()
        tint = QColor(get_palette(self._dark).header_background)
        for column in _POPUP_COLUMNS:
            item = self.table.item(row, column)
            if item is not None:
                item.setBackground(tint)
        self._active_row = row

    def _clear_highlight(self) -> None:
        """Back to the table's own painting: no brush at all, not a white one."""
        if self._active_row < 0:
            return
        for column in _POPUP_COLUMNS:
            item = self.table.item(self._active_row, column)
            if item is not None:
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
        self._active_row = -1

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt
        """
        Hide the panel when the pointer leaves the table.

        `cellEntered` says which row was entered and never that the table was
        left, so the viewport's Leave event is the other half of the gesture.
        Returns False throughout: this only watches, it never consumes.
        """
        if event.type() == QEvent.Type.Leave:
            self.hide_yaml_popup()
        return super().eventFilter(watched, event)

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
        # The reason first, then the values - on every verdict, so a PASS row
        # says what was measured too.
        tooltip_lines = describe_step_values(
            dict(outcome.inputs), dict(outcome.outputs), dict(outcome.expectations)
        )
        if outcome.error_info:
            tooltip_lines.insert(0, outcome.error_info)
        if tooltip_lines:
            item.setToolTip("\n".join(tooltip_lines))
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
        # The click highlight is painted in the outgoing theme's blue, so it
        # goes with the theme rather than being repainted: the panel it belongs
        # to is a momentary thing, and a theme switch ends the gesture.
        self.hide_yaml_popup()
        self._dark = dark
        self.yaml_popup.set_dark(dark)
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
        log.debug("No table row for step %s; a different sequence is displayed.", step_id)
        return None
