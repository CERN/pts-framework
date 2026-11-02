from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QVBoxLayout, QWidget

from pyrade_xy_graph.core.data_store import DataStore
from pyrade_xy_graph.core import math_engine
from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget
from pyrade_xy_graph.ui.style import SPACING

_STAT_ROWS = ('Min', 'Max', 'Average', 'Median', 'Peak-to-peak')


class MathDockWidget(QWidget):
    """
    Shows min/max/average/median/peak-to-peak for one signal, over
    either its whole buffered range (default) or a region dragged on
    the main graph ("Limit to selected region", which shows/hides
    ScopePlotWidget's ROI selector).

    No FFT plot here - use pyqtgraph's own right-click Plot Options >
    Transforms > Power Spectrum on the main graph instead (works for
    left-axis curves; see ScopePlotWidget._add_item_to_axis).
    """

    def __init__(self, data_store: DataStore, plot_widget: ScopePlotWidget, parent=None):
        super().__init__(parent)
        self.data_store = data_store
        self.plot_widget = plot_widget
        self._x_min = 0.0
        self._x_max = 1.0

        layout = QVBoxLayout(self)
        # SPACING matches _titled()'s section header padding (ui/style.py)
        # so "Math" and its content share a left edge.
        layout.setContentsMargins(SPACING, SPACING, SPACING, SPACING)
        layout.setSpacing(SPACING)

        self.signal_combo = QComboBox()
        self.signal_combo.currentTextChanged.connect(self._recompute)
        layout.addWidget(self.signal_combo)

        self.roi_checkbox = QCheckBox("Limit to selected region")
        self.roi_checkbox.setToolTip(
            "Shows a draggable region on the graph and scopes stats to it. "
            "Unchecked (default) computes over the whole buffered signal.")
        self.roi_checkbox.toggled.connect(self._on_roi_toggled)
        layout.addWidget(self.roi_checkbox)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        self._value_labels: dict[str, QLabel] = {}
        for row, stat_name in enumerate(_STAT_ROWS):
            name_label = QLabel(stat_name)
            name_label.setStyleSheet("color: palette(mid);")
            value_label = QLabel("-")
            value_label.setStyleSheet("font-weight: 600; font-family: monospace;")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(name_label, row, 0)
            grid.addWidget(value_label, row, 1)
            self._value_labels[stat_name] = value_label
        layout.addLayout(grid)
        layout.addStretch()

        self.plot_widget.roi_changed.connect(self._on_roi_changed)

        # Debounced: data_updated fires at high frequency during live
        # acquisition, and summary_stats (median especially) isn't free
        # over a multi-million-sample buffer.
        self._recompute_timer = QTimer(self)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.setInterval(200)
        self._recompute_timer.timeout.connect(self._recompute)
        self.data_store.data_updated.connect(self._recompute_timer.start)

    def sync_signals(self, names: list[str]):
        """Adds any name not already in the combo box. Never removes
        entries - see clear_signals() for wholesale replacement."""
        current = self.signal_combo.currentText()
        existing = {self.signal_combo.itemText(i) for i in range(self.signal_combo.count())}
        for name in names:
            if name not in existing:
                self.signal_combo.addItem(name)
        if not current and self.signal_combo.count():
            self.signal_combo.setCurrentIndex(0)

    def clear_signals(self):
        self.signal_combo.clear()
        for label in self._value_labels.values():
            label.setText("-")

    def _on_roi_toggled(self, checked: bool):
        self.plot_widget.toggle_roi(checked)
        self._recompute()

    def _on_roi_changed(self, x_min: float, x_max: float):
        self._x_min, self._x_max = x_min, x_max
        self._recompute()

    def _recompute(self):
        name = self.signal_combo.currentText()
        if not name or name not in self.data_store:
            return

        if self.roi_checkbox.isChecked():
            x_col = self.data_store.get_x_key(name)
            roi = self.data_store.get_roi(self._x_min, self._x_max, x_col=x_col)
            y = roi.get(name)
        else:
            y = self.data_store[name]

        if y is None or len(y) == 0:
            return

        stats = math_engine.summary_stats(y)
        unit = self.data_store.get_unit(name)
        suffix = f" {unit}" if unit else ""
        for label, key in zip(_STAT_ROWS, ('min', 'max', 'average', 'median', 'peak_to_peak')):
            self._value_labels[label].setText(f"{stats[key]:.6g}{suffix}")
