"""
Unit tests for the HAL monitor's window (src/pyhal/monitor/window.py).

Each test runs a HalServer in threads of the test process, on a free port, with real driver
processes, as test_pyhal_monitor_link.py does; raw sockets stand in for the other clients.
The window runs offscreen (tests/conftest.py). Every test closes its window and waits for the
window's worker threads, so nothing is left running.
"""

import logging
import multiprocessing
import os
import socket
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer

from pyhal import connection_driver
from pyhal.monitor import __main__ as monitor_main
from pyhal.monitor import window as window_module
from pyhal.monitor.window import MonitorWindow
from pyhal.protocol import codec, messages
from pyhal.server import HalServer

LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"
WAIT_MS = 20000


class Client:
    """One raw connection: reads the first message (hello) at once, then lines on request."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.stream = self.sock.makefile("rb")
        self.hello = self.receive()

    def receive(self):
        line = codec.read_line(self.stream)
        if line is None:
            return None
        return codec.decode(line, messages.HAL_KINDS)

    def request(self, kind: str, **fields):
        message = messages.build(messages.CLIENT_KINDS, kind, **fields)
        self.sock.sendall(codec.encode(message))
        return self.receive()

    def beat(self) -> None:
        """One `beat`: from then on the HAL counts this connection as a client."""
        self.sock.sendall(codec.encode(messages.Beat()))

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def _stop(hal: HalServer) -> None:
    """Stop a server with a shutdown, unless it has exited already."""
    if not hal._exited.is_set():
        try:
            client = Client(hal.port)
            if isinstance(client.hello, messages.Hello):
                client.request("shutdown")
            client.close()
        except OSError:
            pass
    waiter = threading.Thread(target=hal.serve_until_stopped)
    waiter.start()
    waiter.join(timeout=120)
    assert not waiter.is_alive(), "the HAL server did not exit"


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _wait_for_status(spare: Client, condition, seconds: float = 10.0) -> messages.StatusReport:
    """Poll `status` on a spare connection until condition(report) holds: sync on the wire."""
    deadline = time.monotonic() + seconds
    while True:
        report = spare.request("status")
        assert isinstance(report, messages.StatusReport)
        if condition(report):
            return report
        assert time.monotonic() < deadline, f"status never matched: {report}"
        time.sleep(0.02)


def _wait_for_connections(hal: HalServer, count: int, seconds: float = 10.0) -> None:
    """Wait until the HAL has `count` connections: it has seen the others go."""
    deadline = time.monotonic() + seconds
    while True:
        with hal._lock:
            connections = len(hal._connections)
        if connections == count:
            return
        assert time.monotonic() < deadline, f"the HAL still has {connections} connection(s)"
        time.sleep(0.02)


def _marking_bench(tmp_path: Path) -> tuple[str, Path]:
    marks = tmp_path / "marks.txt"
    text = (
        f"[loop1]\ndriver = {LOOPBACK}\n"
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\ntag = m1\n"
        f"[m2]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\ntag = m2\n"
    )
    return text, marks


def _table(window: MonitorWindow) -> dict[str, list[str]]:
    """The devices table: name -> [device type, state, last error]."""
    rows: dict[str, list[str]] = {}
    table = window.devices_table
    for row in range(table.rowCount()):
        cells = [table.item(row, column).text() for column in range(table.columnCount())]
        rows[cells[0]] = cells[1:]
    return rows


@pytest.fixture
def start_hal(tmp_path):
    """start_hal(bench_text, port=0, **options) -> a started HalServer; stopped afterwards."""
    started: list[HalServer] = []

    def start(bench_text: str = f"[loop1]\ndriver = {LOOPBACK}\n", port: int = 0, **options):
        bench = tmp_path / "bench.ini"
        bench.write_text(bench_text, encoding="utf-8")
        hal = HalServer(bench, port, **options)
        hal.start()
        started.append(hal)
        return hal

    yield start
    for hal in started:
        _stop(hal)
    assert multiprocessing.active_children() == []
    left = [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("HAL ") and thread.is_alive()
    ]
    assert left == []


@pytest.fixture
def make_window(qtbot):
    """make_window(port, bench=None) -> a shown MonitorWindow; closed and waited for after."""
    windows: list[MonitorWindow] = []

    def make(port: int, bench: str | None = None) -> MonitorWindow:
        window = MonitorWindow(port, bench=bench)
        qtbot.addWidget(window)
        window.show()
        windows.append(window)
        return window

    yield make
    for window in windows:
        window.close()
        assert window.wait_for_workers(30), "a worker of the window did not end"


def test_the_window_shows_the_hal_and_its_devices(start_hal, make_window, qtbot, tmp_path):
    bench_text, _marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text, log_path="C:/logs/hal.log")
    other = Client(hal.port)
    assert isinstance(other.request("open", device="m1"), messages.Opened)
    window = make_window(hal.port)
    assert window.windowTitle() == f"HAL monitor \N{EM DASH} 127.0.0.1:{hal.port}"
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    # A HAL in threads of the test process reports the test process's pid.
    assert window.pid_label.text() == str(os.getpid())
    assert window.version_label.text() == messages.hal_version()
    assert window.bench_label.text() == str((tmp_path / "bench.ini").resolve())
    assert window.log_label.text() == "C:/logs/hal.log"
    # The monitor's own connection is not counted.
    assert window.clients_label.text() == "1"
    assert window.activity_label.text() == "idle"
    assert window.queued_label.text() == "0"
    assert window.refreshed_label.text() != ""
    report = other.request("status")
    expected = {
        row["name"]: [row["device_type"], row["state"], row["last_error"] or ""]
        for row in report.devices
    }
    assert _table(window) == expected
    assert [cells[1] for cells in expected.values()] == ["configured", "open", "configured"]
    # The table fills the window's width: the last column takes what the others leave.
    table = window.devices_table
    widths = sum(table.columnWidth(column) for column in range(table.columnCount()))
    assert widths >= table.viewport().width() - 2
    assert table.columnWidth(3) > table.columnWidth(0)
    assert window.close_all_button.isEnabled()
    assert window.stop_button.isEnabled()
    assert not window.start_button.isEnabled()
    other.close()


def test_the_window_shows_not_reachable_and_offers_start(
    start_hal, make_window, qtbot, tmp_path, monkeypatch
):
    port = _free_port()
    bench = tmp_path / "bench.ini"
    bench.write_text(f"[loop1]\ndriver = {LOOPBACK}\n", encoding="utf-8")
    started: list[tuple[str, int]] = []

    def start_in_threads(bench_path, start_port, **options):
        started.append((str(bench_path), start_port))
        start_hal(port=start_port)
        return 4242

    monkeypatch.setattr(window_module.client, "start_hal", start_in_threads)
    window = make_window(port, bench=str(bench))
    qtbot.waitUntil(lambda: window.state_label.text() == "not reachable", timeout=WAIT_MS)
    assert not window.close_all_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.start_button.isEnabled()
    assert str(bench) in window.start_button.toolTip()
    assert _table(window) == {}
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    assert started == [(str(bench), port)]
    assert "4242" in window.statusBar().currentMessage()
    assert _table(window) == {"loop1": ["", "configured", ""]}
    assert not window.start_button.isEnabled()


def test_start_is_disabled_without_a_bench(make_window, qtbot):
    window = make_window(_free_port())
    qtbot.waitUntil(lambda: window.state_label.text() == "not reachable", timeout=WAIT_MS)
    assert not window.start_button.isEnabled()
    assert window.start_button.toolTip() == "No bench file: start the monitor with --bench FILE"


def test_closing_the_window_leaves_the_bench_alone(start_hal, qtbot, tmp_path):
    bench_text, marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text)
    spare = Client(hal.port)
    assert isinstance(spare.request("open", device="m1"), messages.Opened)
    window = MonitorWindow(hal.port)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    # The window's poll asks only `status`: the HAL counts spare alone.
    assert spare.request("status").clients == 1
    _wait_for_connections(hal, 2)
    window.close()
    assert window.wait_for_workers(30)
    # Once the HAL has seen the monitor go, every line it sent has been taken: a close_all
    # or shutdown it sent would be queued before the `info` below.
    _wait_for_connections(hal, 1)
    info = spare.request("info", device="m1")
    assert info.is_open is True
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect m1"]
    spare.close()


def test_close_all_asks_first_and_shows_the_result(
    start_hal, make_window, qtbot, tmp_path, monkeypatch
):
    monkeypatch.setattr(connection_driver, "RESCUE_TIMEOUT_S", 1.0)
    bench_text, marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text, call_timeout_s=1.0)
    other = Client(hal.port)
    assert isinstance(other.request("open", device="m1"), messages.Opened)
    assert isinstance(other.request("open", device="m2"), messages.Opened)
    Path(str(marks) + ".tdhang.m2").write_text("", encoding="utf-8")
    questions: list[str] = []
    answers = [False, True]
    warnings: list[str] = []

    def confirm(parent, title, text):
        questions.append(text)
        return answers.pop(0)

    def warn(parent, title, text):
        warnings.append(text)

    monkeypatch.setattr(window_module, "confirm", confirm)
    monkeypatch.setattr(window_module, "warn", warn)
    window = make_window(hal.port)
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    # Answered No: nothing is sent.
    qtbot.mouseClick(window.close_all_button, Qt.MouseButton.LeftButton)
    assert len(questions) == 1
    assert "Every open device is torn down, also those of other clients." in questions[0]
    assert window.close_all_button.isEnabled()
    assert other.request("info", device="m1").is_open is True
    # Answered Yes.
    qtbot.mouseClick(window.close_all_button, Qt.MouseButton.LeftButton)
    assert len(questions) == 2
    qtbot.waitUntil(lambda: warnings != [], timeout=60000)
    assert "m2" in warnings[0]
    assert "Not torn down: m2" in window.statusBar().currentMessage()
    assert "teardown m1" in marks.read_text(encoding="utf-8").splitlines()
    qtbot.waitUntil(lambda: _table(window)["m1"][1] == "configured", timeout=WAIT_MS)
    assert window.close_all_button.isEnabled()
    other.close()


def test_actions_do_not_block_the_gui(start_hal, make_window, qtbot, monkeypatch):
    hal = start_hal()
    other = Client(hal.port)
    assert isinstance(other.request("open", device="loop1"), messages.Opened)
    answers: list = []

    def sleep_call():
        call = messages.Call(device="loop1", operation="sleep", args=[2.0], kwargs={})
        other.sock.sendall(codec.encode(call))
        answers.append(other.receive())

    sleeper = threading.Thread(target=sleep_call)
    sleeper.start()
    monkeypatch.setattr(window_module, "confirm", lambda parent, title, text: True)
    monkeypatch.setattr(window_module, "warn", lambda parent, title, text: None)
    window = make_window(hal.port)
    qtbot.waitUntil(lambda: window.state_label.text() == "busy", timeout=WAIT_MS)
    assert window.activity_label.text().startswith("running sleep on loop1 since ")
    ticks: list[float] = []
    ticker = QTimer()
    ticker.setInterval(50)
    ticker.timeout.connect(lambda: ticks.append(time.monotonic()))
    ticker.start()
    try:
        qtbot.mouseClick(window.close_all_button, Qt.MouseButton.LeftButton)
        # The click returned at once; the action runs on a worker.
        assert not window.close_all_button.isEnabled()
        assert "Closing all devices" in window.statusBar().currentMessage()
        qtbot.waitUntil(
            lambda: "Every device was torn down." in window.statusBar().currentMessage(),
            timeout=WAIT_MS,
        )
    finally:
        ticker.stop()
    sleeper.join(30)
    assert isinstance(answers[0], messages.Result)
    # The close_all waited behind the 2 s sleep while the event loop kept turning.
    assert len(ticks) >= 10
    assert window.close_all_button.isEnabled()
    other.close()


def _record(handle, level: str, message: str) -> None:
    handle.write(f"2026-11-23 10:00:00.000;{level};pyhal;{message}\n")


def test_the_log_view_shows_new_records_and_filters_by_level(
    start_hal, make_window, qtbot, tmp_path
):
    log_file = tmp_path / "hal.log"
    log_file.write_text("", encoding="utf-8")
    hal = start_hal(log_path=str(log_file))
    window = make_window(hal.port)
    qtbot.waitUntil(lambda: window.tailed_log == str(log_file), timeout=WAIT_MS)
    with open(log_file, "a", encoding="utf-8") as handle:
        _record(handle, "DEBUG", "a debug line")
        _record(handle, "INFO", "an info line")
        _record(handle, "WARNING", "a warning line")
        _record(handle, "ERROR", "an error line")
        _record(handle, "INFO", "the last line")
    qtbot.waitUntil(lambda: "the last line" in window.log_view.toPlainText(), timeout=WAIT_MS)
    # INFO by default.
    assert window.level_filter.currentText() == "INFO"
    lines = window.log_view.toPlainText().splitlines()
    assert [line.split(" ", 1)[1] for line in lines] == [
        "INFO an info line",
        "WARNING a warning line",
        "ERROR an error line",
        "INFO the last line",
    ]
    assert len(lines[0].split(" ", 1)[0]) == len("10:00:00")
    html = window.log_view.document().toHtml()
    assert window_module.AMBER in html
    assert window_module.RED in html
    window.level_filter.setCurrentText("WARNING")
    assert [line.split(" ", 1)[1] for line in window.log_view.toPlainText().splitlines()] == [
        "WARNING a warning line",
        "ERROR an error line",
    ]
    window.level_filter.setCurrentText("DEBUG")
    assert len(window.log_view.toPlainText().splitlines()) == 5
    assert "DEBUG a debug line" in window.log_view.toPlainText()


def test_the_log_view_keeps_at_most_its_maximum(make_window, qtbot):
    window = make_window(_free_port())
    for number in range(window_module.LOG_VIEW_MAX_LINES + 20):
        window.add_log_record(logging.INFO, "10:00:00", f"line {number}")
    lines = window.log_view.toPlainText().splitlines()
    assert len(lines) == window_module.LOG_VIEW_MAX_LINES
    assert lines[-1].endswith(f"line {window_module.LOG_VIEW_MAX_LINES + 19}")


def test_a_multi_line_record_keeps_its_indentation(make_window, qtbot):
    window = make_window(_free_port())
    window.add_log_record(logging.ERROR, "10:00:00", "Traceback:\n    File x, line 1\n  raise")
    text = window.log_view.toPlainText()
    assert "    File x, line 1" in text
    assert "  raise" in text


def test_a_failing_poll_still_ends_the_poll(start_hal, make_window, qtbot, monkeypatch, caplog):
    hal = start_hal()
    real_status = window_module.MonitorLink.status
    failures = [3]

    def failing_status(link):
        if failures[0] > 0:
            failures[0] = failures[0] - 1
            raise RuntimeError("poll broke")
        return real_status(link)

    monkeypatch.setattr(window_module.MonitorLink, "status", failing_status)
    caplog.set_level(logging.DEBUG, logger="pyhal.monitor.window")
    window = make_window(hal.port)
    qtbot.waitUntil(lambda: window.state_label.text() == "not reachable", timeout=WAIT_MS)
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "poll broke" in record.getMessage()
    ]
    assert len(warnings) == 1


def test_stop_asks_first_and_the_window_shows_not_reachable(
    start_hal, make_window, qtbot, tmp_path, monkeypatch
):
    hal = start_hal()
    questions: list[str] = []

    def confirm(parent, title, text):
        questions.append(text)
        return True

    monkeypatch.setattr(window_module, "confirm", confirm)
    monkeypatch.setattr(window_module, "warn", lambda parent, title, text: None)
    window = make_window(hal.port, bench=str(tmp_path / "bench.ini"))
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    qtbot.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    assert "Every open device is torn down, also those of other clients." in questions[0]
    assert "Stopping the HAL" in window.statusBar().currentMessage()
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage()
        == "Stop: The HAL stopped. Every device was torn down.",
        timeout=WAIT_MS,
    )
    assert hal.wait_until_exited(30)
    qtbot.waitUntil(lambda: window.state_label.text() == "not reachable", timeout=WAIT_MS)
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()


def test_closing_during_stop_still_stops_the_hal(
    start_hal, qtbot, tmp_path, monkeypatch, caplog
):
    marks = tmp_path / "marks.txt"
    bench_text = (
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\n"
        "slow_teardown_s = 2\n"
    )
    hal = start_hal(bench_text)
    other = Client(hal.port)
    assert isinstance(other.request("open", device="m1"), messages.Opened)
    monkeypatch.setattr(window_module, "confirm", lambda parent, title, text: True)
    monkeypatch.setattr(window_module, "warn", lambda parent, title, text: None)
    caplog.set_level(logging.INFO, logger="pyhal.monitor.window")
    window = MonitorWindow(hal.port)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    qtbot.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    window.close()
    assert not window.isVisible()
    # What main() does once the event loop has ended.
    window.wait_before_exit()
    assert hal.wait_until_exited(30)
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect", "teardown"]
    assert "Waiting for Stop HAL to finish before the monitor exits." in caplog.text
    assert window.wait_for_workers(30)
    other.close()


def test_the_log_view_follows_a_new_hal(start_hal, make_window, qtbot, tmp_path):
    log_a = tmp_path / "a.log"
    log_b = tmp_path / "b.log"
    log_a.write_text("", encoding="utf-8")
    log_b.write_text("", encoding="utf-8")
    first = start_hal(log_path=str(log_a))
    window = make_window(first.port)
    qtbot.waitUntil(lambda: window.tailed_log == str(log_a), timeout=WAIT_MS)
    _stop(first)
    qtbot.waitUntil(lambda: window.state_label.text() == "not reachable", timeout=WAIT_MS)
    start_hal(port=first.port, log_path=str(log_b))
    qtbot.waitUntil(lambda: window.tailed_log == str(log_b), timeout=WAIT_MS)
    with open(log_b, "a", encoding="utf-8") as handle:
        _record(handle, "INFO", "a line of the new HAL")
    qtbot.waitUntil(
        lambda: "a line of the new HAL" in window.log_view.toPlainText(), timeout=WAIT_MS
    )


# --- serve mode (run_hal.py) ---------------------------------------------------------------


def _serve_window(qtbot, port: int, bench: Path, **options) -> MonitorWindow:
    window = MonitorWindow(port, bench=str(bench), serve=True, **options)
    qtbot.addWidget(window)
    window.show()
    return window


def test_serve_starts_a_hal_and_closing_stops_it(start_hal, qtbot, tmp_path, monkeypatch):
    port = _free_port()
    bench = tmp_path / "bench.ini"
    bench.write_text(f"[loop1]\ndriver = {LOOPBACK}\n", encoding="utf-8")
    started: list[HalServer] = []

    def start_in_threads(bench_path, start_port, **options):
        started.append(start_hal(port=start_port))
        return 4242

    monkeypatch.setattr(window_module.client, "start_hal", start_in_threads)
    window = _serve_window(qtbot, port, bench)
    # No button pressed: the window starts the HAL on its own.
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    assert len(started) == 1
    window.close()
    assert not window.isVisible()
    # What main() does once the event loop has ended.
    window.wait_before_exit()
    assert started[0].wait_until_exited(30)
    assert window.wait_for_workers(30)


def test_serve_attaches_to_a_running_hal_and_closing_stops_it(
    start_hal, qtbot, tmp_path, monkeypatch
):
    hal = start_hal()
    questions: list[str] = []
    monkeypatch.setattr(
        window_module, "confirm", lambda parent, title, text: questions.append(text) or True
    )

    def no_start(*args, **kwargs):
        raise AssertionError("a HAL answers: serve mode must not start another")

    monkeypatch.setattr(window_module.client, "start_hal", no_start)
    window = _serve_window(qtbot, hal.port, tmp_path / "bench.ini")
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    window.close()
    # No other client: closing asks nothing.
    assert questions == []
    window.wait_before_exit()
    assert hal.wait_until_exited(30)
    assert window.wait_for_workers(30)


def test_serve_asks_before_stopping_under_other_clients(start_hal, qtbot, tmp_path, monkeypatch):
    hal = start_hal()
    other = Client(hal.port)
    other.beat()
    answers = [False, True]
    questions: list[str] = []

    def confirm(parent, title, text):
        questions.append(text)
        return answers.pop(0)

    monkeypatch.setattr(window_module, "confirm", confirm)
    window = _serve_window(qtbot, hal.port, tmp_path / "bench.ini")
    qtbot.waitUntil(lambda: window.clients_label.text() == "1", timeout=WAIT_MS)
    window.close()
    # No: the window stays open and the HAL runs on.
    assert window.isVisible()
    assert "Other clients connected: 1." in questions[0]
    # Not started by a program (no exit_with_hal): nothing about PyPTS.
    assert "PyPTS" not in questions[0]
    assert not hal._exited.is_set()
    window.close()
    assert not window.isVisible()
    window.wait_before_exit()
    assert hal.wait_until_exited(30)
    assert window.wait_for_workers(30)
    other.close()


def test_serve_start_passes_the_nonce_and_the_log_level(start_hal, qtbot, tmp_path, monkeypatch):
    port = _free_port()
    bench = tmp_path / "bench.ini"
    bench.write_text(f"[loop1]\ndriver = {LOOPBACK}\n", encoding="utf-8")
    calls: list[dict] = []

    def start_in_threads(bench_path, start_port, **options):
        calls.append(options)
        start_hal(port=start_port)
        return 4242

    monkeypatch.setattr(window_module.client, "start_hal", start_in_threads)
    window = _serve_window(qtbot, port, bench, nonce="abc", log_level=5)
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    assert calls == [{"log_dir": None, "log_level": 5, "nonce": "abc"}]
    window.close()
    window.wait_before_exit()
    assert window.wait_for_workers(30)


def test_exit_with_hal_closes_the_window_when_the_hal_goes(
    start_hal, qtbot, tmp_path, monkeypatch, caplog
):
    # Only the no-Stop half: with the HAL gone there are no other clients, so closeEvent would
    # ask nothing anyway.
    hal = start_hal()
    caplog.set_level(logging.INFO, logger="pyhal.monitor.window")
    window = _serve_window(qtbot, hal.port, tmp_path / "bench.ini", exit_with_hal=True)
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    _stop(hal)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=WAIT_MS)
    window.wait_before_exit()
    assert "has gone; the monitor closes with it." in caplog.text
    assert "Stopping the HAL" not in caplog.text
    assert window.wait_for_workers(30)


def test_exit_with_hal_survives_one_failed_poll(start_hal, qtbot, tmp_path, monkeypatch):
    # One poll without an answer (as a poll slower than POLL_TIMEOUT_S gives) while the HAL
    # runs: the window stays.
    hal = start_hal()
    real_status = window_module.MonitorLink.status
    polls = {"seen": 0, "missed": 0, "after": 0}

    def status_missing_once(link):
        if polls["seen"] >= 1 and polls["missed"] == 0:
            polls["missed"] = 1
            return None
        report = real_status(link)
        if report is not None:
            if polls["missed"] == 1:
                polls["after"] = polls["after"] + 1
            polls["seen"] = polls["seen"] + 1
        return report

    monkeypatch.setattr(window_module.MonitorLink, "status", status_missing_once)
    monkeypatch.setattr(window_module, "confirm", lambda parent, title, text: True)
    window = _serve_window(qtbot, hal.port, tmp_path / "bench.ini", exit_with_hal=True)
    qtbot.waitUntil(lambda: polls["after"] >= 2, timeout=WAIT_MS)
    assert window.isVisible()
    assert window.state_label.text() == "running"
    window.close()
    window.wait_before_exit()
    assert hal.wait_until_exited(30)
    assert window.wait_for_workers(30)


def test_exit_with_hal_waits_for_a_hal_it_has_seen(start_hal, qtbot, tmp_path, monkeypatch):
    # No HAL yet and Start failing: the window stays, showing why.
    def failing_start(bench_path, start_port, **options):
        raise window_module.DriverError("The HAL server could not be started: bad bench")

    monkeypatch.setattr(window_module.client, "start_hal", failing_start)
    window = _serve_window(qtbot, _free_port(), tmp_path / "bench.ini", exit_with_hal=True)
    qtbot.waitUntil(
        lambda: "Start failed" in window.statusBar().currentMessage(), timeout=WAIT_MS
    )
    qtbot.wait(int(window_module.REFRESH_S * 2500))
    assert window.isVisible()
    window.close()
    window.wait_before_exit()
    assert window.wait_for_workers(30)


@pytest.mark.parametrize("option", [["--nonce", "x"], ["--exit-with-hal"]])
def test_the_monitor_options_need_serve(option, capsys):
    with pytest.raises(SystemExit) as caught:
        monitor_main.main(["--bench", "bench.ini", *option])
    assert caught.value.code == 2
    assert f"{option[0]} needs --serve" in capsys.readouterr().err


def test_the_monitor_log_level_is_parsed_as_pyhal_parses_it():
    parser = monitor_main._build_parser()
    assert parser.parse_args(["--log-level", "TRACE"]).log_level == 5
    assert parser.parse_args(["--log-level", "warning"]).log_level == 30
    assert parser.parse_args(["--log-level", "12"]).log_level == 12
    assert parser.parse_args([]).log_level is None
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--log-level", "LOUD"])
    assert caught.value.code == 2


def test_the_window_does_not_count_itself_among_the_clients(start_hal, make_window, qtbot):
    hal = start_hal()
    window = make_window(hal.port)
    qtbot.waitUntil(lambda: window.state_label.text() == "running", timeout=WAIT_MS)
    assert window.clients_label.text() == "0"
    other = Client(hal.port)
    other.beat()
    qtbot.waitUntil(lambda: window.clients_label.text() == "1", timeout=WAIT_MS)
    other.close()


def test_exit_with_hal_says_what_closing_costs_the_starter(start_hal, qtbot, tmp_path, monkeypatch):
    hal = start_hal()
    other = Client(hal.port)
    other.beat()
    questions: list[str] = []

    def confirm(parent, title, text):
        questions.append(text)
        return False

    monkeypatch.setattr(window_module, "confirm", confirm)
    window = _serve_window(qtbot, hal.port, tmp_path / "bench.ini", exit_with_hal=True)
    qtbot.waitUntil(lambda: window.clients_label.text() == "1", timeout=WAIT_MS)
    window.close()
    assert window.isVisible()
    assert "Other clients connected: 1." in questions[0]
    assert window_module.STARTER_WARNING in questions[0]
    assert "PyPTS cannot reach them again until it is restarted" in questions[0]
    assert "Restart" in questions[0]
    # Let the window close without stopping the HAL: the fixture stops it.
    window._hal_gone = True
    window.close()
    window.wait_before_exit()
    assert window.wait_for_workers(30)
    other.close()


def _report(pid: int) -> messages.StatusReport:
    return messages.StatusReport(
        pid=pid, version="v", bench="b", log="", clients=0, busy=None, queued=0, devices=[]
    )


def test_exit_with_hal_does_not_latch_onto_another_hal(qtbot, tmp_path, monkeypatch, caplog):
    # The HAL seen first (pid 1) goes and another starter's (pid 2) takes the port at once:
    # no poll finds none, yet the window closes, since pid 2 is not its HAL.
    reports = [_report(1), _report(1), _report(2)]

    def status(link):
        if len(reports) > 1:
            return reports.pop(0)
        return reports[0]

    def no_start(*args, **kwargs):
        raise AssertionError("a HAL answers: serve mode must not start another")

    monkeypatch.setattr(window_module.MonitorLink, "status", status)
    monkeypatch.setattr(window_module.client, "start_hal", no_start)
    caplog.set_level(logging.INFO, logger="pyhal.monitor.window")
    window = _serve_window(qtbot, _free_port(), tmp_path / "bench.ini", exit_with_hal=True)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=WAIT_MS)
    assert window.pid_label.text() == "2"
    window.wait_before_exit()
    assert "has gone; the monitor closes with it." in caplog.text
    assert "Stopping the HAL" not in caplog.text
    assert window.wait_for_workers(30)


def test_without_exit_with_hal_another_pid_is_just_shown(make_window, qtbot, monkeypatch):
    reports = [_report(1), _report(2)]

    def status(link):
        if len(reports) > 1:
            return reports.pop(0)
        return reports[0]

    monkeypatch.setattr(window_module.MonitorLink, "status", status)
    window = make_window(_free_port())
    qtbot.waitUntil(lambda: window.pid_label.text() == "2", timeout=WAIT_MS)
    qtbot.wait(int(window_module.REFRESH_S * 2500))
    assert window.isVisible()
    assert window.state_label.text() == "running"
