import logging
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QLabel

from pyrade_xy_graph.core import trace_level  # noqa: F401  (registers Logger.trace())
from pyrade_xy_graph.core.math_engine import DECIMATION_METHODS

log = logging.getLogger(__name__)

# Colorblind-safe categorical palette for a white-background plot.
# Ordering is the CVD-safety mechanism - assign in this fixed order,
# never re-sorted or cycled per-use. A signal count beyond 8 wraps back
# to slot 1 rather than refusing new signals; colors past 8 aren't
# guaranteed distinguishable.
DEFAULT_COLORS = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]


@dataclass
class SignalStyle:
    color: str = "#dddddd"
    width: float = 2.0   # line width in px
    symbol: str | None = None   # None = no point markers, else pyqtgraph symbol code ('o', 't', etc)
    visible: bool = True


class ScopePlotWidget(pg.PlotWidget):
    """
    PyQtGraph widget for DataStore array streaming. Supports an arbitrary
    number of independently-scaled Y axes, a trailing scope window, ROI
    selection (for MathDockWidget), and pan/rect zoom modes.

    Render-cost bunching is delegated to pyqtgraph's own curve
    downsampling (`PlotDataItem.setClipToView`/`setDownsampling`) - see
    `downsample_method` below.
    """
    roi_changed = Signal(float, float)
    # Fire on mouse-mode / downsample-method changes from either this
    # widget's own toolbar (set_pan_mode() etc.) or pyqtgraph's native
    # right-click menu, so other UI (e.g. a toolbar combo box) can stay in
    # sync regardless of which one the user touched. mouse_mode_changed
    # carries 'pan' or 'rect'; downsample_method_changed carries one of
    # DECIMATION_METHODS.
    mouse_mode_changed = Signal(str)
    downsample_method_changed = Signal(str)

    def __init__(self, parent=None, target_points: int = 4000):
        super().__init__(parent)
        self.plotItem.setClipToView(True)
        self.plotItem.showGrid(x=True, y=True, alpha=0.3)
        # pyqtgraph's ViewBox defaults to sticky auto-range (re-fitting the
        # view on every curve update), which fights every explicit
        # range-setting path this widget has (autoscale(), set_x_range(),
        # scope window, "load detail for visible region"). Every range
        # change here is explicit instead - see those methods.
        self.plotItem.vb.disableAutoRange()
        # pyqtgraph's Transforms checkboxes (FFT/log/derivative/phase-map)
        # change a curve's domain and cache a clipToView-clipped display
        # dataset against the pre-toggle view range, which nothing
        # invalidates afterward - the transformed curve renders as a
        # near-empty sliver until the next pan/zoom. An explicit one-shot
        # autoRange() after each toggle forces a fresh, correctly-ranged read.
        for _check_name in ('fftCheck', 'logXCheck', 'logYCheck', 'derivativeCheck', 'phasemapCheck'):
            getattr(self.plotItem.ctrl, _check_name).toggled.connect(
                lambda *_: self.plotItem.vb.autoRange())

        # Sync source for mouse_mode_changed: fires on both this widget's
        # own set_pan_mode()/set_rect_zoom_mode() and pyqtgraph's native
        # "Mouse Mode" menu, since both ultimately call
        # ViewBox.setMouseMode(), which emits sigStateChanged either way.
        # The downsample-side equivalent is wired up below, once
        # downsample_method exists.
        self.plotItem.vb.sigStateChanged.connect(self._on_viewbox_state_changed)
        self._last_mouse_mode = self.plotItem.vb.state['mouseMode']
        # No on-graph legend: SignalTreeWidget already shows each signal's
        # name and color, and the crosshair readout below shows name+value
        # at the point being examined. pyqtgraph's legend also has its own
        # click-to-toggle-visibility that would fall out of sync with
        # SignalTreeWidget if both were shown.

        # File-load RAM budget only (see FileLoadWorker/core.math_engine.decimate):
        # a multi-GB file is decimated once at load time to roughly this
        # many points per channel so it's never materialized whole in
        # memory. Not used for render-time decimation - see downsample_method.
        self.target_points = target_points
        # 'peak' (default, min+max per bin), 'mean', or 'subsample' - see
        # core.math_engine.decimate. A FileLoadWorker construction
        # parameter, unrelated to the render-time downsample_method below.
        self.file_load_decimation_method = 'peak'
        # pyqtgraph's downsampling vocabulary:
        #   'peak'      - min+max per pixel column (transient-preserving)
        #   'mean'      - averages per pixel column (smoother, hides spikes)
        #   'subsample' - every Nth raw sample (cheapest, can alias)
        # Viewport-aware: recomputed against the visible x-range and pixel
        # width on every redraw (via clipToView + autoDownsampleFactor), so
        # zooming in reveals more of the buffered resolution instead of
        # being capped at a fixed point budget.
        self.downsample_method = 'peak'
        # Applied through PlotItem.setDownsampling() - see
        # set_downsample_method's docstring for why this, not each curve's
        # own setDownsampling(), is the single source of truth - so every
        # left-axis curve added from here on inherits it automatically via
        # PlotItem.addItem().
        self.plotItem.setDownsampling(auto=True, mode=self.downsample_method)
        # Sync source for downsample_method_changed, mirroring the
        # mouse-mode wiring above. Wired up here rather than earlier
        # because _on_native_downsample_changed reads self.downsample_method.
        for _radio_name in ('peakRadio', 'meanRadio', 'subsampleRadio'):
            getattr(self.plotItem.ctrl, _radio_name).toggled.connect(self._on_native_downsample_changed)
        # None = show the full buffered range; else a trailing window
        # width in x-units, so the plot "follows" like a scope.
        self.scope_window: float | None = None

        self.curves: dict[str, pg.PlotDataItem] = {}
        self.styles: dict[str, SignalStyle] = {}
        self.axis_of: dict[str, str] = {}
        # Off by default - see set_legend_visible.
        self._legend: pg.LegendItem | None = None

        self._extra_axes: dict[str, dict] = {}
        self._next_axis_col = 3  # PlotItem layout: 0=left axis,1=viewbox,2=(unused right slot)
        self._color_index = 0

        self.plotItem.vb.sigResized.connect(self._sync_extra_axes)

        # ROI region (for MathDockWidget's stats selection)
        self.roi = pg.LinearRegionItem(values=[0, 1], orientation='vertical')
        self.roi.setZValue(10)
        self.roi.setVisible(False)
        self.addItem(self.roi)
        self.roi.sigRegionChanged.connect(self._on_roi_moved)

        self._setup_crosshair()

    def _setup_crosshair(self):
        """
        Hover crosshair snapped to the nearest data point, with an
        exact-value readout pinned to the graph's bottom-right corner.
        Prefers curves with point markers enabled (SignalStyle.symbol set,
        i.e. SignalTreeWidget's "show point markers" toggle) when any are
        visible; otherwise falls back to the nearest visible curve overall.
        """
        # Solid, high-contrast, on top of curves/grid - a thin grey dash
        # was easy to lose against the grid lines on a white background.
        pen = pg.mkPen(color="#e03131", width=1)
        self._crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self._crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        self._crosshair_v.setZValue(1000)
        self._crosshair_h.setZValue(1000)
        self._crosshair_v.setVisible(False)
        self._crosshair_h.setVisible(False)
        self.addItem(self._crosshair_v, ignoreBounds=True)
        self.addItem(self._crosshair_h, ignoreBounds=True)

        self._value_readout = QLabel(self)
        self._value_readout.setStyleSheet(
            "background-color: rgba(255, 255, 255, 220); border: 1px solid #888; "
            "padding: 2px 6px; font-family: monospace;")
        self._value_readout.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._value_readout.hide()

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def mouseMoveEvent(self, event):
        """
        Second, independent trigger for the crosshair, alongside
        scene().sigMouseMoved (connected in _setup_crosshair) - a hedge
        against pyqtgraph's GraphicsScene mouse-move signal occasionally
        not firing on some macOS/PySide6 setups. Harmless if
        sigMouseMoved already works: _update_crosshair just runs twice
        with the same position that frame.
        """
        super().mouseMoveEvent(event)
        try:
            pos = event.position() if hasattr(event, 'position') else event.localPos()
            self._update_crosshair(self.mapToScene(pos.toPoint()))
        except Exception:
            log.exception("crosshair update failed (mouseMoveEvent path)")

    def _on_mouse_moved(self, scene_pos):
        try:
            self._update_crosshair(scene_pos)
        except Exception:
            # Log and keep going instead of leaving the crosshair
            # permanently inert after one bad frame (e.g. a curve mid-update).
            log.exception("crosshair update failed")

    def _update_crosshair(self, scene_pos):
        if not self.plotItem.vb.sceneBoundingRect().contains(scene_pos):
            self._crosshair_v.setVisible(False)
            self._crosshair_h.setVisible(False)
            self._value_readout.hide()
            return

        mouse_x = self.plotItem.vb.mapSceneToView(scene_pos).x()
        nearest = self._find_nearest_point(mouse_x)
        if nearest is None:
            self._crosshair_v.setVisible(False)
            self._crosshair_h.setVisible(False)
            self._value_readout.hide()
            return

        name, x, y = nearest
        self._crosshair_v.setPos(x)
        self._crosshair_h.setPos(y)
        self._crosshair_v.setVisible(True)
        self._crosshair_h.setVisible(True)

        self._value_readout.setText(f"{name}  x={x:.6g}  y={y:.6g}")
        self._value_readout.adjustSize()
        self._reposition_readout()
        self._value_readout.show()

    def _find_nearest_point(self, mouse_x: float):
        """Nearest-by-x data point among visible curves (any axis),
        point-marker-enabled curves preferred over plain lines when both exist.

        Uses item.xData/.yData (the raw, un-clipped dataset), not
        item.getData() (pyqtgraph's display dataset, clipped to the
        current view range whenever clipToView is on and auto-range is
        off - see __init__), so snapping finds the true nearest sample
        regardless of clip/downsample state or whether the view has been
        re-fit since the last zoom/pan."""
        with_points = []
        without_points = []
        for name, item in self.curves.items():
            if not item.isVisible():
                continue
            x_data, y_data = item.xData, item.yData
            if x_data is None or len(x_data) == 0:
                continue
            idx = int(np.searchsorted(x_data, mouse_x))
            idx = min(idx, len(x_data) - 1)
            if idx > 0 and abs(x_data[idx - 1] - mouse_x) < abs(x_data[idx] - mouse_x):
                idx -= 1
            candidate = (name, float(x_data[idx]), float(y_data[idx]))
            (with_points if self.styles[name].symbol is not None else without_points).append(candidate)

        pool = with_points or without_points
        if not pool:
            return None
        return min(pool, key=lambda c: abs(c[1] - mouse_x))

    def _reposition_readout(self):
        # Anchored to the plotting area's own corner (the ViewBox), not
        # the whole widget: the widget's total height also includes the
        # x-axis tick-label row below the ViewBox, and anchoring against
        # that put the readout on top of the axis labels instead of
        # sitting cleanly inside the graph.
        margin = 8
        vb_bottom_right = self.mapFromScene(self.plotItem.vb.sceneBoundingRect().bottomRight())
        x = vb_bottom_right.x() - self._value_readout.width() - margin
        y = vb_bottom_right.y() - self._value_readout.height() - margin
        self._value_readout.move(max(0, int(x)), max(0, int(y)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_value_readout'):
            self._reposition_readout()

    # ---- axes -----------------------------------------------------

    def add_y_axis(self, name: str, label: str | None = None, units: str | None = None,
                    color: str = "#dddddd"):
        """Adds an independently-scaled Y axis. 'left' (the plot's own
        default axis) always exists; call this for every additional one."""
        if name == 'left' or name in self._extra_axes:
            return

        axis_item = pg.AxisItem('right')
        axis_item.setPen(color)
        axis_item.setTextPen(color)
        if label:
            axis_item.setLabel(label, units=units)

        view_box = pg.ViewBox()
        view_box.disableAutoRange()  # see the matching call/comment in __init__
        self.plotItem.layout.addItem(axis_item, 2, self._next_axis_col)
        self._next_axis_col += 1
        self.plotItem.scene().addItem(view_box)
        axis_item.linkToView(view_box)
        view_box.setXLink(self.plotItem.vb)

        self._extra_axes[name] = {'view_box': view_box, 'axis_item': axis_item}
        self._sync_extra_axes()

    def _view_box_for(self, axis_name: str) -> pg.ViewBox:
        if axis_name == 'left':
            return self.plotItem.vb
        return self._extra_axes[axis_name]['view_box']

    def _add_item_to_axis(self, item: pg.PlotDataItem, axis: str):
        """
        For 'left' (the common case), items go through PlotItem.addItem()
        rather than the raw ViewBox, since that registers the item into
        PlotItem.curves and applies the current ctrl-menu state - without
        it, the item renders but is invisible to the legend and to every
        right-click Plot Options control (Transforms, Downsample, Average,
        Alpha, Points).

        For a secondary axis this doesn't apply: pyqtgraph's multi-axis
        recipe adds items straight to an independent ViewBox that
        PlotItem doesn't own, so those items are outside its ctrl menu's
        reach, legend included. Accepted limitation of that recipe.
        """
        if axis == 'left':
            self.plotItem.addItem(item)
        else:
            self._view_box_for(axis).addItem(item)

    def _remove_item_from_axis(self, item: pg.PlotDataItem, axis: str):
        if axis == 'left':
            self.plotItem.removeItem(item)
        else:
            self._view_box_for(axis).removeItem(item)

    def _sync_extra_axes(self):
        """Keeps every extra ViewBox's screen geometry glued to the main
        one on resize/pan/zoom - the standard pyqtgraph multi-axis recipe."""
        main_vb = self.plotItem.vb
        for info in self._extra_axes.values():
            info['view_box'].setGeometry(main_vb.sceneBoundingRect())
            info['view_box'].linkedViewChanged(main_vb, info['view_box'].XAxis)

    def set_left_label(self, text: str, units: str | None = None, color: str | None = None):
        style = {'color': color} if color else {}
        self.plotItem.setLabel('left', text, units=units, **style)

    # ---- curves -----------------------------------------------------

    @staticmethod
    def _make_pen(style: SignalStyle) -> pg.QtGui.QPen:
        """Round join/cap - pg.mkPen doesn't expose these directly, so
        set them on the QPen it returns."""
        pen = pg.mkPen(color=style.color, width=style.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def add_signal(self, name: str, axis: str = 'left', style: SignalStyle | None = None):
        if name in self.curves:
            return
        if style is None:
            style = SignalStyle(color=DEFAULT_COLORS[self._color_index % len(DEFAULT_COLORS)])
            self._color_index += 1
        self.styles[name] = style
        self.axis_of[name] = axis

        # symbolSize=8: minimum readable marker size.
        item = pg.PlotDataItem(pen=self._make_pen(style), symbol=style.symbol, symbolSize=8,
                                symbolBrush=style.color, symbolPen=pg.mkPen('w', width=1), name=name)
        item.setVisible(style.visible)
        self._add_item_to_axis(item, axis)
        # Left-axis items already get downsampling for free from
        # _add_item_to_axis's PlotItem.addItem() call, which applies
        # PlotItem's current ctrl state to every newly added item.
        # Secondary-axis items bypass PlotItem.addItem() entirely and
        # need it applied here directly.
        self._apply_downsampling(item, axis)
        self.curves[name] = item
        log.debug("add_signal: %r on axis=%r color=%s", name, axis, style.color)

    def _apply_downsampling(self, item: pg.PlotDataItem, axis: str = 'left'):
        if axis == 'left':
            # PlotItem.addItem() (via _add_item_to_axis) already applies
            # the current ctrl-menu state. Not setting the item's own
            # setDownsampling()/setClipToView() here keeps PlotItem's
            # state the single source of truth - see set_downsample_method.
            return
        # Secondary-axis curves bypass PlotItem.addItem() entirely (see
        # _add_item_to_axis), so this is the only way to reach them - the
        # same structural gap documented for the native Transforms menu
        # and exporters (test_secondary_axis_curves_are_invisible_to_native_exporters).
        item.setClipToView(True)
        item.setDownsampling(auto=True, method=self.downsample_method)

    def set_legend_visible(self, visible: bool):
        """
        Opt-in on-graph legend (pyqtgraph's PlotItem.addLegend()) - off by
        default because its click-to-toggle-visibility behavior falls out
        of sync with SignalTreeWidget if both are shown. PyradeXYGraphWidget
        keeps this off since it always has its own SignalTreeWidget; turn
        it on when embedding ScopePlotWidget standalone with no signal
        list of its own.

        Only registers 'left'-axis curves: secondary-axis curves bypass
        PlotItem entirely (see _add_item_to_axis) and are invisible to
        its legend for the same reason they're invisible to the
        right-click Transforms menu and native exporters.
        """
        if self._legend is None:
            if not visible:
                return
            self._legend = self.plotItem.addLegend()
            for name, item in self.curves.items():
                if self.axis_of.get(name) == 'left':
                    self._legend.addItem(item, name)
        self._legend.setVisible(visible)

    def set_downsample_method(self, method: str):
        """
        Changes the render-time downsampling method for every existing
        (and subsequently added) curve. method: 'peak', 'mean', or
        'subsample' - see downsample_method's docstring in __init__.

        Left-axis curves go through PlotItem.setDownsampling() - the
        mechanism pyqtgraph's native "Downsample" submenu also drives -
        rather than each curve's own setDownsampling(). PlotItem.addItem()
        re-applies its own ctrl-menu state to every item added afterward
        regardless, and that same state drives the native submenu, so
        setting curves directly would leave PlotItem's state stale: the
        native menu wouldn't reflect this call, and touching the menu
        could silently revert it. Routing through PlotItem.setDownsampling()
        keeps the two as one shared state instead of two copies that can
        drift apart.

        Secondary-axis curves aren't reachable through PlotItem (see
        _add_item_to_axis) and are set directly.

        Does not set self.downsample_method directly -
        _on_native_downsample_changed does, as a side effect of the
        setDownsampling() call below synchronously toggling
        ctrl.peakRadio/etc, the same path a native-menu change takes.
        Setting it here first would make that handler's "did this
        actually change" check always see no change and skip emitting
        downsample_method_changed.
        """
        if method not in DECIMATION_METHODS:
            raise ValueError(f"Unknown downsample method: {method!r} (expected one of {DECIMATION_METHODS})")
        self.plotItem.setDownsampling(auto=True, mode=method)
        for name, item in self.curves.items():
            if self.axis_of.get(name) != 'left':
                item.setDownsampling(auto=True, method=method)

    def update_signal(self, name: str, x: np.ndarray, y: np.ndarray, axis: str = 'left'):
        if name not in self.curves:
            self.add_signal(name, axis=axis)

        if self.scope_window is not None and len(x) > 0:
            x_max = x[-1]
            mask = x >= (x_max - self.scope_window)
            x, y = x[mask], y[mask]

        # Full (scope-window-filtered) resolution goes straight to
        # pyqtgraph; render-cost bunching happens inside PlotDataItem
        # itself (setDownsampling/setClipToView, set in add_signal) so it
        # stays viewport-aware rather than a fixed budget applied up front.
        log.trace("update_signal: %r %d points handed to pyqtgraph", name, len(x))
        self.curves[name].setData(x, y)

    def set_visible(self, name: str, visible: bool):
        if name in self.curves:
            self.curves[name].setVisible(visible)
            self.styles[name].visible = visible

    def set_style(self, name: str, *, color: str | None = None, width: float | None = None,
                  symbol: str | None = ...):
        """symbol: pass None explicitly to remove point markers, or omit
        (Ellipsis default) to leave the current symbol unchanged."""
        if name not in self.curves:
            return
        style = self.styles[name]
        if color is not None:
            style.color = color
        if width is not None:
            style.width = width
        if symbol is not ...:
            style.symbol = symbol

        self.curves[name].setPen(self._make_pen(style))
        self.curves[name].setSymbol(style.symbol)
        self.curves[name].setSymbolBrush(style.color)
        self.curves[name].setSymbolPen(pg.mkPen('w', width=1))

    def set_signal_axis(self, name: str, axis: str):
        """
        Moves an existing signal to a different Y axis (e.g. 'left' -> a
        secondary axis, to normalize its scale against very
        differently-scaled signals). Per-signal: every other signal stays
        where it was.
        """
        if name not in self.curves or self.axis_of.get(name) == axis:
            return
        if axis != 'left' and axis not in self._extra_axes:
            self.add_y_axis(axis)

        item = self.curves[name]
        log.debug("set_signal_axis: %r %r -> %r", name, self.axis_of[name], axis)

        # clipToView (set on every 'left'-axis curve by PlotItem.addItem)
        # makes PlotDataItem._getDisplayDataset() call
        # self.getViewBox().autoRangeEnabled() on every view change.
        # Mid-reparent (removeItem -> addItem below), getViewBox() briefly
        # resolves to no ViewBox; its fallback returns the
        # GraphicsView/PlotWidget itself, which has no autoRangeEnabled()
        # method, and pyqtgraph calls it anyway from inside a Qt
        # itemChange() callback - an uncaught AttributeError that leaves
        # the item stuck mid-move (data disappears and doesn't come back).
        # Toggling clipToView off for the move sidesteps that; a left-axis
        # landing gets it restored for free by _add_item_to_axis's
        # PlotItem.addItem() call below, and _apply_downsampling handles
        # the secondary-axis case.
        item.setClipToView(False)
        self._remove_item_from_axis(item, self.axis_of[name])
        self._add_item_to_axis(item, axis)
        self._apply_downsampling(item, axis)
        self.axis_of[name] = axis

        # A not-yet-ranged ViewBox keeps its default (0, 1) range until
        # something explicitly fits it to its contents; moving a curve in
        # doesn't trigger that on its own, so it would render outside the
        # visible range and appear to vanish. A one-shot autoRange() (not
        # enableAutoRange(), which turns on the sticky re-fit mode this
        # widget keeps off elsewhere - see __init__) fits the range once
        # without leaving that mode on.
        target_vb = self._view_box_for(axis)
        target_vb.autoRange()

    def remove_signal(self, name: str):
        if name not in self.curves:
            return
        self._remove_item_from_axis(self.curves[name], self.axis_of[name])
        del self.curves[name]
        del self.styles[name]
        del self.axis_of[name]

    # ---- scaling / interaction ---------------------------------------

    def autoscale(self):
        """
        Fits the shared X range and each axis's Y range to the currently
        visible curves only - explicit and one-shot, computed directly
        from each curve's data (`.xData`/`.yData`, the full-resolution
        series regardless of downsample_method - see update_signal). A
        hidden signal never contributes to the fitted range; an axis with
        nothing visible on it is left where it was.
        """
        x_min, x_max = self._visible_bounds(lambda name: self.curves[name].xData)
        if x_min is not None:
            self.plotItem.setXRange(x_min, x_max, padding=0.02)

        self._autoscale_y('left')
        for axis_name in self._extra_axes:
            self._autoscale_y(axis_name)

    def _visible_bounds(self, get_array, *, names=None):
        lo = hi = None
        for name in (names if names is not None else self.curves):
            item = self.curves[name]
            if not item.isVisible():
                continue
            arr = get_array(name)
            if arr is None or len(arr) == 0:
                continue
            arr_lo, arr_hi = float(np.min(arr)), float(np.max(arr))
            lo = arr_lo if lo is None else min(lo, arr_lo)
            hi = arr_hi if hi is None else max(hi, arr_hi)
        return lo, hi

    def _autoscale_y(self, axis_name: str):
        names_on_axis = [name for name, axis in self.axis_of.items() if axis == axis_name]
        y_min, y_max = self._visible_bounds(lambda name: self.curves[name].yData, names=names_on_axis)
        if y_min is None:
            return  # nothing currently visible on this axis - leave its range alone
        if y_min == y_max:
            # Flat or single-value data has zero span - padding has
            # nothing to scale from, so give it explicit headroom.
            pad = abs(y_min) * 0.1 or 1.0
            y_min, y_max = y_min - pad, y_max + pad
        self._view_box_for(axis_name).setYRange(y_min, y_max, padding=0.05)

    def set_x_range(self, x_min: float, x_max: float):
        self.plotItem.setXRange(x_min, x_max, padding=0)

    def set_y_range(self, y_min: float, y_max: float, axis: str = 'left'):
        self._view_box_for(axis).setYRange(y_min, y_max, padding=0)

    def set_pan_mode(self):
        self.plotItem.vb.setMouseMode(pg.ViewBox.PanMode)
        for info in self._extra_axes.values():
            info['view_box'].setMouseMode(pg.ViewBox.PanMode)

    def set_rect_zoom_mode(self):
        self.plotItem.vb.setMouseMode(pg.ViewBox.RectMode)
        for info in self._extra_axes.values():
            info['view_box'].setMouseMode(pg.ViewBox.RectMode)

    def _on_viewbox_state_changed(self, _view_box):
        # Driven by setMouseMode() above or pyqtgraph's native "Mouse
        # Mode" submenu - both call ViewBox.setMouseMode(), which emits
        # sigStateChanged either way, so this is one shared trigger for both.
        mode = self.plotItem.vb.state['mouseMode']
        if mode != self._last_mouse_mode:
            self._last_mouse_mode = mode
            self.mouse_mode_changed.emit('pan' if mode == pg.ViewBox.PanMode else 'rect')

    def _on_native_downsample_changed(self, checked: bool):
        if not checked:
            return  # exclusive radio group - only react to the one that became checked
        _, _, method = self.plotItem.downsampleMode()
        if method != self.downsample_method:
            self.downsample_method = method
            self.downsample_method_changed.emit(method)

    # ---- ROI (math window selection) ----------------------------------

    def toggle_roi(self, visible: bool):
        self.roi.setVisible(visible)
        if visible:
            self._on_roi_moved()

    def get_roi_bounds(self) -> tuple[float, float]:
        return self.roi.getRegion()

    def _on_roi_moved(self):
        if self.roi.isVisible():
            x_min, x_max = self.roi.getRegion()
            self.roi_changed.emit(x_min, x_max)

    def clear_signals(self):
        """
        Named distinctly from pyqtgraph's clear(): PlotWidget.__init__
        does setattr(self, 'clear', self.plotItem.clear), an instance
        attribute that would shadow a same-named subclass method (instance
        __dict__ wins over class methods), so a clear() override here
        would never run.
        """
        self.clear()
        for info in self._extra_axes.values():
            info['view_box'].clear()
        self.curves.clear()
        self.styles.clear()
        self.axis_of.clear()
