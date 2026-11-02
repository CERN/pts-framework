"""
PyradeXYGraphWidget: all of pyrade_xy_graph's functionality - live
acquisition, static file loading, plot, signal list, math stats, log - as
a plain QWidget. See the class docstring for why this is a QWidget and
not a QMainWindow, and ui/main_window.py's MainWindow for the standalone
runnable app built on top of it.
"""

import logging
import queue
import uuid
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QInputDialog, QLabel, QMessageBox, QSplitter, QToolBar, QVBoxLayout,
    QWidget,
)

from pyrade_xy_graph.core import export_utils
from pyrade_xy_graph.core.binary_results import FileLoadWorker, RangeLoadWorker
from pyrade_xy_graph.core.data_store import DataStore
from pyrade_xy_graph.core.math_engine import DECIMATION_METHODS
from pyrade_xy_graph.core.live_worker import AcquisitionWorker
from pyrade_xy_graph.ui import style
from pyrade_xy_graph.ui.log_panel import LogPanel
from pyrade_xy_graph.ui.math_dock import MathDockWidget
from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget
from pyrade_xy_graph.ui.signal_tree import SignalTreeWidget

log = logging.getLogger(__name__)


@dataclass
class LiveSession:
    """
    One running live-acquisition pipeline, keyed by session_id in
    PyradeXYGraphWidget.sessions. Returned (by id) from
    start_live_acquisition so the worker/queue feeding a session stay
    reachable afterward.
    """
    session_id: str
    worker: AcquisitionWorker
    data_queue: "queue.Queue | None"


def _titled(title: str, widget: QWidget) -> QWidget:
    """
    Wraps widget with a bold header label above it - a plain-QWidget
    title bar. The header's left padding (QLabel#sectionHeader in
    ui/style.py) matches SignalTreeWidget/MathDockWidget/LogPanel's own
    content margins, so title and content share a left edge.
    """
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    header = QLabel(title)
    header.setObjectName("sectionHeader")
    layout.addWidget(header)
    layout.addWidget(widget)
    return container


class PyradeXYGraphWidget(QWidget):
    """
    All of pyrade_xy_graph's functionality as a plain QWidget, embeddable
    into any host application's own layout, tab, or window.

    Built on QSplitters, not QMainWindow/QDockWidget: an inner
    QMainWindow embedded inside a host that's itself a QMainWindow is a
    known Qt pain point (dock widgets can try to dock against the outer
    window's dock areas). QSplitters give the same fixed layout (Left
    Sidebar: Signals+Math / Main View: plot / Bottom Bar: Log) and nest
    cleanly anywhere.

    See ui/main_window.py's MainWindow for the standalone runnable
    wrapper (what main.py shows) - a thin QMainWindow adding a native
    menu bar built from this widget's own QActions (_build_actions).
    """

    def __init__(self, parent=None, live_max_len: int = 5_000_000, show_legend: bool = False):
        super().__init__(parent)
        # One shared stylesheet for the whole widget tree - cascades to
        # every descendant, including widgets inside SignalTreeWidget's
        # own per-row stylesheets.
        self.setStyleSheet(style.GLOBAL_STYLESHEET)

        self.data_store = DataStore(max_len=live_max_len)
        self.plot_widget = ScopePlotWidget()
        # Off by default: SignalTreeWidget already controls visibility/
        # colour/points/axis per signal, and pyqtgraph's own on-graph
        # legend has an independent click-to-toggle that would bypass
        # it. Pass show_legend=True only when embedding this widget
        # without SignalTreeWidget too.
        self.plot_widget.set_legend_visible(show_legend)

        self.signal_tree = SignalTreeWidget(self.plot_widget)
        self.math_dock = MathDockWidget(self.data_store, self.plot_widget)
        self.log_panel = LogPanel()
        self.log_panel.attach()

        self._build_actions()
        self._build_layout()

        self.data_store.data_updated.connect(self._on_data_updated)

        self.sessions: dict[str, LiveSession] = {}
        self.file_loader: FileLoadWorker | None = None

        # Manual "load detail for visible region" state - see
        # _on_load_visible_detail_dialog.
        self._open_file_path: str | None = None
        self._file_overview: dict[str, tuple] = {}   # channel -> (x, y) at load-time decimation
        self._overview_x_range: tuple[float, float] | None = None
        self._detail_window: dict[str, tuple[float, float]] = {}  # channel -> currently-spliced-in (lo, hi)
        self._range_loaders: dict[str, RangeLoadWorker] = {}       # channel -> in-flight loader

        log.info("PyRade XY Graph ready")

    # ---- layout / actions ----------------------------------------------

    def _build_actions(self):
        """
        QActions built once, independent of any menu/toolbar - a host
        application can add these to its own chrome, since a QAction
        isn't tied to a single widget. The two toolbars below are this
        widget's own always-present chrome.
        """
        def action(text, slot):
            act = QAction(text, self)
            act.triggered.connect(slot)
            return act

        self.action_open_file = action("Open File...", self._on_open_file_dialog)
        self.action_start_acquisition = action("Start Acquisition", self._on_start_acquisition)
        self.action_stop_acquisition = action("Stop Acquisition", lambda: self.stop_live_acquisition())
        self.action_screenshot = action("Screenshot...", self._on_screenshot_dialog)
        self.action_export_data = action("Export Data...", self._on_export_data_dialog)

        self.action_autoscale = action("Autoscale", self.plot_widget.autoscale)
        self.action_set_x_range = action("Set X Range...", self._on_set_x_range_dialog)
        self.action_scope_window = action("Scope Window...", self._on_scope_window_dialog)
        self.action_file_load_decimation = action("File Load Decimation...", self._on_bunching_dialog)
        self.action_load_visible_detail = action(
            "Load Detail for Visible Region...", self._on_load_visible_detail_dialog)
        # Enabled once a file has finished loading (_on_file_load_finished).
        self.action_load_visible_detail.setEnabled(False)

        # Choice-from-a-fixed-list settings are inline toolbar combo
        # boxes rather than a dialog. Free-form numeric entry (X range,
        # scope window, file-load point budget) stays dialog-based.
        self.zoom_mode_combo = self._build_combo(
            [("Pan", "pan"), ("Rectangle Zoom", "rect")], self._on_zoom_mode_combo_changed)
        self.plot_widget.mouse_mode_changed.connect(self._on_plot_mouse_mode_changed)

        self.downsample_method_combo = self._build_combo(
            list(DECIMATION_METHODS), self.plot_widget.set_downsample_method,
            current=self.plot_widget.downsample_method)
        self.plot_widget.downsample_method_changed.connect(self._on_plot_downsample_method_changed)

        self.file_load_decimation_method_combo = self._build_combo(
            list(DECIMATION_METHODS), self._on_file_load_decimation_method_changed,
            current=self.plot_widget.file_load_decimation_method)

        self.nav_toolbar = QToolBar("Navigation", self)
        self.nav_toolbar.setMovable(False)
        self.nav_toolbar.addAction(self.action_open_file)
        self.nav_toolbar.addSeparator()
        self.nav_toolbar.addAction(self.action_start_acquisition)
        self.nav_toolbar.addAction(self.action_stop_acquisition)

        self.tools_toolbar = QToolBar("Tools", self)
        self.tools_toolbar.setMovable(False)
        self.tools_toolbar.addAction(self.action_autoscale)
        self._add_labeled_widget(self.tools_toolbar, "Zoom:", self.zoom_mode_combo)
        self.tools_toolbar.addAction(self.action_set_x_range)
        self.tools_toolbar.addAction(self.action_scope_window)
        self.tools_toolbar.addAction(self.action_file_load_decimation)
        self._add_labeled_widget(self.tools_toolbar, "File Load Decimation:",
                                  self.file_load_decimation_method_combo)
        self._add_labeled_widget(self.tools_toolbar, "Downsample:", self.downsample_method_combo)
        self.tools_toolbar.addAction(self.action_load_visible_detail)
        self.tools_toolbar.addSeparator()
        self.tools_toolbar.addAction(self.action_screenshot)
        self.tools_toolbar.addAction(self.action_export_data)

    @staticmethod
    def _build_combo(items, on_changed, current: str | None = None) -> QComboBox:
        """items: list of str, or (label, data) pairs when the shown
        label differs from the value passed to on_changed (e.g.
        "Rectangle Zoom" -> 'rect'). on_changed(value) fires only on a
        user selection - see _on_plot_mouse_mode_changed/
        _on_plot_downsample_method_changed for the reverse sync
        direction, which sets the combo's index directly instead."""
        combo = QComboBox()
        for entry in items:
            if isinstance(entry, tuple):
                combo.addItem(entry[0], entry[1])
            else:
                combo.addItem(entry, entry)
        if current is not None:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(lambda i: on_changed(combo.itemData(i)))
        return combo

    @staticmethod
    def _add_labeled_widget(toolbar: QToolBar, label: str, widget: QWidget):
        toolbar.addWidget(QLabel(f" {label} "))
        toolbar.addWidget(widget)

    def _build_layout(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.nav_toolbar)
        outer.addWidget(self.tools_toolbar)

        # Left Sidebar: Signals (top, ~70%) + Math (bottom, ~30%).
        sidebar = QSplitter(Qt.Vertical)
        sidebar.addWidget(_titled("Signals", self.signal_tree))
        sidebar.addWidget(_titled("Math", self.math_dock))
        sidebar.setSizes([700, 300])

        # Main content: plot on top, Log below - Log runs only under
        # this column, not under the sidebar too.
        content = QSplitter(Qt.Vertical)
        content.addWidget(self.plot_widget)
        content.addWidget(_titled("Log", self.log_panel))
        content.setSizes([700, 200])

        body = QSplitter(Qt.Horizontal)
        body.addWidget(sidebar)
        body.addWidget(content)
        body.setSizes([300, 900])
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)

        outer.addWidget(body)

    # ---- static file loading ------------------------------------------

    def _on_open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Data File", "", "Supported Files (*.csv *.txt *.h5 *.hdf5 *.tdms)")
        if path:
            self.open_file(path)

    def open_file(self, path: str, target_points_per_channel: int | None = None,
                  decimation_method: str | None = None):
        log.info("Loading file: %s", path)
        self.data_store.clear()
        self.plot_widget.clear_signals()
        # A new file wholesale-replaces the signal set, unlike
        # sync_signals's "briefly absent from one live batch" case.
        self.signal_tree.clear_signals()
        self.math_dock.clear_signals()
        self._reset_file_state(path)

        self.file_loader = FileLoadWorker(
            path, target_points_per_channel=target_points_per_channel or self.plot_widget.target_points,
            decimation_method=decimation_method or self.plot_widget.file_load_decimation_method)
        self.file_loader.chunk_loaded.connect(self._on_file_chunk)
        self.file_loader.channel_unit.connect(self.data_store.set_unit)
        self.file_loader.error.connect(self._on_file_error)
        self.file_loader.finished_all.connect(lambda: self._on_file_load_finished(path))
        self.file_loader.start()

    def _on_file_chunk(self, name: str, x, y):
        x_key = f"{name}#x"
        self.data_store.set_x_key(name, x_key)
        self.data_store.append({x_key: x, name: y})

    def _on_file_error(self, message: str):
        log.error("File load error: %s", message)
        QMessageBox.critical(self, "File load error", message)

    def _on_file_load_finished(self, path: str):
        log.info("Finished loading %s", path)
        # One-shot fit now that the file is loaded - ScopePlotWidget has
        # no sticky auto-range, so without this the view sits at the
        # ViewBox's default (0, 1) range until Autoscale is clicked.
        self.plot_widget.autoscale()

        # Snapshot the just-loaded data as the overview -
        # _on_load_visible_detail_dialog splices higher-resolution reads
        # into this. .copy() because DataStore.get_signal returns
        # zero-copy views that the next replace_signal() call would
        # otherwise mutate.
        overview = {}
        for name in self.data_store.columns:
            if self.data_store.is_x_column(name):
                continue
            x, y = self.data_store.get_signal(name)
            if len(x):
                overview[name] = (x.copy(), y.copy())
        self._file_overview = overview

        xs = [x for x, _y in overview.values()]
        self._overview_x_range = (min(a.min() for a in xs), max(a.max() for a in xs)) if xs else None
        self.action_load_visible_detail.setEnabled(bool(overview))

    def _reset_file_state(self, path: str):
        # RangeLoadWorker has no mid-flight cancellation - clearing
        # self._range_loaders here only forgets them for the "already
        # loading, skip" check below; any still-running thread finishes
        # regardless (see shutdown()).
        self._range_loaders.clear()
        self._detail_window.clear()
        self._file_overview = {}
        self._overview_x_range = None
        self._open_file_path = path
        self.action_load_visible_detail.setEnabled(False)

    # ---- manual "load detail for visible region" -----------------------

    def _on_load_visible_detail_dialog(self):
        if not self._file_overview or self._open_file_path is None:
            return

        x_min, x_max = self.plot_widget.plotItem.vb.viewRange()[0]
        if self._overview_x_range is not None:
            full_lo, full_hi = self._overview_x_range
            x_min = max(x_min, full_lo)
            x_max = min(x_max, full_hi)
        if x_max <= x_min:
            return

        percentage, ok = QInputDialog.getInt(
            self, "Load Detail for Visible Region",
            "Percentage of raw samples in the visible x-range to load\n"
            f"(1-100% - capped at {RangeLoadWorker.HARD_CAP_POINTS:,} points/channel regardless):",
            100, 1, 100)
        if not ok:
            return

        log.info("Loading %d%% detail for visible region [%.6g, %.6g]", percentage, x_min, x_max)
        for name in self._file_overview:
            if name in self._range_loaders:
                continue  # a load for this channel is already in flight

            loader = RangeLoadWorker(self._open_file_path, name, x_min, x_max,
                                      percentage=percentage, parent=self)
            loader.range_loaded.connect(self._on_range_loaded)
            loader.error.connect(self._on_file_error)
            loader.finished.connect(lambda n=name: self._range_loaders.pop(n, None))
            self._range_loaders[name] = loader
            loader.start()

    def _on_range_loaded(self, channel: str, x, y):
        """
        Splices the freshly-read [x_min, x_max] window into the cached
        overview rather than replacing a channel's data outright, so
        zooming back out still shows the complete x-range. Always
        spliced from the untouched _file_overview, not the previous
        splice, so a second load for a different region replaces the
        first window instead of compounding with it.
        """
        if len(x) == 0 or channel not in self._file_overview:
            return
        loader = self.sender()
        lo = loader.x_min if loader is not None else float(x.min())
        hi = loader.x_max if loader is not None else float(x.max())

        ov_x, ov_y = self._file_overview[channel]
        before = ov_x < lo
        after = ov_x > hi
        spliced_x = np.concatenate([ov_x[before], x, ov_x[after]])
        spliced_y = np.concatenate([ov_y[before], y, ov_y[after]])
        self.data_store.replace_signal(channel, f"{channel}#x", spliced_x, spliced_y)
        self._detail_window[channel] = (lo, hi)

    # ---- live acquisition -----------------------------------------------

    def _on_start_acquisition(self):
        self.start_live_acquisition(queue.Queue())

    def start_live_acquisition(self, data_queue: queue.Queue, record_path: str | None = None,
                                worker_class: type[AcquisitionWorker] = AcquisitionWorker,
                                poll_timeout: float = 0.02) -> str:
        """
        Wires DAQ -> AcquisitionWorker -> DataStore via a direct Qt
        signal. Recording (.csv/.txt/.h5/.hdf5/.tdms, or none) happens
        on the worker's own RecorderThread if record_path is given.

        Multiple sessions can run concurrently: each call returns a
        session_id, and self.sessions[session_id] (a LiveSession) keeps
        the worker/data_queue reachable afterward. All sessions feed the
        same shared DataStore - concurrent sessions must use distinct
        column names *and* distinct x-columns (DataStore.set_x_key).
        'Time' is an ordinary column like any other; two sessions both
        defaulting to it would race to append to the same column. Not
        arbitrated here - it's a caller responsibility.

        worker_class: an AcquisitionWorker subclass overriding
        startup()/shutdown() for hardware-specific setup/teardown.

        poll_timeout: passed through to AcquisitionWorker.
        """
        log.info("Starting acquisition%s", f", recording to {record_path}" if record_path else "")

        worker = worker_class(data_queue, record_path=record_path, poll_timeout=poll_timeout)
        worker.data_received.connect(self.data_store.append)
        worker.error.connect(self._on_acquisition_error)

        session_id = uuid.uuid4().hex
        self.sessions[session_id] = LiveSession(session_id=session_id, worker=worker, data_queue=data_queue)

        worker.start()
        # One-shot fit shortly after data starts arriving (see
        # _on_file_load_finished) - not tied to data_updated, which
        # fires per batch and would mean re-fitting on every one.
        QTimer.singleShot(500, self.plot_widget.autoscale)
        return session_id

    def stop_live_acquisition(self, session_id: str | None = None):
        """Stops one session (by id), or every running session if
        session_id is None."""
        if session_id is None:
            for sid in list(self.sessions):
                self._stop_session(sid)
            return
        self._stop_session(session_id)

    def _stop_session(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        log.info("Stopping acquisition %s", session_id)
        # AcquisitionWorker.run()'s finally-clause stops and waits for
        # its RecorderThread before returning, so wait() below implies
        # recording is complete too.
        session.worker.stop()
        session.worker.wait()

    def _on_acquisition_error(self, message: str):
        log.error("Live acquisition error: %s", message)
        QMessageBox.critical(self, "Live acquisition error", message)

    # ---- routing ----------------------------------------------------

    def _on_data_updated(self):
        signal_names = [col for col in self.data_store.columns if not self.data_store.is_x_column(col)]
        log.trace("_on_data_updated: routing %d signals to plot_widget", len(signal_names))
        for name in signal_names:
            x, y = self.data_store.get_signal(name)
            if len(x) and len(y):
                self.plot_widget.update_signal(name, x, y)

        self.signal_tree.sync_signals(signal_names)
        self.math_dock.sync_signals(signal_names)

    # ---- scaling ------------------------------------------------------

    def _on_set_x_range_dialog(self):
        x_min, ok1 = QInputDialog.getDouble(self, "X Range", "Min:", 0.0, -1e18, 1e18, 6)
        if not ok1:
            return
        x_max, ok2 = QInputDialog.getDouble(self, "X Range", "Max:", 1.0, -1e18, 1e18, 6)
        if ok2:
            self.plot_widget.set_x_range(x_min, x_max)

    def _on_scope_window_dialog(self):
        current = self.plot_widget.scope_window or 0.0
        value, ok = QInputDialog.getDouble(
            self, "Scope Window", "Trailing x-window width (0 = show full range):",
            current, 0.0, 1e18, 6)
        if ok:
            self.plot_widget.scope_window = value if value > 0 else None
            log.info("Scope window set to %s", self.plot_widget.scope_window or "full range")

    def _on_bunching_dialog(self):
        value, ok = QInputDialog.getInt(
            self, "File Load Decimation",
            "Target points per channel when opening a file\n"
            "(bounds RAM use for huge files - does not affect live/graph rendering):",
            self.plot_widget.target_points, 10, 1_000_000)
        if ok:
            self.plot_widget.target_points = value
            log.info("File load decimation target set to %d points/channel", value)

    def _on_file_load_decimation_method_changed(self, method: str):
        # No native pyqtgraph equivalent here (unlike downsample method,
        # below) - purely FileLoadWorker's own load-time setting.
        self.plot_widget.file_load_decimation_method = method
        log.info("File load decimation method set to %r", method)

    def _on_plot_downsample_method_changed(self, method: str):
        """Reverse sync: pyqtgraph's native "Downsample" submenu changed
        the method - reflect it in the combo without re-triggering
        set_downsample_method (already applied)."""
        idx = self.downsample_method_combo.findData(method)
        if idx >= 0 and idx != self.downsample_method_combo.currentIndex():
            self.downsample_method_combo.blockSignals(True)
            self.downsample_method_combo.setCurrentIndex(idx)
            self.downsample_method_combo.blockSignals(False)

    def _on_zoom_mode_combo_changed(self, mode: str):
        if mode == 'pan':
            self.plot_widget.set_pan_mode()
        else:
            self.plot_widget.set_rect_zoom_mode()

    def _on_plot_mouse_mode_changed(self, mode: str):
        """Reverse sync: pyqtgraph's native "Mouse Mode" submenu changed
        it - reflect it in the combo without re-triggering
        set_pan_mode()/set_rect_zoom_mode() (already applied)."""
        idx = self.zoom_mode_combo.findData(mode)
        if idx >= 0 and idx != self.zoom_mode_combo.currentIndex():
            self.zoom_mode_combo.blockSignals(True)
            self.zoom_mode_combo.setCurrentIndex(idx)
            self.zoom_mode_combo.blockSignals(False)

    # ---- export ------------------------------------------------------

    def _on_screenshot_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Screenshot", "screenshot.png", "PNG Files (*.png)")
        if path:
            export_utils.save_screenshot(self.plot_widget, path)
            log.info("Saved screenshot to %s", path)

    def _on_export_data_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Raw Data", "export.csv",
            "CSV Files (*.csv);;HDF5 Files (*.h5 *.hdf5);;TDMS Files (*.tdms)")
        if path:
            export_utils.export_signal_data(self.data_store, path)
            log.info("Exported raw data to %s", path)

    # ---- lifecycle ------------------------------------------------------

    def shutdown(self):
        """Stops any running acquisitions/file loads. Call before
        discarding the widget - MainWindow's closeEvent does; a host
        embedding this widget directly should too."""
        self.stop_live_acquisition()
        if self.file_loader is not None and self.file_loader.isRunning():
            self.file_loader.stop()
            self.file_loader.wait()
        # RangeLoadWorker has no stop() - just wait for any still in
        # flight so none outlive the widget.
        for loader in list(self._range_loaders.values()):
            loader.wait()

    def closeEvent(self, event):
        # Only fires if this widget is itself a top-level window - a
        # no-op when embedded, since Qt never delivers QCloseEvent to a
        # child widget.
        self.shutdown()
        super().closeEvent(event)
