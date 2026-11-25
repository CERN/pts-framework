"""
Unit tests for `python -m pyhal` (src/pyhal/__main__.py): its options, its report, and the
exit handlers. The handlers are driven in this process, on a HalServer running in threads,
with the real signal machinery (signal.raise_signal) and the console handler called directly.
Every handler installed is restored before the test ends.
"""

import logging
import signal
import socket
import sys
import threading
from pathlib import Path

import pytest

from pyhal import __main__ as pyhal_main
from pyhal.hal_log import TRACE, stop_log_file
from pyhal.protocol import codec, messages
from pyhal.server import HalServer


def _open_m1(port: int) -> socket.socket:
    """A raw connection that opened m1, left open."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=30)
    stream = sock.makefile("rb")
    assert isinstance(codec.decode(codec.read_line(stream), messages.HAL_KINDS), messages.Hello)
    sock.sendall(codec.encode(messages.Open("m1")))
    answer = codec.decode(codec.read_line(stream), messages.HAL_KINDS)
    assert isinstance(answer, messages.Opened)
    stream.close()
    return sock


def _marking_hal(tmp_path: Path, slow_teardown_s: float = 0) -> tuple[HalServer, Path]:
    marks = tmp_path / "marks.txt"
    bench = tmp_path / "bench.ini"
    bench.write_text(
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\n"
        f"slow_teardown_s = {slow_teardown_s}\n",
        encoding="utf-8",
    )
    hal = HalServer(bench, 0)
    return hal, marks


def test_log_levels_are_numbers_or_names():
    assert pyhal_main.parse_log_level("TRACE") == TRACE
    assert pyhal_main.parse_log_level("debug") == logging.DEBUG
    assert pyhal_main.parse_log_level("25") == 25
    with pytest.raises(ValueError):
        pyhal_main.parse_log_level("LOUD")


def test_the_report_and_its_exit_code(capsys):
    assert pyhal_main.report_not_torn_down([]) == 0
    assert capsys.readouterr().out == "Every device was torn down.\n"
    assert pyhal_main.report_not_torn_down(["psu1", "load2"]) == 1
    assert capsys.readouterr().out == "Not torn down: psu1, load2\n"


def test_serving_needs_a_bench(capsys):
    with pytest.raises(SystemExit) as caught:
        pyhal_main.main(["--port", "1"])
    assert caught.value.code == 2
    assert "--bench" in capsys.readouterr().err


def test_a_signal_tears_down_and_a_second_one_does_not_abort_it(tmp_path):
    hal, marks = _marking_hal(tmp_path, slow_teardown_s=2)
    handlers = pyhal_main.ExitHandlers(hal)
    handlers.install()
    try:
        hal.start()
        raw = _open_m1(hal.port)
        signal.raise_signal(signal.SIGINT)
        # The teardown is under way (2 s); a second Ctrl+C changes nothing.
        signal.raise_signal(signal.SIGINT)
        hal.serve_until_stopped()
        raw.close()
    finally:
        handlers.restore()
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect", "teardown"]
    assert hal._exit_reason == "signal SIGINT"


def test_restore_puts_the_previous_handlers_back(tmp_path):
    hal, _ = _marking_hal(tmp_path)
    before = signal.getsignal(signal.SIGINT)
    handlers = pyhal_main.ExitHandlers(hal)
    handlers.install()
    assert signal.getsignal(signal.SIGINT) is not before
    handlers.restore()
    assert signal.getsignal(signal.SIGINT) is before


@pytest.mark.skipif(sys.platform != "win32", reason="the console control handler is Windows'")
def test_the_console_close_event_waits_for_the_teardown(tmp_path):
    hal, marks = _marking_hal(tmp_path, slow_teardown_s=1)
    handlers = pyhal_main.ExitHandlers(hal)
    hal.start()
    raw = _open_m1(hal.port)
    # Ctrl+C and Ctrl+Break are left to the signal handlers.
    assert handlers.on_console_event(pyhal_main.CTRL_C_EVENT) == 0
    assert hal._exit_reason is None
    answers: list[int] = []
    closer = threading.Thread(
        target=lambda: answers.append(handlers.on_console_event(pyhal_main.CTRL_CLOSE_EVENT))
    )
    closer.start()
    closer.join(timeout=60)
    assert not closer.is_alive()
    # Windows ends the process when the handler returns, so it returned only after the exit.
    assert answers == [1]
    assert hal.wait_until_exited(0)
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect", "teardown"]
    raw.close()


def test_serve_leaves_only_after_the_teardown_even_when_its_wait_fails(tmp_path, monkeypatch):
    # The driver processes are daemons: had serve() returned before the teardown, the
    # interpreter's exit would have killed them without it.
    marks = tmp_path / "marks.txt"
    bench = tmp_path / "bench.ini"
    bench.write_text(
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\n", encoding="utf-8"
    )
    started: list[HalServer] = []
    log_files: list[Path] = []
    original_start = HalServer.start
    original_wait = HalServer.serve_until_stopped
    original_start_log_file = pyhal_main.start_log_file
    sockets: list[socket.socket] = []

    def start(self: HalServer) -> None:
        original_start(self)
        started.append(self)

    def failing_wait(self: HalServer) -> None:
        if len(sockets) == 0:
            sockets.append(_open_m1(self.port))
            raise RuntimeError("the wait failed")
        original_wait(self)

    def start_log_file(log_dir: Path, level: int) -> Path:
        path = original_start_log_file(log_dir, level)
        log_files.append(path)
        return path

    monkeypatch.setattr(HalServer, "start", start)
    monkeypatch.setattr(HalServer, "serve_until_stopped", failing_wait)
    monkeypatch.setattr(pyhal_main, "start_log_file", start_log_file)
    before = signal.getsignal(signal.SIGINT)
    try:
        with pytest.raises(RuntimeError, match="the wait failed"):
            pyhal_main.serve(bench, 0, tmp_path / "logs", logging.INFO, None)
    finally:
        for path in log_files:
            stop_log_file(path)
        for sock in sockets:
            sock.close()
    assert started[0].wait_until_exited(0)
    assert started[0]._exit_reason == "the main thread is ending"
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect", "teardown"]
    assert signal.getsignal(signal.SIGINT) is before


# --- --window: the HAL opens its monitor window and owns it (user decision 2026-11-24) -------


class _FakeWindowProcess:
    """Stands in for the monitor's Popen: records what is done to it."""

    def __init__(self, command, **options) -> None:
        self.command = list(command)
        self.options = options
        self.pid = 4244
        self.exit_code: int | None = None
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 1

    def wait(self, timeout=None):
        return self.exit_code

    def kill(self) -> None:
        self.exit_code = 1


def test_the_window_option_is_parsed():
    parser = pyhal_main._build_parser()
    assert parser.parse_args(["--bench", "b.ini", "--window"]).window is True
    assert parser.parse_args(["--bench", "b.ini"]).window is False


def test_open_window_runs_the_monitor_on_the_port_as_a_child(tmp_path, monkeypatch):
    made: list[_FakeWindowProcess] = []

    def fake_popen(command, **options):
        process = _FakeWindowProcess(command, **options)
        made.append(process)
        return process

    monkeypatch.setattr(pyhal_main.subprocess, "Popen", fake_popen)
    process = pyhal_main.open_window(29600, tmp_path)
    assert process is made[0]
    assert made[0].command[1:] == [
        "-P",
        "-m",
        "pyhal.monitor",
        "--port",
        "29600",
        "--exit-with-hal",
    ]
    assert made[0].options["cwd"] == tmp_path.resolve()
    assert (tmp_path / pyhal_main.MONITOR_STARTUP_FILE).exists()
    # Not detached: no process group or session of its own.
    assert "start_new_session" not in made[0].options
    if sys.platform == "win32":
        assert made[0].options["creationflags"] == pyhal_main.subprocess.CREATE_NO_WINDOW


def test_a_window_that_cannot_start_is_a_warning(tmp_path, monkeypatch, caplog):
    def failing_popen(command, **options):
        raise OSError("no such interpreter")

    monkeypatch.setattr(pyhal_main.subprocess, "Popen", failing_popen)
    with caplog.at_level(logging.WARNING, logger="pyhal"):
        assert pyhal_main.open_window(29600, tmp_path) is None
    assert "The HAL monitor window could not be started: no such interpreter" in caplog.text


def test_close_window_ends_only_a_window_still_open():
    pyhal_main.close_window(None)
    gone = _FakeWindowProcess([])
    gone.exit_code = 0
    pyhal_main.close_window(gone)  # type: ignore[arg-type]
    assert gone.terminated is False
    still_open = _FakeWindowProcess([])
    pyhal_main.close_window(still_open)  # type: ignore[arg-type]
    assert still_open.terminated is True


def test_serve_with_window_opens_it_and_ends_it_after_the_teardown(tmp_path, monkeypatch):
    bench = tmp_path / "bench.ini"
    bench.write_text("[loop1]\ndriver = pyhal.drivers.loopback.LoopbackDriver\n", "utf-8")
    events: list[str] = []
    window = _FakeWindowProcess([])
    servers: list[HalServer] = []
    log_files: list[Path] = []
    original_wait = HalServer.serve_until_stopped
    original_start_log_file = pyhal_main.start_log_file

    def open_window(port: int, log_dir: Path):
        events.append(f"open {port} {log_dir}")
        return window

    def close_window(monitor) -> None:
        exited = servers[0].wait_until_exited(0)
        events.append(f"close, the HAL exited: {exited}")
        assert monitor is window

    def wait(self: HalServer) -> None:
        servers.append(self)
        self.request_exit("the test is done")
        original_wait(self)

    def start_log_file(log_dir: Path, level: int) -> Path:
        path = original_start_log_file(log_dir, level)
        log_files.append(path)
        return path

    monkeypatch.setattr(pyhal_main, "open_window", open_window)
    monkeypatch.setattr(pyhal_main, "close_window", close_window)
    monkeypatch.setattr(HalServer, "serve_until_stopped", wait)
    monkeypatch.setattr(pyhal_main, "start_log_file", start_log_file)
    try:
        code = pyhal_main.serve(bench, 0, tmp_path / "logs", logging.INFO, None, window=True)
    finally:
        for path in log_files:
            stop_log_file(path)
    assert code == pyhal_main.EXIT_OK
    logs = tmp_path / "logs"
    assert events == [f"open {servers[0].port} {logs}", "close, the HAL exited: True"]
