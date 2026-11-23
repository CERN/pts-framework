"""
Unit tests for the HAL server (src/pyhal/server.py) and its log file (src/pyhal/hal_log.py).

Each test runs a HalServer in threads of the test process, on a free port, with real driver
processes (the loopback driver and the ones in hal_test_drivers.py). The clients are raw
sockets speaking the protocol through pyhal.protocol.codec, so the server is tested on the
wire, not through pyhal's own client.
"""

import hashlib
import logging
import math
import multiprocessing
import os
import re
import select
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from pyhal import hal_log, server
from pyhal.protocol import codec, messages
from pyhal.server import HalServer

LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"
SHUTTING_DOWN = messages.Error("hal", "The HAL server is shutting down.")


class Client:
    """One raw connection: reads the first message (hello) at once, then lines on request."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=20)
        self.stream = self.sock.makefile("rb")
        self.hello = self.receive()

    def send(self, kind: str, **fields) -> None:
        message = messages.build(messages.CLIENT_KINDS, kind, **fields)
        self.sock.sendall(codec.encode(message))

    def receive(self):
        line = codec.read_line(self.stream)
        if line is None:
            return None
        return codec.decode(line, messages.HAL_KINDS)

    def request(self, kind: str, **fields):
        self.send(kind, **fields)
        return self.receive()

    def call(self, device: str, operation: str, *args):
        return self.request("call", device=device, operation=operation, args=list(args), kwargs={})

    def has_data_within(self, seconds: float) -> bool:
        readable, _, _ = select.select([self.sock], [], [], seconds)
        return bool(readable)

    def close_at_once(self) -> None:
        """Half-close after sending, then close: what a client that does not wait does."""
        self.sock.shutdown(socket.SHUT_WR)
        self.close()

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


@pytest.fixture
def start_hal(tmp_path):
    """start_hal(bench_text, **options) -> a started HalServer; stopped afterwards."""
    started: list[HalServer] = []

    def start(bench_text: str = f"[loop1]\ndriver = {LOOPBACK}\n", **options) -> HalServer:
        bench = tmp_path / "bench.ini"
        bench.write_text(bench_text, encoding="utf-8")
        hal = HalServer(bench, 0, **options)
        hal.start()
        started.append(hal)
        return hal

    yield start
    for hal in started:
        _stop(hal)
    assert multiprocessing.active_children() == []
    left = [thread.name for thread in threading.enumerate() if thread.name.startswith("HAL ")]
    assert left == []


def _marking_bench(tmp_path: Path, extra: str = "") -> tuple[str, Path]:
    marks = tmp_path / "marks.txt"
    text = (
        f"[loop1]\ndriver = {LOOPBACK}\n"
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\n{extra}"
    )
    return text, marks


def _client_threads() -> list[str]:
    return [thread.name for thread in threading.enumerate() if thread.name.startswith("HAL client")]


def _wait_for_last_mark(marks: Path, word: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if marks.exists():
            lines = marks.read_text(encoding="utf-8").split()
            if lines and lines[-1] == word:
                return True
        time.sleep(0.05)
    return False


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


def _running(operation: str):
    def condition(report: messages.StatusReport) -> bool:
        return report.busy is not None and report.busy["operation"] == operation

    return condition


def _queued(count: int):
    def condition(report: messages.StatusReport) -> bool:
        return report.queued == count

    return condition


def _server_connection(hal: HalServer, index: int):
    """The server's own object for the index-th connection still open, in accept order."""
    with hal._lock:
        return hal._connections[index]


class StallingSocket:
    """A server-side socket whose writes block until it is hung up: a client that never reads."""

    def __init__(self, real: socket.socket) -> None:
        self._real = real
        self._woken = threading.Event()

    def sendall(self, data: bytes) -> None:
        self._woken.wait(30)
        raise OSError("the stalled write was ended")

    def shutdown(self, how: int) -> None:
        # Linux: shutdown() wakes a stalled write. Windows: only detach() and close() do.
        if sys.platform != "win32":
            self._woken.set()
        self._real.shutdown(how)

    def detach(self) -> int:
        self._woken.set()
        return self._real.detach()

    def close(self) -> None:
        self._woken.set()
        self._real.close()


def test_hello_names_the_hal(start_hal, tmp_path):
    hal = start_hal(nonce="n-123", log_path="C:/logs/hal.log")
    client = Client(hal.port)
    hello = client.hello
    assert isinstance(hello, messages.Hello)
    bench = tmp_path / "bench.ini"
    assert hello.pid == os.getpid()
    assert hello.nonce == "n-123"
    assert hello.bench == str(bench.resolve())
    assert hello.bench_sha256 == hashlib.sha256(bench.read_bytes()).hexdigest()
    assert hello.log == "C:/logs/hal.log"
    assert hello.open == []
    assert hello.clients == 0
    second = Client(hal.port)
    assert second.hello.clients == 1
    client.close()
    second.close()


def test_a_call_round_trip(start_hal):
    hal = start_hal()
    client = Client(hal.port)
    opened = client.request("open", device="loop1")
    assert isinstance(opened, messages.Opened)
    assert opened.device == "loop1"
    assert opened.device_type == "Other"
    assert "echo" in opened.operations
    result = client.call("loop1", "echo", float("nan"))
    assert isinstance(result, messages.Result)
    assert math.isnan(result.value)
    client.close()


def test_driver_errors_and_hal_errors_carry_their_origin(start_hal):
    hal = start_hal()
    client = Client(hal.port)
    answer = client.call("loop1", "fail", "boom")
    assert answer == messages.Error("driver", "Device 'loop1': 'fail' failed: RuntimeError: boom")
    answer = client.request("open", device="nope")
    assert isinstance(answer, messages.Error)
    assert answer.origin == "hal"
    assert answer.message.startswith("No device 'nope' is configured.")
    client.close()


def test_two_clients_share_a_device_fifo(start_hal):
    hal = start_hal()
    a = Client(hal.port)
    b = Client(hal.port)
    spare = Client(hal.port)
    assert isinstance(a.request("open", device="loop1"), messages.Opened)
    a.send("call", device="loop1", operation="echo", args=["a"], kwargs={})
    b.send("call", device="loop1", operation="echo", args=["b"], kwargs={})
    assert a.receive() == messages.Result("a")
    assert b.receive() == messages.Result("b")
    a.send("call", device="loop1", operation="sleep", args=[1], kwargs={})
    _wait_for_status(spare, _running("sleep"))
    assert b.call("loop1", "echo", "after") == messages.Result("after")
    # A's answer was written before B's call ran: it is waiting already.
    assert a.has_data_within(0)
    assert a.receive() == messages.Result(None)
    for client in (a, b, spare):
        client.close()


def test_an_answer_goes_only_to_its_connection(start_hal):
    hal = start_hal()
    a = Client(hal.port)
    b = Client(hal.port)
    assert a.call("loop1", "echo", "for a") == messages.Result("for a")
    assert not b.has_data_within(0.5)
    a.close()
    b.close()


def test_status_is_answered_while_a_call_runs(start_hal):
    hal = start_hal()
    a = Client(hal.port)
    b = Client(hal.port)
    spare = Client(hal.port)
    assert isinstance(a.request("open", device="loop1"), messages.Opened)
    a.send("call", device="loop1", operation="sleep", args=[2], kwargs={})
    _wait_for_status(spare, _running("sleep"))
    started = time.monotonic()
    status = b.request("status")
    assert time.monotonic() - started < 0.5
    assert isinstance(status, messages.StatusReport)
    assert status.busy is not None
    assert status.busy["device"] == "loop1"
    assert status.busy["operation"] == "sleep"
    assert status.clients == 3
    assert status.queued == 0
    assert status.devices[0]["name"] == "loop1"
    assert status.devices[0]["state"] == "open"
    assert a.receive() == messages.Result(None)
    for client in (a, b, spare):
        client.close()


def test_close_all_runs_after_the_client_has_gone(start_hal, tmp_path):
    """Review Focus 1: a close_all sent, its answer never read."""
    bench, marks = _marking_bench(tmp_path)
    hal = start_hal(bench)
    client = Client(hal.port)
    assert isinstance(client.request("open", device="m1"), messages.Opened)
    client.send("close_all")
    client.close_at_once()
    assert _wait_for_last_mark(marks, "teardown", 5)


def test_a_gone_clients_queued_calls_are_dropped_but_its_close_all_runs(start_hal):
    """Review Focus 3: a stray call queued by a client that has gone does not run."""
    hal = start_hal()
    a = Client(hal.port)
    b = Client(hal.port)
    c = Client(hal.port)
    spare = Client(hal.port)
    a.send("call", device="loop1", operation="sleep", args=[2], kwargs={})
    _wait_for_status(spare, _running("sleep"))
    b.send("call", device="loop1", operation="echo", args=["stray"], kwargs={})
    _wait_for_status(spare, _queued(1))
    b.close_at_once()
    _wait_for_status(spare, _queued(0))
    c.send("close_all")
    assert c.receive() == messages.ClosedAll([])
    assert a.receive() == messages.Result(None)
    assert hal.requests_run == 2
    for client in (a, c, spare):
        client.close()


def test_a_gone_clients_close_all_still_runs_behind_a_running_call(start_hal, tmp_path):
    bench, marks = _marking_bench(tmp_path)
    hal = start_hal(bench)
    a = Client(hal.port)
    b = Client(hal.port)
    spare = Client(hal.port)
    assert isinstance(a.request("open", device="m1"), messages.Opened)
    a.send("call", device="m1", operation="hang", args=[1], kwargs={})
    _wait_for_status(spare, _running("hang"))
    b.send("close_all")
    b.close_at_once()
    assert a.receive() == messages.Result(None)
    assert _wait_for_last_mark(marks, "teardown", 10)
    a.close()
    spare.close()


def test_a_silent_client_is_dropped_and_the_bench_is_left_alone(start_hal, monkeypatch):
    monkeypatch.setattr(server, "CLIENT_SILENCE_S", 0.5)
    hal = start_hal()
    client = Client(hal.port)
    assert isinstance(client.request("open", device="loop1"), messages.Opened)
    assert client.has_data_within(3)
    assert client.receive() is None
    # The server's connection thread ends although this client keeps its end open: a frozen
    # client must not keep a thread (on Windows, shutdown() alone does not wake its read).
    deadline = time.monotonic() + 2
    while _client_threads() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _client_threads() == []
    client.close()
    other = Client(hal.port)
    assert other.hello.open == ["loop1"]
    assert other.hello.clients == 0
    other.close()


def test_a_waiting_client_is_not_dropped(start_hal, monkeypatch):
    monkeypatch.setattr(server, "CLIENT_SILENCE_S", 0.5)
    hal = start_hal()
    client = Client(hal.port)
    assert client.call("loop1", "sleep", 2) == messages.Result(None)
    client.close()


def test_shutdown_closes_every_device_then_exits(start_hal, tmp_path):
    bench, marks = _marking_bench(tmp_path)
    hal = start_hal(bench)
    client = Client(hal.port)
    assert isinstance(client.request("open", device="m1"), messages.Opened)
    assert client.request("shutdown") == messages.Bye()
    assert _wait_for_last_mark(marks, "teardown", 1)
    waiter = threading.Thread(target=hal.serve_until_stopped)
    waiter.start()
    waiter.join(timeout=30)
    assert not waiter.is_alive()
    assert client.receive() is None
    client.close()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", hal.port), timeout=5).close()


def test_a_new_client_is_refused_while_shutting_down(start_hal, tmp_path):
    bench, marks = _marking_bench(tmp_path, "slow_teardown_s = 2\n")
    hal = start_hal(bench)
    client = Client(hal.port)
    spare = Client(hal.port)
    assert isinstance(client.request("open", device="m1"), messages.Opened)
    client.send("shutdown")
    _wait_for_status(spare, _running("shutdown"))
    latecomer = Client(hal.port)
    assert latecomer.hello == SHUTTING_DOWN
    assert latecomer.receive() is None
    latecomer.close()
    assert client.receive() == messages.Bye()
    assert _wait_for_last_mark(marks, "teardown", 1)
    client.close()
    spare.close()


def test_request_exit_refuses_queued_calls_and_runs_a_queued_close_all(start_hal, tmp_path):
    """The exit of a signal (Task 5): the running call finishes, queued calls are refused."""
    bench, marks = _marking_bench(tmp_path)
    hal = start_hal(bench)
    a = Client(hal.port)
    b = Client(hal.port)
    c = Client(hal.port)
    spare = Client(hal.port)
    assert isinstance(a.request("open", device="m1"), messages.Opened)
    a.send("call", device="m1", operation="hang", args=[1], kwargs={})
    _wait_for_status(spare, _running("hang"))
    b.send("call", device="m1", operation="hang", args=[0], kwargs={})
    c.send("close_all")
    _wait_for_status(spare, _queued(2))
    hal.request_exit("test")
    assert a.receive() == messages.Result(None)
    assert b.receive() == SHUTTING_DOWN
    assert c.receive() == messages.ClosedAll([])
    waiter = threading.Thread(target=hal.serve_until_stopped)
    waiter.start()
    waiter.join(timeout=30)
    assert not waiter.is_alive()
    assert marks.read_text(encoding="utf-8").split() == ["connect", "teardown"]
    for client in (a, b, c, spare):
        client.close()


def test_a_dying_server_thread_tears_down_and_exits(start_hal, tmp_path, monkeypatch, caplog):
    def explode(self, request):
        raise RuntimeError("request thread bug")

    bench, marks = _marking_bench(tmp_path)
    hal = start_hal(bench)
    client = Client(hal.port)
    assert isinstance(client.request("open", device="m1"), messages.Opened)
    monkeypatch.setattr(HalServer, "_handle", explode)
    client.send("info", device="m1")
    assert client.receive() is None
    waiter = threading.Thread(target=hal.serve_until_stopped)
    waiter.start()
    waiter.join(timeout=30)
    assert not waiter.is_alive()
    assert marks.read_text(encoding="utf-8").split() == ["connect", "teardown"]
    assert "The HAL server thread 'HAL requests' failed." in caplog.text
    client.close()


def test_a_line_read_after_the_drop_is_not_run(start_hal):
    """A call the connection thread read just before the watchdog dropped its client."""
    hal = start_hal()
    gone = Client(hal.port)
    other = Client(hal.port)
    connection = _server_connection(hal, 0)
    hal._drop(connection, "test")
    hal._take(connection, messages.Call("loop1", "echo", ["stray"], {}))
    hal._take(connection, messages.CloseAll())
    assert other.request("close_all") == messages.ClosedAll([])
    # The gone client's close_all ran; its call did not (it would have opened loop1).
    assert hal.requests_run == 2
    assert other.request("info", device="loop1").is_open is False
    gone.close()
    other.close()


def test_a_client_that_never_reads_is_dropped(start_hal, monkeypatch):
    """A client that beats but never reads its answer must not hold the request thread."""
    monkeypatch.setattr(server, "WRITE_STALL_S", 1.0)
    hal = start_hal()
    stuck = Client(hal.port)
    connection = _server_connection(hal, 0)
    connection.sock = StallingSocket(connection.sock)
    sent_at = time.monotonic()
    stuck.send("call", device="loop1", operation="echo", args=["never read"], kwargs={})
    stop_beating = threading.Event()

    def beat() -> None:
        while not stop_beating.wait(0.2):
            try:
                stuck.send("beat")
            except OSError:
                return

    beater = threading.Thread(target=beat)
    beater.start()
    try:
        other = Client(hal.port)
        other.sock.settimeout(10)
        assert other.call("loop1", "echo", "next") == messages.Result("next")
        freed_after_s = time.monotonic() - sent_at
        if sys.platform == "win32":
            # shutdown() does not wake the stalled write here; the hang-up waited for the
            # write lock for HANG_UP_WAIT_S and then closed the handle under the write.
            assert freed_after_s > server.WRITE_STALL_S + server.HANG_UP_WAIT_S
        assert other.request("status").clients == 1
        other.close()
    finally:
        stop_beating.set()
        beater.join()
        stuck.close()


def test_a_beat_keeps_a_silent_client_connected(start_hal, monkeypatch):
    monkeypatch.setattr(server, "CLIENT_SILENCE_S", 0.5)
    hal = start_hal()
    client = Client(hal.port)
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        client.send("beat")
        time.sleep(0.1)
    assert client.call("loop1", "echo", "still here") == messages.Result("still here")
    client.close()


def test_an_answer_that_cannot_be_written_is_discarded(start_hal):
    """The write-failure path: the client is gone mid-answer, the server goes on serving."""
    hal = start_hal()
    gone = Client(hal.port)
    spare = Client(hal.port)
    gone.send("call", device="loop1", operation="sleep", args=[1], kwargs={})
    _wait_for_status(spare, _running("sleep"))
    # The server's end can no longer send, so the answer's write fails.
    _server_connection(hal, 0).sock.shutdown(socket.SHUT_WR)
    _wait_for_status(spare, lambda report: report.busy is None and report.clients == 1)
    assert spare.call("loop1", "echo", "on") == messages.Result("on")
    gone.close()
    spare.close()


class FlakyListener:
    """The server's listener, but its next accept() fails once, as a transient error does."""

    def __init__(self, real: socket.socket) -> None:
        self._real = real
        self.failures = 0

    def accept(self):
        if self.failures == 0:
            self.failures = 1
            raise ConnectionAbortedError("aborted by the peer")
        return self._real.accept()

    def close(self) -> None:
        self._real.close()


def test_a_failed_accept_does_not_stop_the_server(start_hal):
    hal = start_hal()
    flaky = FlakyListener(hal._listener)
    hal._listener = flaky
    deadline = time.monotonic() + 5
    while flaky.failures == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert flaky.failures == 1
    # Accepted after the failure: the accept thread went on, and the bench is still served.
    client = Client(hal.port)
    assert isinstance(client.hello, messages.Hello)
    assert client.call("loop1", "echo", 1) == messages.Result(1)
    client.close()


class FailingListener:
    """The server's listener, but its accept() fails `left` times in a row, then works."""

    def __init__(self, real: socket.socket, failures: int) -> None:
        self._real = real
        self.left = failures

    def accept(self):
        if self.left > 0:
            self.left = self.left - 1
            raise OSError("no handle free")
        return self._real.accept()

    def close(self) -> None:
        self._real.close()


def test_a_persistent_accept_error_warns_once_until_accept_works_again(
    start_hal, monkeypatch, caplog
):
    monkeypatch.setattr(server, "ACCEPT_RETRY_S", 0.01)
    hal = start_hal()
    flaky = FailingListener(hal._listener, 5)
    hal._listener = flaky
    with caplog.at_level(logging.DEBUG, logger="pyhal.server"):
        deadline = time.monotonic() + 5
        while flaky.left > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert flaky.left == 0
        client = Client(hal.port)
        assert isinstance(client.hello, messages.Hello)
        # Accepting works again: a new failure is a first failure, a WARNING once more.
        flaky.left = 2
        deadline = time.monotonic() + 5
        while flaky.left > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        client.close()
    records = [r for r in caplog.records if "could not accept" in r.getMessage()]
    levels = [r.levelno for r in records]
    assert levels[:5] == [logging.WARNING] + [logging.DEBUG] * 4
    assert levels[5:] == [logging.WARNING, logging.DEBUG]


def test_a_malformed_line_closes_only_that_connection(start_hal):
    hal = start_hal()
    good = Client(hal.port)
    bad = Client(hal.port)
    bad.sock.sendall(b"this is not json\n")
    answer = bad.receive()
    assert isinstance(answer, messages.Error)
    assert answer.origin == "protocol"
    assert bad.receive() is None
    bad.close()
    assert good.call("loop1", "echo", 7) == messages.Result(7)
    good.close()


def test_an_oversized_result_is_an_error_and_the_connection_stays(start_hal):
    hal = start_hal("[big1]\ndriver = hal_test_drivers.BigResultDriver\n")
    client = Client(hal.port)
    answer = client.call("big1", "big", 17)
    assert isinstance(answer, messages.Error)
    assert answer.origin == "hal"
    words = r"'big' ran, but its result is too large to send: \d+ bytes\."
    assert re.fullmatch(words, answer.message)
    result = client.call("big1", "big", 1)
    assert isinstance(result, messages.Result)
    assert len(result.value) == 1024 * 1024
    client.close()


def test_the_log_file_records_device_lines(start_hal, tmp_path):
    path = hal_log.start_log_file(tmp_path / "logs", logging.INFO)
    try:
        assert path.parent == (tmp_path / "logs").resolve()
        assert re.fullmatch(r"hal_\d{8}_\d{6}_" + str(os.getpid()) + r"\.log", path.name)
        hal = start_hal()
        client = Client(hal.port)
        assert isinstance(client.request("open", device="loop1"), messages.Opened)
        client.close()
        _stop(hal)
    finally:
        hal_log.stop_log_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert any(line.endswith(";Device 'loop1' connected.") for line in lines)
    for line in lines:
        assert hal_log.RECORD_START.match(line), line
    assert ";INFO;pyhal.connection_driver;" in "\n".join(lines)


def test_the_default_log_dir_is_pyhals_own(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert hal_log.default_log_dir() == tmp_path / "pyhal" / "logs"
    assert logging.getLevelName(hal_log.TRACE) == "TRACE"


def test_two_log_files_started_in_one_second_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # The same second for both starts, so the second name certainly collides with the first.
    monkeypatch.setattr(hal_log.time, "strftime", lambda _format: "20260101_120000")
    root = logging.getLogger()
    level_before = root.level
    handlers_before = list(root.handlers)
    first = hal_log.start_log_file(tmp_path, logging.INFO)
    second = hal_log.start_log_file(tmp_path, logging.DEBUG)
    try:
        assert first != second
        assert first.name.endswith(f"_{os.getpid()}.log")
        assert second.name.endswith(f"_{os.getpid()}_2.log")
        assert root.level == logging.DEBUG
    finally:
        # Stopped by the path as given, not resolved: each restores the level before it.
        hal_log.stop_log_file(tmp_path / second.name)
        assert root.level == logging.INFO
        hal_log.stop_log_file(Path(first.name))
    assert root.level == level_before
    assert root.handlers == handlers_before
