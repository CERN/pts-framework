"""
The XY graph of one stream, drawn live or from a finished file.

`StreamGraph` is a widget around the copied `pyrade_xy_graph` plot. It shows one
stream CSV at a time (see `pypts.stream_handler`): `show_live()` follows a file
that is still being written, polling it on a timer; `show_static()` draws a
finished file once. Per stream name it keeps a `StreamReader` and a bounded
`DataStore`, so switching to another stream and back neither re-reads the file
nor loses the points already drawn.

The glue upstream keeps in its own graph widget (store -> plot) is written here:
the shown store's `data_updated` redraws the curve, and each tick appends its new
rows as one record, so there is one repaint per tick.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

from pypts.hmi.gui.palette import get_palette
from pypts.hmi.gui.stream_reader import StreamReader, read_whole_stream
from pyrade_xy_graph.core.data_store import DataStore
from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget

logger = logging.getLogger(__name__)

#: Points kept per stream; older ones drop out of the store.
MAX_POINTS = 100_000
#: How often the shown live stream's file is polled.
POLL_INTERVAL_MS = 50


class _StreamState:
    """What is kept per stream: its store, its reader (live only), the unit seen."""

    def __init__(self, store: DataStore, reader: StreamReader | None) -> None:
        self.store = store
        self.reader = reader
        self.unit: str | None = None


class StreamGraph(QWidget):
    """One stream's XY graph, with a waiting message until its file exists."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = False
        self._live: dict[str, _StreamState] = {}
        self._static: _StreamState | None = None
        self._shown: _StreamState | None = None
        self._shown_name: str | None = None
        self._waiting = False

        self._plot = ScopePlotWidget(self)
        self._waiting_label = QLabel(self)
        self._waiting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._waiting_label.setWordWrap(True)

        self._pages = QStackedLayout(self)
        self._pages.setContentsMargins(0, 0, 0, 0)
        self._pages.addWidget(self._plot)
        self._pages.addWidget(self._waiting_label)
        self._pages.setCurrentWidget(self._plot)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

        self.set_dark(False)

    # --- the interface ----------------------------------------------------

    def show_live(self, name: str, csv_path: Path) -> None:
        """Show stream `name`, following `csv_path` on the timer."""
        state = self._live.get(name)
        replaced = None
        if state is not None and state.reader is not None and state.reader.path != Path(csv_path):
            replaced = state
            state = None
        if state is None:
            state = _StreamState(self._new_store(name), StreamReader(csv_path))
            self._live[name] = state
        self._switch_to(name, state)
        if replaced is not None:
            self._release(replaced)
        self._tick()
        self._timer.start()

    def show_static(self, name: str, csv_path: Path) -> bool:
        """Draw the whole file once, no polling. False when the file does not exist."""
        whole = read_whole_stream(csv_path)
        if whole is None:
            return False
        unit, xs, ys = whole
        self._timer.stop()
        state = _StreamState(self._new_store(name), None)
        state.unit = unit
        replaced = self._static
        self._static = state
        self._switch_to(name, state)
        if replaced is not None:
            self._release(replaced)
        if len(xs):
            state.store.append({self._x_key(name): xs, name: ys})
            self._autoscale()
        return True

    def stop(self) -> None:
        """Timer off, nothing shown. The per-stream state is kept."""
        self._timer.stop()
        self._disconnect_shown()
        self._clear_plot()
        self._shown = None
        self._shown_name = None
        if self._static is not None:
            self._release(self._static)
            self._static = None
        self._set_waiting(False)

    def forget_run(self) -> None:
        """`stop()`, and drop every per-stream reader and store."""
        self.stop()
        for state in self._live.values():
            self._release(state)
        self._live.clear()

    def is_waiting(self) -> bool:
        """Whether the shown live stream's file has not appeared yet."""
        return self._waiting

    def shown_name(self) -> str | None:
        return self._shown_name

    def set_dark(self, dark: bool) -> None:
        """
        Colour this plot from the palette. The copied widget sets no global
        pyqtgraph colours, so everything is set here, on this widget only.
        """
        self._dark = dark
        palette = get_palette(dark)
        plot = self._plot
        plot.setBackground(palette.table_background)
        for axis_name in ("left", "bottom"):
            axis = plot.getAxis(axis_name)
            axis.setPen(palette.text_muted)
            axis.setTextPen(palette.text)
        plot._crosshair_v.setPen(palette.danger)
        plot._crosshair_h.setPen(palette.danger)
        plot._value_readout.setStyleSheet(
            f"background-color: {palette.panel_background}; color: {palette.text}; "
            f"border: 1px solid {palette.border}; "
            "padding: 2px 6px; font-family: monospace;"
        )
        self._waiting_label.setStyleSheet(
            f"color: {palette.text_muted}; background-color: {palette.table_background};"
        )
        self._apply_label()

    # --- internals --------------------------------------------------------

    @staticmethod
    def _x_key(name: str) -> str:
        # The stream's own name is the y column; keep the x column apart from it.
        if name == "x":
            return "x_axis"
        return "x"

    def _new_store(self, name: str) -> DataStore:
        store = DataStore(parent=self, max_len=MAX_POINTS)
        store.set_x_key(name, self._x_key(name))
        return store

    @staticmethod
    def _release(state: _StreamState) -> None:
        """
        Let go of a stream's state for good: close its reader and free its
        store. The store is a child of this widget, so while it has that
        parent it - and its buffers - live as long as the widget. Unparented,
        it belongs to Python and goes with the last reference, which the
        caller is dropping; the caller has already switched away from it.

        Not deleteLater(): on a store holding data, PySide6 6.9 raises
        KeyError(0) calling it - the copied DataStore defines __len__ and
        __getitem__, and the binding takes it for a sequence.
        """
        if state.reader is not None:
            state.reader.close()
        state.store.setParent(None)

    def _clear_plot(self) -> None:
        """
        Remove the curves. The copied widget's clear_signals() clears the whole
        plot item, which also drops the crosshair lines, so they are put back.
        """
        self._plot.clear_signals()
        self._plot.addItem(self._plot._crosshair_v, ignoreBounds=True)
        self._plot.addItem(self._plot._crosshair_h, ignoreBounds=True)

    def _disconnect_shown(self) -> None:
        if self._shown is not None:
            try:
                self._shown.store.data_updated.disconnect(self._on_data_updated)
            except (RuntimeError, TypeError):
                logger.debug("Stream graph: store was not connected")

    def _switch_to(self, name: str, state: _StreamState) -> None:
        self._disconnect_shown()
        self._clear_plot()
        self._shown = state
        self._shown_name = name
        state.store.data_updated.connect(self._on_data_updated)
        self._apply_label()
        self._on_data_updated()
        self._autoscale()
        if state.reader is not None:
            self._set_waiting(not state.reader.exists)
        else:
            self._set_waiting(False)

    def _set_waiting(self, waiting: bool) -> None:
        self._waiting = waiting
        if waiting:
            self._waiting_label.setText(f"Waiting for stream {self._shown_name}")
            self._pages.setCurrentWidget(self._waiting_label)
        else:
            self._pages.setCurrentWidget(self._plot)

    def _apply_label(self) -> None:
        if self._shown is None or self._shown_name is None:
            return
        self._plot.set_left_label(
            self._shown_name, units=self._shown.unit, color=get_palette(self._dark).text
        )

    def _on_data_updated(self) -> None:
        if self._shown is None or self._shown_name is None:
            return
        xs, ys = self._shown.store.get_signal(self._shown_name)
        if len(xs) and len(ys):
            self._plot.update_signal(self._shown_name, xs, ys)

    def _autoscale(self) -> None:
        if self._plot.curves:
            self._plot.autoscale()

    def _tick(self) -> None:
        state = self._shown
        name = self._shown_name
        if state is None or name is None or state.reader is None:
            return
        xs, ys = state.reader.poll()
        if state.reader.unit != state.unit:
            state.unit = state.reader.unit
            self._apply_label()
        if self._waiting and state.reader.exists:
            self._set_waiting(False)
        if len(xs):
            state.store.append({self._x_key(name): xs, name: ys})
            self._autoscale()
