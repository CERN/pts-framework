"""
Unit tests for the HAL monitor's link (src/pyhal/monitor/link.py).

Each test runs a HalServer in threads of the test process, on a free port, with real driver
processes, as test_pyhal_server.py does; raw sockets stand in for the other clients. A HAL in
threads reports the test process's pid, so two of them are told apart by their nonce and log.
"""

import logging
import multiprocessing
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from pyhal import DriverError, connection_driver
from pyhal.monitor import link as link_module
from pyhal.monitor.link import MonitorLink
from pyhal.protocol import codec, messages
from pyhal.server import HalServer

LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"


class Client:
    """One raw connection: reads the first message (hello) at once, then lines on request."""

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


def _marking_bench(tmp_path: Path) -> tuple[str, Path]:
    marks = tmp_path / "marks.txt"
    text = (
        f"[loop1]\ndriver = {LOOPBACK}\n"
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\ntag = m1\n"
        f"[m2]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\ntag = m2\n"
    )
    return text, marks


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
def make_link():
    """make_link(port) -> a MonitorLink; closed afterwards."""
    links: list[MonitorLink] = []

    def make(port: int) -> MonitorLink:
        link = MonitorLink(port)
        links.append(link)
        return link

    yield make
    for link in links:
        link.close()


def test_status_reports_the_hal_and_its_devices(start_hal, make_link, tmp_path):
    bench_text, _marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text, nonce="n-1", log_path="C:/logs/hal.log")
    other = Client(hal.port)
    assert isinstance(other.request("open", device="m1"), messages.Opened)
    link = make_link(hal.port)
    report = link.status()
    assert isinstance(report, messages.StatusReport)
    assert report.pid == os.getpid()
    assert report.version == messages.hal_version()
    assert report.bench == str((tmp_path / "bench.ini").resolve())
    assert report.log == "C:/logs/hal.log"
    # Only `other`: the link's poll asks nothing but `status`, so the HAL does not count it.
    assert report.clients == 1
    assert report.busy is None
    assert report.queued == 0
    states = {row["name"]: row["state"] for row in report.devices}
    assert states == {"loop1": "configured", "m1": "open", "m2": "configured"}
    assert link.hello is not None
    assert link.hello.nonce == "n-1"
    assert link.hello.open == ["m1"]
    # The next poll uses the same connection: still one client.
    assert link.status().clients == 1
    other.close()


def test_status_is_none_when_no_hal_answers(make_link):
    link = make_link(_free_port())
    assert link.status() is None
    assert link.hello is None
    assert link.log_tail(lambda level, message: None) is None


def test_actions_raise_when_no_hal_answers(make_link):
    port = _free_port()
    link = make_link(port)
    with pytest.raises(DriverError, match=f"No HAL server answered on 127.0.0.1:{port}"):
        link.close_all()
    with pytest.raises(DriverError, match=f"No HAL server answered on 127.0.0.1:{port}"):
        link.stop()


def test_the_link_reconnects_to_a_new_hal(start_hal, make_link):
    first = start_hal(nonce="A", log_path="a.log")
    link = make_link(first.port)
    assert link.status().log == "a.log"
    _stop(first)
    assert link.status() is None
    second = start_hal(port=first.port, nonce="B", log_path="b.log")
    report = link.status()
    assert report is not None
    assert report.pid == os.getpid()
    assert report.log == "b.log"
    assert link.hello.nonce == "B"
    assert second.port == first.port


def test_close_all_returns_what_was_not_torn_down(start_hal, make_link, tmp_path, monkeypatch):
    monkeypatch.setattr(connection_driver, "RESCUE_TIMEOUT_S", 1.0)
    bench_text, marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text, call_timeout_s=1.0)
    other = Client(hal.port)
    assert isinstance(other.request("open", device="m1"), messages.Opened)
    assert isinstance(other.request("open", device="m2"), messages.Opened)
    Path(str(marks) + ".tdhang.m2").write_text("", encoding="utf-8")
    link = make_link(hal.port)
    assert link.close_all() == ["m2"]
    assert "teardown m1" in marks.read_text(encoding="utf-8").splitlines()
    # The HAL goes on serving.
    assert link.status() is not None
    other.close()


def test_stop_ends_the_hal(start_hal, make_link, tmp_path):
    bench_text, marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text)
    other = Client(hal.port)
    assert isinstance(other.request("open", device="m1"), messages.Opened)
    other.close()
    link = make_link(hal.port)
    assert link.stop() == []
    assert hal.wait_until_exited(30)
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect m1", "teardown m1"]
    assert link.status() is None


def test_closing_the_link_sends_nothing(start_hal, make_link, tmp_path):
    bench_text, marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text)
    spare = Client(hal.port)
    assert isinstance(spare.request("open", device="m1"), messages.Opened)
    link = make_link(hal.port)
    assert link.status().clients == 1
    _wait_for_connections(hal, 2)
    link.close()
    # Once the HAL has seen the link go, every line it sent has been taken: a close_all it
    # sent would be queued before the `info` below.
    _wait_for_connections(hal, 1)
    info = spare.request("info", device="m1")
    assert info.is_open is True
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect m1"]
    spare.close()


def test_start_refuses_when_a_hal_answers(start_hal, make_link, tmp_path):
    hal = start_hal()
    link = make_link(hal.port)
    with pytest.raises(DriverError) as caught:
        link.start(str(tmp_path / "bench.ini"))
    assert str(caught.value) == f"A HAL server already answers on port {hal.port}."


def test_the_log_tail_follows_the_last_hellos_log(start_hal, make_link, tmp_path):
    log_file = tmp_path / "hal.log"
    log_file.write_text("", encoding="utf-8")
    hal = start_hal(log_path=str(log_file))
    link = make_link(hal.port)
    # No hello yet: no log to follow.
    assert link.log_tail(lambda level, message: None) is None
    assert link.status() is not None
    records: list[tuple[int, str]] = []
    tail = link.log_tail(lambda level, message: records.append((level, message)))
    assert tail is not None
    try:
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write("2026-11-23 10:00:00.000;WARNING;pyhal;a line\n")
        tail.drain()
    finally:
        tail.stop()
    assert records == [(logging.WARNING, "a line")]


def test_a_refused_stop_still_says_what_was_not_torn_down(start_hal, make_link, monkeypatch):
    hal = start_hal()
    real_close_all_on = link_module._close_all_on

    def close_all_then_exit(sock, stream, port):
        names = real_close_all_on(sock, stream, port)
        # Another shutdown is under way by the time this one's `shutdown` arrives.
        hal.request_exit("test")
        return ["psu1", *names]

    monkeypatch.setattr(link_module, "_close_all_on", close_all_then_exit)
    link = make_link(hal.port)
    with pytest.raises(DriverError) as caught:
        link.stop()
    assert str(caught.value) == (
        "The HAL server did not stop: The HAL server is shutting down. Not torn down: psu1"
    )
