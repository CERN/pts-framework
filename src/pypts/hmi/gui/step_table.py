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

The second thing a name cell carries is that step's `StepSource` - the whole
sequence the step belongs to, as written, and the step's lines in it - which
the click panel shows (`step_yaml_popup.py`). It rides the same item as the id
for the same reason: one place per row, nothing parallel to keep in step with
the rows, and it survives the theme repaint, which only rebuilds the Result
column.

**Groups fold.** A row that stands for a called sequence (`StepSummary.is_group`)
carries an arrow, and the rows under it - every following row that is deeper -
fold away under it. Nothing is removed: a folded row is only hidden, so every
update that finds its row by step id still finds it. Groups start folded; a click
on a group's name, or a double-click anywhere on its row, folds or unfolds it,
and the table's right-click menu expands or collapses them all.
"""

from uuid import UUID

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
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
from pypts.recipe.step_source import StepSource
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

#: Where a row's StepSource lives, beside the step id in UserRole. Both are on
#: the name cell (column 0) - see the module docstring.
_YAML_ROLE = Qt.ItemDataRole.UserRole + 1

#: The row's depth in the call tree, whether it stands for a called sequence, and
#: - for a group - whether it is unfolded. On the name cell with the rest.
_DEPTH_ROLE = Qt.ItemDataRole.UserRole + 2
_GROUP_ROLE = Qt.ItemDataRole.UserRole + 3
_EXPANDED_ROLE = Qt.ItemDataRole.UserRole + 4
#: The step's own name, without the indentation and the arrow the cell shows.
_NAME_ROLE = Qt.ItemDataRole.UserRole + 5

#: What a group's name starts with, folded and unfolded.
_FOLDED_ARROW = "\u25b8"
_UNFOLDED_ARROW = "\u25be"

#: How far one level of the call tree is indented in the name column.
_INDENT = "    "

#: The columns a click in opens the panel: the step name and the description.
#: The Result column is left out on purpose - it carries its own tooltip with
#: the measured values in it, and a click there is a click on a verdict.
#:
#: They are also the columns the row highlight paints, for the same reason from
#: the other side: the Result cell's background *is* the verdict chip, so
#: tinting it would make PASS a different green on whichever row was clicked.
_POPUP_COLUMNS = (0, 1)

#: How often an open panel looks at where the pointer is.
_POINTER_CHECK_MS = 100

#: Slack, in pixels, around the pointer's way from the clicked cell to the panel.
_CORRIDOR_SLACK = 12


def _name_text(name: str, depth: int, is_group: bool, expanded: bool) -> str:
    """
    What a name cell shows: indented by depth, a group with its arrow.

    A step of the sequence itself that is not a group reads exactly as its name.
    """
    prefix = _INDENT * depth
    if not is_group:
        return prefix + name
    arrow = _FOLDED_ARROW
    if expanded:
        arrow = _UNFOLDED_ARROW
    return f"{prefix}{arrow} {name}"


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

        # The panel. A click opens it; it closes when the pointer is neither on
        # the clicked row, nor on the panel, nor on its way between the two. The
        # pointer is *looked at* on a timer rather than followed through enter
        # and leave events: the panel is a window of its own, and moving onto
        # it to scroll is exactly a leave the table would otherwise act on.
        self.yaml_popup = StepYamlPopup(self)
        self.table.cellClicked.connect(self._clicked_cell)
        self.table.cellDoubleClicked.connect(self._double_clicked_cell)

        # Expand all / Collapse all.
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self._pointer_timer = QTimer(self)
        self._pointer_timer.setInterval(_POINTER_CHECK_MS)
        self._pointer_timer.timeout.connect(self._check_pointer)

        # The row the panel is open on, and therefore the row the highlight is
        # painted on: -1 for none. One row at a time - the panel shows one step.
        self._active_row = -1
        # Where the click was, in global coordinates: one end of the corridor
        # the pointer may cross to reach the panel.
        self._clicked_at = QPoint()

    # --- Filling ---------------------------------------------------------------

    def show_sequence(
        self, sequence: SequenceSummary, yaml_sources: tuple[StepSource, ...] = ()
    ) -> None:
        """
        One row per step, Result 'Pending', the step id stored in the row.

        `yaml_sources` is one `StepSource` per row, in the same order, from
        `recipe.step_source`. It is optional and may be short: a row without one
        simply has no panel, which is what a recipe the GUI could not read back
        off disk gets.
        """
        self.hide_yaml_popup()
        self.table.setRowCount(len(sequence.steps))
        for row, step in enumerate(sequence.steps):
            name_item = read_only(QTableWidgetItem(step.step_name))
            name_item.setData(Qt.ItemDataRole.UserRole, str(step.step_id))
            name_item.setData(_NAME_ROLE, step.step_name)
            name_item.setData(_DEPTH_ROLE, step.depth)
            name_item.setData(_GROUP_ROLE, step.is_group)
            name_item.setData(_EXPANDED_ROLE, False)
            name_item.setText(_name_text(step.step_name, step.depth, step.is_group, False))
            if row < len(yaml_sources):
                name_item.setData(_YAML_ROLE, yaml_sources[row])
            name_font = name_item.font()
            name_font.setBold(True)
            name_item.setFont(name_font)
            self.table.setItem(row, 0, name_item)

            self.table.setItem(row, 1, read_only(QTableWidgetItem(step.description)))
            self.table.setItem(row, 2, self._pending_item())

        # Every group starts folded.
        self._apply_folding()

        # ResizeToContents keeps the heights right from here on; this one call
        # is for right now, before the table has been laid out and while the
        # stretch column still has its pre-layout width.
        self.table.resizeRowsToContents()

    def clear(self) -> None:
        """No rows at all - the recipe was unloaded."""
        self.hide_yaml_popup()
        self.table.setRowCount(0)

    # --- Folding ---------------------------------------------------------------

    def is_group_row(self, row: int) -> bool:
        item = self.table.item(row, 0)
        return item is not None and bool(item.data(_GROUP_ROLE))

    def is_expanded(self, row: int) -> bool:
        item = self.table.item(row, 0)
        return item is not None and bool(item.data(_EXPANDED_ROLE))

    def set_expanded(self, row: int, expanded: bool) -> None:
        """Unfold or fold one group row. A row that is not a group is left alone."""
        if not self.is_group_row(row):
            return
        self._mark_expanded(row, expanded)
        self._apply_folding()

    def toggle_row(self, row: int) -> None:
        self.set_expanded(row, not self.is_expanded(row))

    def expand_all(self) -> None:
        self._set_all_expanded(True)

    def collapse_all(self) -> None:
        self._set_all_expanded(False)

    def _set_all_expanded(self, expanded: bool) -> None:
        for row in range(self.table.rowCount()):
            if self.is_group_row(row):
                self._mark_expanded(row, expanded)
        self._apply_folding()

    def _mark_expanded(self, row: int, expanded: bool) -> None:
        """The flag and the arrow, which say the same thing."""
        item = self.table.item(row, 0)
        if item is None:
            return
        item.setData(_EXPANDED_ROLE, expanded)
        name = item.data(_NAME_ROLE)
        item.setText(_name_text(name, int(item.data(_DEPTH_ROLE) or 0), True, expanded))

    def _apply_folding(self) -> None:
        """
        Hide every row under a folded group, show every other one.

        One pass down the table: rows are in call-tree order, so a group's rows
        are the ones after it that are deeper than it. After a folded group,
        everything deeper than it is hidden; the first row at its depth or
        shallower ends the fold.
        """
        folded_at: int | None = None
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            depth = 0
            if item is not None:
                depth = int(item.data(_DEPTH_ROLE) or 0)
            if folded_at is not None and depth > folded_at:
                self.table.setRowHidden(row, True)
                continue
            folded_at = None
            self.table.setRowHidden(row, False)
            if self.is_group_row(row) and not self.is_expanded(row):
                folded_at = depth
        if self._active_row >= 0 and self.table.isRowHidden(self._active_row):
            self.hide_yaml_popup()

    def _visible_row_for(self, row: int) -> int:
        """The row itself, or the nearest group above it that is showing."""
        if not self.table.isRowHidden(row):
            return row
        item = self.table.item(row, 0)
        depth = 0
        if item is not None:
            depth = int(item.data(_DEPTH_ROLE) or 0)
        for above in range(row - 1, -1, -1):
            above_item = self.table.item(above, 0)
            if above_item is None:
                continue
            above_depth = int(above_item.data(_DEPTH_ROLE) or 0)
            if above_depth < depth:
                if not self.table.isRowHidden(above):
                    return above
                depth = above_depth
        return row

    def _show_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self.table)
        expand = menu.addAction("Expand all")
        collapse = menu.addAction("Collapse all")
        expand.triggered.connect(lambda _checked=False: self.expand_all())
        collapse.triggered.connect(lambda _checked=False: self.collapse_all())
        menu.exec(self.table.viewport().mapToGlobal(position))

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
        self._pointer_timer.stop()
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
        if column == 0 and self.is_group_row(row):
            # A group's name is its fold control - during a run too.
            self.hide_yaml_popup()
            self.toggle_row(row)
            return
        if self._running:
            log.debug("Step table click on row %d: no panel while a run is in progress.", row)
            self.hide_yaml_popup()
            return
        if column not in _POPUP_COLUMNS:
            self.hide_yaml_popup()
            return
        item = self.table.item(row, 0)
        source = None
        if item is not None:
            source = item.data(_YAML_ROLE)
        if not isinstance(source, StepSource) or not source.text:
            log.debug("Step table click on row %d: no recipe text for this row.", row)
            self.hide_yaml_popup()
            return
        self._highlight_row(row)
        self._clicked_at = QCursor.pos()
        self.yaml_popup.show_for(
            source.text,
            source.first_line,
            source.last_line,
            self._clicked_at.x(),
            self._clicked_at.y(),
        )
        self._pointer_timer.start()
        if source.highlights:
            log.debug(
                "Step table click on row %d: panel shown, lines %d-%d highlighted.",
                row,
                source.first_line,
                source.last_line,
            )
        else:
            log.debug("Step table click on row %d: panel shown, a whole sequence.", row)

    def _double_clicked_cell(self, row: int, column: int) -> None:
        """
        A double-click on a group row folds or unfolds it - once.

        A double-click arrives as a click followed by a double-click. On the name
        the click has already toggled the group, so the double-click adds nothing;
        on the description the click opened the panel, so this closes it and
        toggles.
        """
        if column == 0 or not self.is_group_row(row):
            return
        self.hide_yaml_popup()
        self.toggle_row(row)

    def _check_pointer(self) -> None:
        """The timer's tick: close the panel once the pointer has wandered off."""
        self.pointer_moved_to(QCursor.pos())

    def pointer_moved_to(self, global_position: QPoint) -> None:
        """
        Keep the panel while the pointer is where the gesture allows; close it otherwise.

        Allowed: the clicked row's name and description cells, the panel itself
        - so the wheel can scroll it - and the corridor between where the click
        was and the panel's nearest corner, so the way there does not close it.
        Anything else - another row, the Result column, outside the table -
        ends the gesture, and reading down the table does not drag the panel
        along: the next row has to be clicked in turn.
        """
        if not self.yaml_popup.isVisible() or self._active_row < 0:
            self.hide_yaml_popup()
            return
        if self._row_rect(self._active_row).contains(global_position):
            return
        panel = self.yaml_popup.frameGeometry()
        if panel.contains(global_position):
            return
        if self._corridor(panel).contains(global_position):
            return
        self.hide_yaml_popup()

    def _row_rect(self, row: int) -> QRect:
        """The clicked row's name and description cells, in global coordinates."""
        area = QRect()
        viewport = self.table.viewport()
        for column in _POPUP_COLUMNS:
            item = self.table.item(row, column)
            if item is None:
                continue
            cell = self.table.visualItemRect(item)
            area = area.united(QRect(viewport.mapToGlobal(cell.topLeft()), cell.size()))
        return area

    def _corridor(self, panel: QRect) -> QRect:
        """The box between the click and the panel's corner nearest to it."""
        corner_x = panel.left()
        if self._clicked_at.x() > panel.center().x():
            corner_x = panel.right()
        corner_y = panel.top()
        if self._clicked_at.y() > panel.center().y():
            corner_y = panel.bottom()
        box = QRect(self._clicked_at, QPoint(corner_x, corner_y)).normalized()
        return box.adjusted(-_CORRIDOR_SLACK, -_CORRIDOR_SLACK, _CORRIDOR_SLACK, _CORRIDOR_SLACK)

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
        # A step inside a folded group stays folded: the table follows the run to
        # the group row that is showing instead.
        self.table.scrollToItem(
            self.table.item(self._visible_row_for(row), 0),
            QAbstractItemView.ScrollHint.EnsureVisible,
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
