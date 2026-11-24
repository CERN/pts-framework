"""
Unit tests for CORE's HAL link (src/pypts/core/hal_link.py).

The tests that connect run a HalServer in threads of the test process, on a free port, with
real driver processes, as test_pyhal_client.py does; its bench is this test's bench.ini
(tests/conftest.py puts it in a temporary folder), so bench_config() names the same file.
tests/conftest.py turns the HAL off for every test (PYPTS_HAL=off); a test that wants a
connect removes the switch. The client module's state is reset before and after each test.
"""

import logging
import multiprocessing
import socket
import threading
import time
from pathlib import Path

import pytest

from pyhal import DriverError, client, hal_log
from pyhal.protocol import codec, messages
from pyhal.server import HalServer
from pypts.config_handler import file_locations
from pypts.config_handler.bench_config import BenchConfig, BenchOutcome
from pypts.core import hal_link
from pypts.core.hal_link import CLOSE_WAIT_S, HAL_OFF, HalLink

LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"
CONNECT_WAIT_S = 20.0


class RawClient:
    """One raw connection: a spare client, for `info` and for stopping the server."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=20)
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

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def _stop(hal: HalServer) -> None:
    if not hal._exited.is_set():
        try:
            raw = RawClient(hal.port)
            if isinstance(raw.hello, messages.Hello):
                raw.request("shutdown")
            raw.close()
        except OSError:
            pass
    waiter = threading.Thread(target=hal.serve_until_stopped)
    waiter.start()
    waiter.join(timeout=120)
    assert not waiter.is_alive(), "the HAL server did not exit"


def _reset_client_module() -> None:
    with client._state_lock:
        left = client._client
    if left is not None:
        left.close()
    with client._state_lock:
        client._client = None
        client._scope_active = False
        client._scope_devices = []
        client._connect_problem = None
    client._connect_settled.set()


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@pytest.fixture
def start_hal():
    """start_hal(bench_text) -> a started HalServer on a free port; stopped afterwards."""
    _reset_client_module()
    started: list[HalServer] = []

    def start(bench_text: str = f"[loop1]\ndriver = {LOOPBACK}\n", log_path: str = "") -> HalServer:
        bench = file_locations.bench_file_path()
        bench.write_text(bench_text, encoding="utf-8")
        hal = HalServer(bench, 0, log_path=log_path)
        hal.start()
        started.append(hal)
        return hal

    yield start
    _reset_client_module()
    for hal in started:
        _stop(hal)
    assert multiprocessing.active_children() == []


@pytest.fixture
def clean_client():
    """The client module's state reset before and after a test that starts no server."""
    _reset_client_module()
    yield
    _reset_client_module()


def _wait_for_connect(link: HalLink) -> None:
    thread = link._thread
    assert thread is not None
    thread.join(CONNECT_WAIT_S)
    assert not thread.is_alive(), "the HAL connect did not end"


def _get_device_error(name: str) -> str:
    with client.run_scope(), pytest.raises(DriverError) as caught:
        client.get_device(name)
    return str(caught.value)


def test_the_switch_off_makes_no_connect_and_says_why(clean_client, monkeypatch):
    monkeypatch.setenv("PYPTS_HAL", "off")
    called: list[object] = []
    monkeypatch.setattr(hal_link, "connect", lambda *args, **kwargs: called.append(args))
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    link.start()
    assert link._thread is None
    assert called == []
    started = time.monotonic()
    assert _get_device_error("loop1") == HAL_OFF
    assert time.monotonic() - started < 5
    link.close()


def test_a_discarded_bench_is_what_get_device_reports(clean_client, monkeypatch, tmp_path):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    discarded = BenchConfig(
        devices={},
        outcome=BenchOutcome.DISCARDED,
        problem="it is broken.",
        path=tmp_path / "bench.ini",
    )
    monkeypatch.setattr(hal_link, "bench_config", lambda: discarded)
    called: list[object] = []
    monkeypatch.setattr(hal_link, "connect", lambda *args, **kwargs: called.append(args))
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    link.start()
    assert link._thread is None
    assert called == []
    assert _get_device_error("loop1") == (
        "bench.ini was discarded at startup, so this start has no devices: it is broken."
    )
    link.close()


def test_it_connects_to_a_running_hal_and_relogs_its_lines(
    start_hal, monkeypatch, tmp_path, caplog
):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    log_path = hal_log.start_log_file(tmp_path / "logs", logging.INFO)
    # In this process the HAL's log file is a handler on the root logger: keep the re-logged
    # lines out of it, or the tail would read them back (a real HAL is another process).
    handler = hal_log._installed[log_path][0]
    handler.addFilter(lambda record: not record.name.startswith("pypts"))
    try:
        hal = start_hal(log_path=str(log_path))
        link = HalLink(logging.INFO, show_window=False, port=hal.port)
        with caplog.at_level(logging.DEBUG, logger="pypts.core.hal_link"):
            link.start()
            _wait_for_connect(link)
            with client.run_scope():
                client.get_device("loop1").log_message("Hello from the driver.")
                logging.getLogger("pyhal.server").warning("A warning of the HAL.")
            link.close()
        records = [r for r in caplog.records if r.name == "pypts.core.hal_link"]
        infos = [r.getMessage() for r in records if r.levelno == logging.INFO]
        assert "Connected to the HAL server." in infos
        relogged = [r for r in records if r.getMessage().startswith("HAL: ")]
        driver_lines = [r for r in relogged if r.getMessage().endswith("Hello from the driver.")]
        assert driver_lines and driver_lines[0].levelno == logging.INFO
        warnings = [r for r in relogged if r.getMessage() == "HAL: A warning of the HAL."]
        assert warnings and warnings[0].levelno == logging.WARNING
    finally:
        _reset_client_module()
        hal_log.stop_log_file(log_path)


def test_close_sends_close_all_to_a_hal_it_found(start_hal, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    hal = start_hal()
    link = HalLink(logging.INFO, show_window=False, port=hal.port)
    link.start()
    _wait_for_connect(link)
    with client.run_scope():
        assert client.get_device("loop1").echo(7) == 7
        # A crash close, in the middle of a run.
        link.close()
    spare = RawClient(hal.port)
    try:
        deadline = time.monotonic() + 10
        while True:
            answer = spare.request("info", device="loop1")
            assert isinstance(answer, messages.DeviceInfo)
            if answer.is_open is False:
                break
            assert time.monotonic() < deadline, "the device was never closed"
            time.sleep(0.05)
        assert not hal._exited.is_set()
    finally:
        spare.close()
    link.close()


def test_close_sends_shutdown_to_a_hal_it_started(start_hal, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    hal = start_hal()

    def started_by_this_link(bench, port, **options):
        # As if this connect had started the HAL: the threaded server stands in for it.
        hal_client = client.connect_only(port, scope=False)
        hal_client.started_hal = True
        return hal_client

    monkeypatch.setattr(hal_link, "connect", started_by_this_link)
    link = HalLink(logging.INFO, show_window=True, port=hal.port)
    link.start()
    _wait_for_connect(link)
    link.close()
    assert hal._exited.wait(30)
    assert hal._exit_reason == "shutdown"


def test_close_during_the_startup_connect_does_not_block(start_hal, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    hal = start_hal()
    release = threading.Event()
    made: list[client.HalClient] = []

    def slow_connect(bench, port, **options):
        release.wait(30)
        hal_client = client.connect_only(port, scope=False)
        made.append(hal_client)
        return hal_client

    monkeypatch.setattr(hal_link, "connect", slow_connect)
    link = HalLink(logging.INFO, show_window=False, port=hal.port)
    link.start()
    started = time.monotonic()
    link.close()
    assert time.monotonic() - started < CLOSE_WAIT_S + 1
    # The connect returns after the close: the thread closes that client itself, at once.
    release.set()
    _wait_for_connect(link)
    assert len(made) == 1
    assert made[0]._closed is True
    assert link._client is None


def test_a_failed_connect_is_what_get_device_reports(clean_client, monkeypatch, caplog):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    bench = file_locations.bench_file_path()
    bench.write_text(f"[loop1]\ndriver = {LOOPBACK}\n", encoding="utf-8")

    def failing_connect(bench, port, **options):
        raise DriverError("x")

    monkeypatch.setattr(hal_link, "connect", failing_connect)
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    with caplog.at_level(logging.DEBUG, logger="pypts.core.hal_link"):
        link.start()
        _wait_for_connect(link)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["The HAL server could not be reached: x"]
    started = time.monotonic()
    assert _get_device_error("loop1") == "x"
    assert time.monotonic() - started < 5
    link.close()


def test_an_unexpected_failure_of_the_connect_still_settles_it(clean_client, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)

    def broken_connect(bench, port, **options):
        raise ValueError("unexpected")

    monkeypatch.setattr(hal_link, "connect", broken_connect)
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    link.start()
    _wait_for_connect(link)
    started = time.monotonic()
    assert _get_device_error("loop1") == "ValueError: unexpected"
    assert time.monotonic() - started < 5
    link.close()


def test_close_before_start_and_twice_is_harmless(clean_client, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    called: list[object] = []
    monkeypatch.setattr(hal_link, "connect", lambda *args, **kwargs: called.append(args))
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    link.close()
    link.close()
    link.start()
    assert link._thread is None
    assert called == []


def test_the_connect_gets_the_bench_path_and_the_options(clean_client, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    got: list[tuple[object, ...]] = []

    def recording_connect(bench, port, **options):
        got.append((bench, port, options))
        raise DriverError("not this time")

    monkeypatch.setattr(hal_link, "connect", recording_connect)
    port = _free_port()
    link = HalLink(logging.DEBUG, show_window=True, port=port)
    link.start()
    _wait_for_connect(link)
    assert link._thread is not None
    assert link._thread.name == "HAL connect"
    assert link._thread.daemon is True
    bench, got_port, options = got[0]
    assert Path(bench) == file_locations.bench_file_path()
    assert got_port == port
    assert options == {
        "scope": False,
        "log_sink": link._sink,
        "log_level": logging.DEBUG,
        "show_window": True,
    }
    link.close()


def test_finish_lets_a_late_connect_close_what_it_started(start_hal, monkeypatch):
    # CORE's loop is over and its process about to exit: a connect that returns after close()
    # (a slow window start) must still close its client, or the HAL it started runs on.
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    monkeypatch.setattr(hal_link, "CLOSE_WAIT_S", 0.2)
    hal = start_hal()
    closed_at: list[float] = []
    made: list[client.HalClient] = []

    def late_connect(bench, port, **options):
        while not closed_at:
            time.sleep(0.01)
        time.sleep(1.0)
        hal_client = client.connect_only(port, scope=False)
        hal_client.started_hal = True
        made.append(hal_client)
        return hal_client

    monkeypatch.setattr(hal_link, "connect", late_connect)
    link = HalLink(logging.INFO, show_window=True, port=hal.port)
    link.start()
    link.close()
    closed_at.append(time.monotonic())
    assert link._thread is not None and link._thread.is_alive()
    link.finish()
    assert not link._thread.is_alive()
    assert len(made) == 1
    assert made[0]._closed is True
    # Its parting request: `shutdown`, since it started this HAL.
    assert hal._exited.wait(30)
    assert hal._exit_reason == "shutdown"
    link.finish()


def test_finish_without_a_connect_does_nothing(clean_client, monkeypatch):
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    started = time.monotonic()
    link.finish()
    link.start()  # PYPTS_HAL=off: no thread
    link.finish()
    link.close()
    link.finish()
    assert link._thread is None
    assert time.monotonic() - started < 1


def test_finish_waits_at_most_finish_wait_s(clean_client, monkeypatch):
    monkeypatch.delenv("PYPTS_HAL", raising=False)
    monkeypatch.setattr(hal_link, "CLOSE_WAIT_S", 0.1)
    monkeypatch.setattr(hal_link, "FINISH_WAIT_S", 0.3)
    release = threading.Event()

    def hanging_connect(bench, port, **options):
        release.wait(30)
        raise DriverError("too late")

    monkeypatch.setattr(hal_link, "connect", hanging_connect)
    link = HalLink(logging.INFO, show_window=False, port=_free_port())
    link.start()
    link.close()
    started = time.monotonic()
    link.finish()
    assert time.monotonic() - started < 2
    release.set()
    _wait_for_connect(link)
