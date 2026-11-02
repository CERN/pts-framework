"""Unit tests for the XY graph widget (src/pypts/hmi/gui/stream_graph.py), offscreen."""

import gc
import weakref
from pathlib import Path

import pytest

from pypts.hmi.gui import stream_graph
from pypts.hmi.gui.stream_graph import StreamGraph


@pytest.fixture
def graph(qtbot):
    widget = StreamGraph()
    qtbot.addWidget(widget)
    yield widget
    widget.forget_run()


def write_rows(path: Path, first: int, count: int, header: str | None = "x,y") -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        if header is not None:
            handle.write(header + "\n")
        for i in range(first, first + count):
            handle.write(f"{i},{i * 2}\n")


def curve_x(graph: StreamGraph, name: str):
    return graph._plot.curves[name].xData


def test_live_waits_then_draws(graph, qtbot, tmp_path):
    path = tmp_path / "sine.csv"
    graph.show_live("sine", path)
    assert graph.is_waiting()
    assert graph.shown_name() == "sine"
    assert graph._waiting_label.text() == "Waiting for stream sine"
    write_rows(path, 0, 5)
    qtbot.waitUntil(lambda: not graph.is_waiting())
    qtbot.waitUntil(lambda: "sine" in graph._plot.curves)
    assert list(curve_x(graph, "sine")) == [0, 1, 2, 3, 4]


def test_live_appends_new_rows(graph, qtbot, tmp_path):
    path = tmp_path / "sine.csv"
    write_rows(path, 0, 3)
    graph.show_live("sine", path)
    assert len(curve_x(graph, "sine")) == 3
    write_rows(path, 3, 4, header=None)
    qtbot.waitUntil(lambda: len(curve_x(graph, "sine")) == 7)


def test_store_is_bounded_by_max_points(graph, monkeypatch, tmp_path):
    monkeypatch.setattr(stream_graph, "MAX_POINTS", 50)
    path = tmp_path / "sine.csv"
    write_rows(path, 0, 200)
    graph.show_live("sine", path)
    xs = curve_x(graph, "sine")
    assert len(xs) <= 50
    assert xs[-1] == 199


def test_switching_back_to_a_stream_does_not_reread(graph, tmp_path):
    path_a = tmp_path / "a.csv"
    path_b = tmp_path / "b.csv"
    write_rows(path_a, 0, 4)
    write_rows(path_b, 0, 2)
    graph.show_live("a", path_a)
    reader_a = graph._live["a"].reader
    graph.show_live("b", path_b)
    assert list(curve_x(graph, "b")) == [0, 1]
    graph.show_live("a", path_a)
    assert graph._live["a"].reader is reader_a
    assert list(curve_x(graph, "a")) == [0, 1, 2, 3]
    assert graph.shown_name() == "a"


def test_static_draws_whole_file_once(graph, tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, 0, 6)
    assert graph.show_static("s", path) is True
    assert len(curve_x(graph, "s")) == 6
    assert not graph._timer.isActive()
    assert graph.show_static("gone", tmp_path / "gone.csv") is False


def test_forget_run_drops_state(graph, tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, 0, 3)
    graph.show_live("s", path)
    graph.forget_run()
    assert graph._live == {}
    assert graph.shown_name() is None
    assert not graph.is_waiting()
    assert not graph._timer.isActive()


def test_stop_keeps_state(graph, tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, 0, 3)
    graph.show_live("s", path)
    graph.stop()
    assert "s" in graph._live
    assert graph.shown_name() is None
    assert not graph._timer.isActive()


def test_axis_label_carries_unit(graph, tmp_path):
    path = tmp_path / "v.csv"
    write_rows(path, 0, 3, header="x,y [V]")
    graph.show_live("v", path)
    axis = graph._plot.getAxis("left")
    assert "V" in (axis.labelText or "") + (axis.labelUnits or "")


def test_dark_theme_colours_the_readout(graph):
    graph.set_dark(True)
    assert "color: #f0f0f0" in graph._plot._value_readout.styleSheet()
    graph.set_dark(False)
    assert "color: #1a1a2e" in graph._plot._value_readout.styleSheet()


def test_curve_is_a_child_of_the_plot_view_box(graph, tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, 0, 5)
    graph.show_live("s", path)
    curve = graph._plot.curves["s"]
    assert curve.parentItem() is not None
    assert curve in graph._plot.plotItem.vb.childGroup.childItems()


def stores_alive(graph: StreamGraph) -> int:
    """DataStore children of the graph once deferred deletes have run."""
    from PySide6.QtCore import QCoreApplication, QEvent

    from pyrade_xy_graph.core.data_store import DataStore

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return len(graph.findChildren(DataStore))


def test_dropped_stores_are_deleted(graph, tmp_path):
    path = tmp_path / "sine.csv"
    write_rows(path, 0, 5)
    other = tmp_path / "other.csv"
    write_rows(other, 0, 5)

    assert graph.show_static("sine", path)
    first_store = weakref.ref(graph._static.store)
    for _ in range(4):
        assert graph.show_static("sine", path)
    assert stores_alive(graph) <= 1, "each look-back replaces the static store"
    gc.collect()
    assert first_store() is None, "a replaced store is freed, not only unparented"

    graph.stop()
    assert stores_alive(graph) == 0

    for _ in range(3):
        graph.show_live("sine", path)
        graph.show_live("sine", other)  # the same name on another file replaces its store
        graph.forget_run()
    assert stores_alive(graph) == 0


def test_nan_row_does_not_break_live_or_static(graph, qtbot, tmp_path):
    path = tmp_path / "sine.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("x,y\n0,0\nnan,1\n1,inf\n2,4\n")
    graph.show_live("sine", path)
    assert list(curve_x(graph, "sine")) == [0, 2]
    assert graph.show_static("sine", path) is True
    assert list(curve_x(graph, "sine")) == [0, 2]


def test_crosshair_survives_switching_streams(graph, tmp_path):
    path = tmp_path / "sine.csv"
    write_rows(path, 0, 3)
    graph.show_live("sine", path)
    other = tmp_path / "cos.csv"
    write_rows(other, 0, 3)
    graph.show_live("cos", other)
    graph.show_static("cos", other)
    for line in (graph._plot._crosshair_v, graph._plot._crosshair_h):
        assert line.scene() is not None
