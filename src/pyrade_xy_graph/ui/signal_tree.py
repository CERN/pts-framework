import logging

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget
from pyrade_xy_graph.ui.style import SPACING

log = logging.getLogger(__name__)

# Hover highlight, and a stronger highlight for rows selected for bulk
# editing (see _set_selected) - the plain-QWidget equivalent of a native
# list view's row styling.
_ROW_STYLE = """
QWidget#signalRow {
    border-radius: 4px;
}
QWidget#signalRow:hover {
    background: palette(midlight);
}
QWidget#signalRow[selected="true"] {
    background: palette(highlight);
}
"""

# Click-to-select (SignalTreeWidget._on_row_clicked) uses
# QObject.installEventFilter() on plain QWidget/QLabel instances rather
# than subclassing with a custom mousePressEvent: a Python QWidget
# subclass, even an empty one, stops that widget's own QSS ":hover" rule
# from repainting under PySide6, while underMouse() still reports True
# correctly. Filtering events on SignalTreeWidget itself (which doesn't
# need :hover styling) avoids the problem.


class SignalTreeWidget(QWidget):
    """
    Per-signal show/hide + point-style + colour controls. Reads/writes
    ScopePlotWidget's curve objects directly; never touches DataStore.

    Every control is reachable two ways: the row's own checkboxes/colour
    swatch, and a right-click context menu (points markers, 2nd axis,
    change colour) - both drive the same checkbox state.

    Rows are multi-selectable by clicking - file-explorer style: a plain
    click selects only that row, Ctrl/Cmd+click toggles one row in/out,
    Shift+click selects the range between the last click and this one
    (see _on_row_clicked). Distinct from "Visible", which is about
    what's drawn, not what's selected for editing. Right-clicking a
    selected row while 2+ are selected opens a bulk context menu
    (_build_bulk_context_menu) applying Show/Hide/point-markers/axis/
    colour to every selected signal at once.
    """
    visibility_changed = Signal(str, bool)

    def __init__(self, plot_widget: ScopePlotWidget, parent=None):
        super().__init__(parent)
        self.plot_widget = plot_widget
        self._rows: dict[str, dict] = {}
        self._selected: set[str] = set()
        self._last_clicked: str | None = None  # shift-click range-select anchor
        self._click_targets: dict[QObject, str] = {}  # QObject -> signal name, for eventFilter

        outer_layout = QVBoxLayout(self)
        # SPACING matches _titled()'s section header padding (ui/style.py)
        # so "Signals" and its content share a left edge.
        outer_layout.setContentsMargins(SPACING, SPACING, SPACING, SPACING)
        outer_layout.setSpacing(SPACING)

        select_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_visible(True))
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self._set_all_visible(False))
        select_row.addWidget(select_all_btn)
        select_row.addWidget(deselect_all_btn)
        select_row.addStretch()
        outer_layout.addLayout(select_row)

        # Rows scroll independently of the sidebar's own size - with many
        # signals this must not force the dock (and the main plot next to
        # it) to keep growing/shrinking to fit every row.
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll_area)

        rows_container = QWidget()
        self._layout = QVBoxLayout(rows_container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.addStretch()
        scroll_area.setWidget(rows_container)

    def _set_all_visible(self, visible: bool):
        for row in self._rows.values():
            row['visible_box'].setChecked(visible)  # triggers _on_visibility_toggled per row

    def sync_signals(self, names: list[str]):
        """Adds a row for any name not already tracked. Never removes
        rows on its own - see clear_signals() for wholesale replacement
        (a new file load)."""
        for name in names:
            if name not in self._rows:
                self._add_row(name)

    def clear_signals(self):
        """Removes every row."""
        for name in list(self._rows):
            row_data = self._rows.pop(name)
            row = row_data['row']
            self._click_targets.pop(row, None)
            self._click_targets.pop(row_data['name_label'], None)
            self._layout.removeWidget(row)
            row.deleteLater()
        self._selected.clear()
        self._last_clicked = None

    def _add_row(self, name: str):
        row = QWidget(self)
        row.setObjectName("signalRow")
        row.setStyleSheet(_ROW_STYLE)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 3, 4, 3)
        row_layout.setSpacing(6)

        visible_box = QCheckBox()
        visible_box.setChecked(True)
        visible_box.setToolTip("Show/hide this signal on the plot")
        visible_box.toggled.connect(lambda checked, n=name: self._on_visibility_toggled(n, checked))

        # Click-to-select target, separate from visible_box (which must
        # keep toggling visibility on click) - see the class docstring
        # and _on_row_clicked.
        name_label = QLabel(name)
        name_label.setCursor(Qt.PointingHandCursor)

        points_box = QCheckBox("●")  # a filled circle glyph reads as "point marker" without an abbreviation
        points_box.setToolTip("Show point markers")
        points_box.toggled.connect(lambda checked, n=name: self._on_points_toggled(n, checked))

        # Opt-in per signal: the plot supports a second, independently-
        # scaled Y axis, but that doesn't mean every signal should be on
        # one - unchecked (default) keeps a signal on the shared left axis.
        axis_box = QCheckBox("2nd axis")
        axis_box.setToolTip("Move this signal to its own secondary Y axis")
        axis_box.toggled.connect(lambda checked, n=name: self._on_axis_toggled(n, checked))

        color_btn = QPushButton()
        color_btn.setFixedSize(16, 16)
        color_btn.setCursor(Qt.PointingHandCursor)
        color_btn.setToolTip("Click to change colour")
        style = self.plot_widget.styles.get(name)
        color = style.color if style else "#dddddd"
        self._style_color_swatch(color_btn, color)
        color_btn.clicked.connect(lambda _, n=name, btn=color_btn: self._on_color_clicked(n, btn))

        row_layout.addWidget(visible_box)
        row_layout.addWidget(name_label, stretch=1)
        row_layout.addWidget(color_btn)
        row_layout.addWidget(points_box)
        row_layout.addWidget(axis_box)

        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(lambda pos, n=name, r=row: self._show_context_menu(n, r, pos))

        # Both the row's own background and the name label select the
        # row - see the module-level comment on installEventFilter.
        row.installEventFilter(self)
        name_label.installEventFilter(self)
        self._click_targets[row] = name
        self._click_targets[name_label] = name

        # insert before the trailing stretch
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._rows[name] = {
            'row': row, 'name_label': name_label, 'visible_box': visible_box,
            'points_box': points_box, 'color_btn': color_btn, 'axis_box': axis_box,
        }

    def eventFilter(self, obj, event):
        # Left-button presses only: treating a right-click as a plain
        # select-only-this-row click would collapse a multi-selection
        # before _show_context_menu can offer the bulk menu.
        if (event.type() == QEvent.Type.MouseButtonPress and obj in self._click_targets
                and event.button() == Qt.MouseButton.LeftButton):
            self._on_row_clicked(self._click_targets[obj], event)
        return super().eventFilter(obj, event)

    @staticmethod
    def _style_color_swatch(btn: QPushButton, hex_color: str):
        btn.setStyleSheet(
            f"background-color: {hex_color}; border: 1px solid palette(mid); border-radius: 3px;")

    def _build_context_menu(self, name: str) -> QMenu:
        """
        Same actions the row's own checkboxes/colour swatch expose; each
        drives the same checkbox (QAction.toggled -> QCheckBox.setChecked).

        Split from _show_context_menu (which execs this and blocks)
        so construction/wiring is testable without a blocking call.
        """
        row_data = self._rows[name]
        menu = QMenu(self)

        visible_action = QAction("Visible", menu)
        visible_action.setCheckable(True)
        visible_action.setChecked(row_data['visible_box'].isChecked())
        visible_action.toggled.connect(row_data['visible_box'].setChecked)
        menu.addAction(visible_action)

        points_action = QAction("Show Point Markers", menu)
        points_action.setCheckable(True)
        points_action.setChecked(row_data['points_box'].isChecked())
        points_action.toggled.connect(row_data['points_box'].setChecked)
        menu.addAction(points_action)

        axis_action = QAction("2nd Y Axis", menu)
        axis_action.setCheckable(True)
        axis_action.setChecked(row_data['axis_box'].isChecked())
        axis_action.toggled.connect(row_data['axis_box'].setChecked)
        menu.addAction(axis_action)

        menu.addSeparator()
        color_action = QAction("Change Colour...", menu)
        color_action.triggered.connect(
            lambda: self._on_color_clicked(name, row_data['color_btn']))
        menu.addAction(color_action)

        return menu

    def _build_bulk_context_menu(self, names: list[str]) -> QMenu:
        """
        The multi-signal equivalent of _build_context_menu - plain
        (non-checkable) actions rather than one toggle each, since
        selected rows can already be in different states (some visible,
        some not).
        """
        menu = QMenu(self)
        header = menu.addAction(f"{len(names)} signals selected")
        header.setEnabled(False)
        menu.addSeparator()

        show_action = QAction("Show", menu)
        show_action.triggered.connect(lambda: self._bulk_set_visible(names, True))
        menu.addAction(show_action)
        hide_action = QAction("Hide", menu)
        hide_action.triggered.connect(lambda: self._bulk_set_visible(names, False))
        menu.addAction(hide_action)

        menu.addSeparator()
        points_on = QAction("Show Point Markers", menu)
        points_on.triggered.connect(lambda: self._bulk_set_points(names, True))
        menu.addAction(points_on)
        points_off = QAction("Hide Point Markers", menu)
        points_off.triggered.connect(lambda: self._bulk_set_points(names, False))
        menu.addAction(points_off)

        menu.addSeparator()
        axis_2nd = QAction("Move to 2nd Y Axis", menu)
        axis_2nd.triggered.connect(lambda: self._bulk_set_axis(names, True))
        menu.addAction(axis_2nd)
        axis_left = QAction("Move to Left Axis", menu)
        axis_left.triggered.connect(lambda: self._bulk_set_axis(names, False))
        menu.addAction(axis_left)

        menu.addSeparator()
        color_action = QAction("Change Colour...", menu)
        color_action.triggered.connect(lambda: self._bulk_change_color(names))
        menu.addAction(color_action)

        menu.addSeparator()
        clear_action = QAction("Clear Selection", menu)
        clear_action.triggered.connect(self._clear_selection)
        menu.addAction(clear_action)

        return menu

    def _show_context_menu(self, name: str, row: QWidget, pos):
        # A right-click on a row that's part of a multi-selection acts
        # on the whole selection; otherwise falls back to that row's
        # own menu.
        if name in self._selected and len(self._selected) > 1:
            menu = self._build_bulk_context_menu(sorted(self._selected))
        else:
            menu = self._build_context_menu(name)
        menu.exec(row.mapToGlobal(pos))

    def _on_row_clicked(self, name: str, event):
        """File-explorer-style click-to-select: plain click selects only
        this row, Ctrl/Cmd+click toggles it in/out (Qt maps Cmd-click to
        ControlModifier on macOS), Shift+click selects the range between
        the last click and this one."""
        modifiers = event.modifiers()
        names = list(self._rows)  # visual top-to-bottom order == insertion order

        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._last_clicked in names:
            lo, hi = sorted((names.index(self._last_clicked), names.index(name)))
            for n in list(self._selected):
                if n not in names[lo:hi + 1]:
                    self._set_selected(n, False)
            for n in names[lo:hi + 1]:
                self._set_selected(n, True)
            return  # deliberately doesn't move the range-select anchor

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._set_selected(name, name not in self._selected)
        else:
            for n in list(self._selected):
                if n != name:
                    self._set_selected(n, False)
            self._set_selected(name, True)
        self._last_clicked = name

    def _set_selected(self, name: str, selected: bool):
        if selected:
            self._selected.add(name)
        else:
            self._selected.discard(name)
        row = self._rows[name]['row']
        # Dynamic property + re-polish is how a QSS selector like
        # [selected="true"] (_ROW_STYLE) picks up a runtime change.
        row.setProperty("selected", selected)
        row.style().unpolish(row)
        row.style().polish(row)

    def _bulk_set_visible(self, names: list[str], visible: bool):
        for n in names:
            self._rows[n]['visible_box'].setChecked(visible)  # triggers _on_visibility_toggled per row

    def _bulk_set_points(self, names: list[str], checked: bool):
        for n in names:
            self._rows[n]['points_box'].setChecked(checked)

    def _bulk_set_axis(self, names: list[str], second: bool):
        for n in names:
            self._rows[n]['axis_box'].setChecked(second)

    def _bulk_change_color(self, names: list[str]):
        color = QColorDialog.getColor(Qt.white, self, f"Colour for {len(names)} signals")
        if not color.isValid():
            return
        hex_color = color.name()
        log.debug("bulk signal colour: %r -> %s", names, hex_color)
        for n in names:
            self._style_color_swatch(self._rows[n]['color_btn'], hex_color)
            self.plot_widget.set_style(n, color=hex_color)

    def _clear_selection(self):
        for n in list(self._selected):
            self._set_selected(n, False)

    def _on_visibility_toggled(self, name: str, checked: bool):
        log.debug("signal visibility: %r -> %s", name, checked)
        self.plot_widget.set_visible(name, checked)
        self.visibility_changed.emit(name, checked)

    def _on_points_toggled(self, name: str, checked: bool):
        log.debug("signal point markers: %r -> %s", name, checked)
        self.plot_widget.set_style(name, symbol='o' if checked else None)

    def _on_axis_toggled(self, name: str, checked: bool):
        log.debug("signal 2nd-axis toggle: %r -> %s", name, checked)
        self.plot_widget.set_signal_axis(name, 'right' if checked else 'left')

    def _on_color_clicked(self, name: str, btn: QPushButton):
        style = self.plot_widget.styles.get(name)
        initial = style.color if style else "#dddddd"
        color = QColorDialog.getColor(initial, self, f"Colour for {name}")
        if color.isValid():
            hex_color = color.name()
            log.debug("signal colour: %r -> %s", name, hex_color)
            self._style_color_swatch(btn, hex_color)
            self.plot_widget.set_style(name, color=hex_color)
