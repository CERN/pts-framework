"""
Unit tests for the HAL client (src/pyhal/client.py) and the transition dispatch
(src/pyhal/dispatch.py).

Each test runs a HalServer in threads of the test process, on a free port, with real driver
processes (the loopback driver and the ones in hal_test_drivers.py), and talks to it through
pyhal's own client. Waits are synchronised on the wire: a spare raw connection polls `status`.
"""

import logging
import multiprocessing
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import ClassVar

import pytest

import pyhal
from pyhal import DriverError, client, server
from pyhal.connection_driver import ConnectionDriver
from pyhal.device_control import DeviceInfo
from pyhal.protocol import codec, messages
from pyhal.server import HalServer

LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"
SRC = Path(__file__).resolve().parents[2] / "src"


class RawClient:
    """One raw connection, for status polling and for stopping the server."""

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


def _wait_for_status(spare: RawClient, condition, seconds: float = 10.0):
    deadline = time.monotonic() + seconds
    while True:
        report = spare.request("status")
        assert isinstance(report, messages.StatusReport)
        if condition(report):
            return report
        assert time.monotonic() < deadline, f"status never matched: {report}"
        time.sleep(0.02)


def _running(operation: str):
    def condition(report) -> bool:
        return report.busy is not None and report.busy["operation"] == operation

    return condition


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


@pytest.fixture
def start_hal(tmp_path):
    """start_hal(bench_text) -> a started HalServer on a free port; stopped afterwards."""
    _reset_client_module()
    started: list[HalServer] = []

    def start(bench_text: str = f"[loop1]\ndriver = {LOOPBACK}\n") -> HalServer:
        bench = tmp_path / "bench.ini"
        bench.write_text(bench_text, encoding="utf-8")
        hal = HalServer(bench, 0)
        hal.start()
        started.append(hal)
        return hal

    yield start
    _reset_client_module()
    for hal in started:
        _stop(hal)
    assert multiprocessing.active_children() == []
    left = [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("HAL ") and thread.is_alive()
    ]
    assert left == []


def _marking_bench(tmp_path: Path) -> tuple[str, Path]:
    marks = tmp_path / "marks.txt"
    text = (
        f"[loop1]\ndriver = {LOOPBACK}\n"
        f"[m1]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\ntag = m1\n"
        f"[m2]\ndriver = hal_test_drivers.MarkingDriver\nmarks = {marks}\ntag = m2\n"
    )
    return text, marks


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


# --- handles ---------------------------------------------------------------------


def test_get_device_calls_through_the_hal(start_hal, tmp_path):
    hal = start_hal(f"[loop1]\ndriver = {LOOPBACK}\ncolour = blue\n")
    hal_client = client.connect_only(hal.port, scope=False)
    assert isinstance(hal_client.hello, messages.Hello)
    assert hal_client.port == hal.port
    assert hal_client.started_hal is False
    with client.run_scope():
        device = client.get_device("loop1")
        assert isinstance(device, client.Device)
        assert device.echo([1, (2, 3), b"\x00", float("inf")]) == [1, [2, 3], b"\x00", float("inf")]
        assert device.settings() == {"colour": "blue"}
        assert device.echo(value="by name") == "by name"


def test_a_handle_refuses_unknown_operations_without_a_round_trip(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        before = hal.requests_run
        with pytest.raises(AttributeError) as caught:
            device.explode  # noqa: B018 - the attribute access is the test
        assert hal.requests_run == before
        known = ", ".join(device._operations)
        assert str(caught.value) == (
            f"Device 'loop1' (Other) has no operation 'explode'. It has: {known}."
        )
        with pytest.raises(AttributeError):
            device._private  # noqa: B018 - the attribute access is the test


def test_get_device_outside_a_scope_is_refused(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with pytest.raises(DriverError) as caught:
        client.get_device("loop1")
    assert str(caught.value) == (
        "No HAL scope is active. get_device() works in test code PyPTS is running, or "
        "inside 'with pyhal.connect(...)' in a script of your own."
    )


def test_run_scope_waits_for_a_pending_connect(start_hal):
    hal = start_hal()
    client.connect_pending()
    connected = threading.Event()

    def late_connect():
        time.sleep(0.5)
        client.connect_only(hal.port, scope=False)
        connected.set()

    thread = threading.Thread(target=late_connect)
    thread.start()
    try:
        with client.run_scope():
            assert connected.is_set()
            device = client.get_device("loop1")
            assert device.echo("x") == "x"
    finally:
        thread.join()


def test_a_failed_pending_connect_ends_the_wait(start_hal):
    start_hal()
    client.connect_pending()
    with pytest.raises(DriverError):
        client.connect_only(_free_port(), scope=False)
    started = time.monotonic()
    with client.run_scope():
        pass
    assert time.monotonic() - started < 5.0


def test_note_unavailable_is_what_get_device_raises(start_hal):
    client.connect_pending()
    client.note_unavailable("bench.ini was discarded at startup, so this start has no devices: bad")
    with client.run_scope(), pytest.raises(DriverError, match=r"bench\.ini was discarded"):
        client.get_device("loop1")


def test_run_scope_without_a_pending_connect_does_not_wait(start_hal):
    started = time.monotonic()
    with client.run_scope():
        pass
    assert time.monotonic() - started < 5.0


def test_run_scope_gives_up_waiting_after_connect_wait(start_hal, monkeypatch):
    monkeypatch.setattr(client, "CONNECT_WAIT_S", 0.2)
    client.connect_pending()
    started = time.monotonic()
    with client.run_scope(), pytest.raises(DriverError, match="Not connected"):
        client.get_device("loop1")
    assert 0.15 < time.monotonic() - started < 2.0


def test_get_device_without_a_client_reports_why(start_hal):
    with client.run_scope():
        with pytest.raises(DriverError) as caught:
            client.get_device("loop1")
        assert str(caught.value) == "Not connected to a HAL server."
        port = _free_port()
        with pytest.raises(DriverError) as refused:
            client.connect_only(port)
        assert str(refused.value) == f"No HAL server answered on 127.0.0.1:{port}."
        with pytest.raises(DriverError) as caught:
            client.get_device("loop1")
        assert str(caught.value) == f"No HAL server answered on 127.0.0.1:{port}."


def test_a_stale_handle_is_refused_after_the_scope_ends(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        assert device.echo(1) == 1
    with client.run_scope():
        before = hal.requests_run
        stale_text = (
            "Device 'loop1' belongs to a run that has ended; call get_device('loop1') again."
        )
        with pytest.raises(DriverError, match=re.escape(stale_text)):
            device.echo(2)
        with pytest.raises(DriverError, match=re.escape(stale_text)):
            client.recover_device(device)
        with pytest.raises(DriverError, match=re.escape(stale_text)):
            client.device_info(device)
        with pytest.raises(DriverError, match=re.escape(stale_text)):
            client.close_device(device)
        assert hal.requests_run == before
        assert client.get_device("loop1").echo(3) == 3


def test_the_scope_closes_its_devices_newest_first(start_hal, tmp_path):
    text, marks = _marking_bench(tmp_path)
    hal = start_hal(text)
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        client.get_device("m1").hang(0)
        client.get_device("m2").hang(0)
        client.get_device("m1").hang(0)
    assert marks.read_text(encoding="utf-8").splitlines() == [
        "connect m1",
        "connect m2",
        "teardown m2",
        "teardown m1",
    ]
    spare = RawClient(hal.port)
    report = spare.request("status")
    assert [row["state"] for row in report.devices] == ["configured", "configured", "configured"]
    spare.close()


def test_a_failed_close_is_a_warning_and_the_scope_does_not_raise(start_hal, caplog):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    with client.run_scope():
        client.get_device("loop1")
        hal_client._close_long_connection()
    assert "Device 'loop1' did not close: " in caplog.text


def test_recover_info_and_close_device(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        client.recover_device(device)
        info = client.device_info(device)
        assert isinstance(info, DeviceInfo)
        assert info.name == "loop1"
        assert info.device_type == "Other"
        assert "echo" in info.operations
        assert isinstance(info.operations, tuple)
        assert info.is_open is True
        client.close_device(device)
        assert client.device_info(device).is_open is False
        # D44: the next request for a closed device opens it again.
        assert device.echo(5) == 5


# --- errors ------------------------------------------------------------------------


def test_driver_and_hal_errors_reach_test_code_verbatim(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        with pytest.raises(DriverError) as caught:
            device.fail("boom")
        assert str(caught.value) == "Device 'loop1': 'fail' failed: RuntimeError: boom"
        with pytest.raises(DriverError) as caught:
            client.get_device("nope")
        assert str(caught.value).startswith("No device 'nope' is configured.")
        assert device.echo("still fine") == "still fine"


def test_unsendable_arguments_are_refused_before_sending(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        before = hal.requests_run
        with pytest.raises(DriverError) as caught:
            device.echo(object())
        assert "args[0]" in str(caught.value)
        assert str(caught.value).startswith(
            "Device 'loop1': the arguments of 'echo' cannot be sent"
        )
        assert hal.requests_run == before
        assert device.echo("works") == "works"


def test_a_protocol_error_is_logged_and_raised(start_hal, caplog):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    # Write a line the server cannot read, as a broken client would; it answers and hangs up.
    with hal_client._write_lock:
        hal_client._sock.sendall(b"not json\n")
    # Read the answer only: a request sent now could meet the reset of the hang-up.
    with hal_client._request_lock, pytest.raises(DriverError) as caught:
        hal_client._read_answer("status")
    assert str(caught.value).startswith("HAL protocol error: bad JSON")
    assert any(
        record.levelname == "ERROR" and "HAL protocol error" in record.getMessage()
        for record in caplog.records
    )


# --- the long connection ------------------------------------------------------------


def test_send_takes_plain_python(start_hal):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    assert isinstance(hal_client.send("open", device="loop1"), messages.Opened)
    answer = hal_client.send("call", device="loop1", operation="echo", args=[7], kwargs={})
    assert answer == messages.Result(7)
    with pytest.raises(ValueError):
        hal_client.send("opne", device="loop1")


def test_a_long_call_does_not_get_the_client_dropped(start_hal, monkeypatch):
    monkeypatch.setattr(server, "CLIENT_SILENCE_S", 0.5)
    monkeypatch.setattr(client, "CLIENT_BEAT_S", 0.1)
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        assert device.sleep(2) is None
        # Idle for longer than the silence limit: the beats keep the client connected.
        spare = RawClient(hal.port)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            # The client; spare asks only `status`, so it is not counted.
            assert spare.request("status").clients == 1
            time.sleep(0.05)
        spare.close()
        assert device.echo("still here") == "still here"


def test_threads_take_turns_on_the_long_connection(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    wrong: list[object] = []
    with client.run_scope():
        device = client.get_device("loop1")

        def calls(tag: str) -> None:
            for index in range(50):
                value = f"{tag}{index}"
                answer = device.echo(value)
                if answer != value:
                    wrong.append((value, answer))

        threads = [threading.Thread(target=calls, args=(tag,)) for tag in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads)
    assert wrong == []


def test_the_server_going_away_fails_the_waiting_call(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    errors: list[BaseException] = []
    with client.run_scope():
        device = client.get_device("loop1")

        def long_call() -> None:
            try:
                device.sleep(5)
            except BaseException as exc:  # noqa: BLE001 - handed to the test thread
                errors.append(exc)

        caller = threading.Thread(target=long_call)
        caller.start()
        spare = RawClient(hal.port)
        _wait_for_status(spare, _running("sleep"))
        spare.close()
        # The HAL hangs up on the client while its call runs: what the client sees when the
        # HAL process dies (an in-process server cannot be killed).
        with hal._lock:
            connection = hal._connections[0]
        hal._drop(connection, "the test hangs up")
        hal.request_exit("test")
        caller.join(timeout=30)
        assert not caller.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], DriverError)
        assert str(errors[0]) == (
            "The HAL server closed the connection while 'sleep' on device 'loop1' was running."
        )
        with pytest.raises(DriverError):
            device.echo(1)


def test_an_interrupted_wait_never_lets_the_next_request_take_its_answer(
    start_hal, monkeypatch
):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("loop1")
        real_read_answer = hal_client._read_answer
        interrupted: list[str] = []

        def interrupted_read(what: str):
            # Ctrl+C on Linux interrupts the recv: the request is sent, its answer unread.
            if not interrupted:
                interrupted.append(what)
                raise KeyboardInterrupt
            return real_read_answer(what)

        monkeypatch.setattr(hal_client, "_read_answer", interrupted_read)
        with pytest.raises(KeyboardInterrupt):
            device.echo("first")
        assert interrupted == ["'echo' on device 'loop1'"]
        with pytest.raises(DriverError) as caught:
            device.echo("second")
        assert str(caught.value) == client.CONNECTION_CLOSED


# --- the package -------------------------------------------------------------------


def test_import_pyhal_stays_light():
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import pyhal; from pyhal import PSU; "
        "print('socket' in sys.modules, 'pyhal.client' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code, str(SRC)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert completed.stdout.strip() == "False False"


def test_the_lazy_names_resolve():
    assert pyhal.DEFAULT_PORT == client.DEFAULT_PORT == 29555
    assert pyhal.HalClient is client.HalClient
    assert pyhal.run_scope is client.run_scope
    assert pyhal.close_device is client.close_device
    assert pyhal.ConnectionDriver is ConnectionDriver
    assert pyhal.DeviceInfo is DeviceInfo
    with pytest.raises(AttributeError):
        pyhal.no_such_name  # noqa: B018 - the attribute access is the test


def test_the_top_level_functions_are_the_clients(start_hal):
    hal = start_hal()
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        remote = pyhal.get_device("loop1")
        assert isinstance(remote, client.Device)
        assert remote.echo(os.getpid()) == os.getpid()
        assert pyhal.device_info(remote).is_open is True
        pyhal.recover_device(remote)
    with pytest.raises(DriverError, match="No HAL scope is active"):
        pyhal.get_device("loop1")


# --- review fixes ------------------------------------------------------------------

NESTING_REFUSED = (
    "A HAL scope is already active; run_scope() does not nest. "
    "Connect with scope=False to manage scopes yourself."
)


def test_run_scope_does_not_nest(start_hal, tmp_path):
    text, marks = _marking_bench(tmp_path)
    hal = start_hal(text)
    client.connect_only(hal.port, scope=False)
    with client.run_scope():
        device = client.get_device("m1")
        with pytest.raises(DriverError) as caught, client.run_scope():
            pass
        assert str(caught.value) == NESTING_REFUSED
        # The outer scope is untouched: its handle works, its device is still closed at its exit.
        device.hang(0)
    assert marks.read_text(encoding="utf-8").splitlines() == ["connect m1", "teardown m1"]
    # A script's scope (connect_only with scope=True) is refused the same way.
    _reset_client_module()
    client.connect_only(hal.port, scope=True)
    script_device = client.get_device("loop1")
    with pytest.raises(DriverError, match=re.escape(NESTING_REFUSED)), client.run_scope():
        pass
    assert script_device.echo(1) == 1


def test_close_while_a_call_waits_says_the_client_closed(start_hal):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    errors: list[BaseException] = []
    with client.run_scope():
        device = client.get_device("loop1")

        def long_call() -> None:
            try:
                device.sleep(3)
            except BaseException as exc:  # noqa: BLE001 - handed to the test thread
                errors.append(exc)

        caller = threading.Thread(target=long_call)
        caller.start()
        spare = RawClient(hal.port)
        _wait_for_status(spare, _running("sleep"))
        hal_client.close()
        caller.join(timeout=30)
        assert not caller.is_alive()
        assert len(errors) == 1
        assert str(errors[0]) == "The connection to the HAL server is closed."
        # The server finishes the call and discards its answer; nothing is left running.
        # spare asks only `status`: once the closed client is gone, no client is counted.
        _wait_for_status(spare, lambda report: report.busy is None and report.clients == 0)
        spare.close()


def test_a_call_racing_the_scope_exit_finishes_before_the_closes(start_hal, tmp_path):
    text, marks = _marking_bench(tmp_path)
    hal = start_hal(text)
    client.connect_only(hal.port, scope=False)
    results: list[object] = []
    scope_ended = threading.Event()
    with client.run_scope():
        device = client.get_device("m1")

        def racing_call() -> None:
            results.append(device.hang_marked(2))
            scope_ended.wait(30)
            try:
                device.hang(0)
            except DriverError as exc:
                results.append(str(exc))

        caller = threading.Thread(target=racing_call)
        caller.start()
        spare = RawClient(hal.port)
        _wait_for_status(spare, _running("hang_marked"))
        spare.close()
    # The scope's exit waited behind the call: the call's own mark, written at the end of
    # hang_marked(), is in the file before the close's teardown mark - in the file's order,
    # whatever the timing of the test thread.
    assert marks.read_text(encoding="utf-8").splitlines() == [
        "connect m1",
        "hang done m1",
        "teardown m1",
    ]
    scope_ended.set()
    caller.join(timeout=30)
    assert not caller.is_alive()
    assert results == [
        None,
        "Device 'm1' belongs to a run that has ended; call get_device('m1') again.",
    ]


# --- the close (Task 5) ----------------------------------------------------------------


def test_close_ends_a_script_scope_and_is_idempotent(start_hal, tmp_path):
    text, marks = _marking_bench(tmp_path)
    hal = start_hal(text)
    hal_client = client.connect_only(hal.port, scope=True)
    device = pyhal.get_device("m1")
    device.hang(0)
    hal_client.close()
    # The scope ended with the client: the dispatch no longer routes to it.
    assert client._scope_is_active() is False
    with pytest.raises(DriverError, match="No HAL scope is active"):
        pyhal.get_device("m1")
    with pytest.raises(DriverError, match="belongs to a run that has ended"):
        device.hang(0)
    hal_client.close()
    # The close sent close_all on a short connection (this client did not start the HAL).
    spare = RawClient(hal.port)
    _wait_for_status(spare, lambda report: report.devices[1]["state"] == "configured")
    spare.close()
    assert marks.read_text(encoding="utf-8").splitlines() == [
        "connect m1",
        "teardown m1",
    ]


def test_closing_a_client_that_started_the_hal_sends_shutdown(start_hal):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    hal_client.started_hal = True
    hal_client.close()
    assert hal._exited.wait(30)
    assert hal._exit_reason == "shutdown"


def test_a_new_connect_after_a_shutdown_is_never_welcomed_by_the_exiting_hal(
    start_hal, monkeypatch
):
    hal = start_hal()
    first = client.connect_only(hal.port, scope=False)
    first.started_hal = True
    real_take = hal._take

    def slow_take(connection, request) -> None:
        # The HAL reads the parting `shutdown` late: until then it still says hello.
        if isinstance(request, messages.Shutdown):
            time.sleep(1.0)
        real_take(connection, request)

    monkeypatch.setattr(hal, "_take", slow_take)
    # The new connect closes the first client, which sends `shutdown`, and must wait for
    # that HAL to exit: nothing is left listening, so connect_only() finds no HAL.
    with pytest.raises(DriverError) as caught:
        client.connect_only(hal.port, scope=False)
    assert str(caught.value) == f"No HAL server answered on 127.0.0.1:{hal.port}."
    assert hal._exited.is_set()
    assert hal._exit_reason == "shutdown"


def test_the_close_with_nothing_listening_is_a_debug_line(start_hal, caplog):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    hal.request_exit("test")
    assert hal._exited.wait(30)
    with caplog.at_level("DEBUG", logger="pyhal.client"):
        hal_client.close()
    levels = [record.levelno for record in caplog.records if record.name == "pyhal.client"]
    assert levels and max(levels) == logging.DEBUG
    assert "nothing was sent" in caplog.text


def _one_bad_answer(first_bytes: bytes) -> tuple[socket.socket, threading.Thread]:
    """A listener on a free port that accepts once, writes `first_bytes` and hangs up."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def answer_once() -> None:
        connection, _address = listener.accept()
        with connection:
            if first_bytes:
                connection.sendall(first_bytes)

    thread = threading.Thread(target=answer_once)
    thread.start()
    return listener, thread


@pytest.mark.parametrize("first_bytes", [b"", b"not json\n"], ids=["no hello", "bad hello"])
def test_a_close_the_hal_did_not_take_is_a_warning(start_hal, caplog, first_bytes):
    hal = start_hal()
    hal_client = client.connect_only(hal.port, scope=False)
    listener, thread = _one_bad_answer(first_bytes)
    port = listener.getsockname()[1]
    # The short connection reaches something that does not answer as a HAL should.
    hal_client.port = port
    try:
        with caplog.at_level("DEBUG", logger="pyhal.client"):
            hal_client.close()
    finally:
        thread.join(timeout=10)
        listener.close()
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        "The HAL server did not take the close_all; devices may still be open. "
        f"Run 'python -m pyhal --close-all --port {port}' to close them."
    ]


def test_connect_registers_its_close_at_exit_and_close_unregisters_it(
    start_hal, monkeypatch, tmp_path
):
    hal = start_hal()
    registered: list[object] = []
    monkeypatch.setattr(client.atexit, "register", registered.append)
    monkeypatch.setattr(client.atexit, "unregister", registered.remove)
    hal_client = client.connect(hal._bench_path, hal.port, log_dir=str(tmp_path / "logs"))
    assert hal_client.started_hal is False
    assert registered == [hal_client.close]
    hal_client.close()
    assert registered == []
    hal_client.close()


def test_connect_is_a_lazy_name():
    assert pyhal.connect is client.connect
    assert "connect" in pyhal.__all__


# --- the log tail ----------------------------------------------------------------


def _record(level: str, text: str) -> str:
    return f"2026-11-23 10:00:00.123;{level};pyhal.test;{text}\n"


def _wait_for(sink_records: list, count: int, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while len(sink_records) < count:
        assert time.monotonic() < deadline, f"the sink got only {sink_records}"
        time.sleep(0.02)


def _append(path: Path, text: str) -> None:
    with open(path, "ab") as file:
        file.write(text.encode("utf-8"))


def test_the_tail_passes_new_records_with_their_level(tmp_path):
    path = tmp_path / "hal.log"
    path.write_text(_record("INFO", "written before the connect"), encoding="utf-8")
    got: list[tuple[int, str]] = []
    tail = client.LogTail(str(path), lambda level, text: got.append((level, text)))
    tail.start()
    try:
        _append(path, _record("WARNING", "one"))
        _append(path, _record("TRACE", "two; with a semicolon"))
        _append(path, _record("ODD", "three"))
        _append(path, _record("ERROR", "four"))
        # The last record is held until it is known to be whole (a quiet poll) or drained.
        _wait_for(got, 4)
    finally:
        tail.stop()
    assert got == [
        (logging.WARNING, "one"),
        (5, "two; with a semicolon"),
        (logging.INFO, "three"),
        (logging.ERROR, "four"),
    ]
    assert not [t for t in threading.enumerate() if t.name == "HAL log tail"]


def test_drain_passes_the_last_record_at_once(tmp_path):
    path = tmp_path / "hal.log"
    path.write_text("", encoding="utf-8")
    got: list[tuple[int, str]] = []
    tail = client.LogTail(str(path), lambda level, text: got.append((level, text)))
    tail.start()
    try:
        _append(path, _record("INFO", "first") + _record("INFO", "last"))
        tail.drain()
        assert got == [(logging.INFO, "first"), (logging.INFO, "last")]
        # A line without its newline yet is not a record: it waits.
        _append(path, "2026-11-23 10:00:01.000;INFO;pyhal.test;half")
        tail.drain()
        assert len(got) == 2
        _append(path, " a line\n")
        tail.drain()
        tail.drain()
    finally:
        tail.stop()
    assert got[2:] == [(logging.INFO, "half a line")]


def test_a_multi_line_record_arrives_whole(tmp_path):
    path = tmp_path / "hal.log"
    path.write_text("", encoding="utf-8")
    got: list[tuple[int, str]] = []
    tail = client.LogTail(str(path), lambda level, text: got.append((level, text)))
    tail.start()
    try:
        _append(
            path,
            _record("ERROR", "It failed:\nTraceback (most recent call last):\n  File x\nOops: ä")
            + _record("INFO", "next"),
        )
        tail.drain()
    finally:
        tail.stop()
    assert got == [
        (logging.ERROR, "It failed:\nTraceback (most recent call last):\n  File x\nOops: ä"),
        (logging.INFO, "next"),
    ]


def test_a_raising_sink_and_a_missing_file_do_not_kill_the_tail(tmp_path, caplog):
    path = tmp_path / "later.log"
    calls: list[str] = []

    def sink(level: int, text: str) -> None:
        calls.append(text)
        raise RuntimeError("sink broke")

    tail = client.LogTail(str(path), sink)
    with caplog.at_level("DEBUG", logger="pyhal.client"):
        tail.start()
        try:
            tail.drain()  # no file yet: quiet
            path.write_text(_record("INFO", "a") + _record("INFO", "b"), encoding="utf-8")
            tail.drain()
        finally:
            tail.stop()
    assert calls == ["a", "b"]
    assert max(r.levelno for r in caplog.records if r.name == "pyhal.client") == logging.DEBUG


def test_a_file_that_shrinks_is_read_again_from_its_start(tmp_path):
    path = tmp_path / "hal.log"
    path.write_text(_record("INFO", "a long first record of the old file"), encoding="utf-8")
    got: list[tuple[int, str]] = []
    tail = client.LogTail(str(path), lambda level, text: got.append((level, text)))
    tail.start()
    try:
        _append(path, _record("INFO", "before"))
        tail.drain()
        # The file is replaced by a shorter one: the offset is past its end.
        path.write_text(_record("INFO", "after"), encoding="utf-8")
        tail.drain()
    finally:
        tail.stop()
    assert got == [(logging.INFO, "before"), (logging.INFO, "after")]


def test_a_read_failure_is_logged_again_after_a_successful_read(tmp_path, caplog):
    path = tmp_path / "later.log"
    tail = client.LogTail(str(path), lambda level, text: None)
    with caplog.at_level("DEBUG", logger="pyhal.client"):
        tail.start()
        try:
            tail.drain()
            tail.drain()
            path.write_text(_record("INFO", "a"), encoding="utf-8")
            tail.drain()
            path.unlink()
            tail.drain()
        finally:
            tail.stop()
    complaints = [r for r in caplog.records if "cannot be read yet" in r.getMessage()]
    assert len(complaints) == 2


def test_the_scope_drains_the_teardown_lines(tmp_path):
    from pyhal import hal_log

    _reset_client_module()
    text, _marks = _marking_bench(tmp_path)
    bench = tmp_path / "bench.ini"
    bench.write_text(text, encoding="utf-8")
    log_path = hal_log.start_log_file(tmp_path / "logs", logging.INFO)
    hal = HalServer(bench, 0, log_path=str(log_path))
    hal.start()
    got: list[tuple[int, str]] = []
    try:
        hal_client = client.connect(
            bench, hal.port, scope=False, log_sink=lambda level, text: got.append((level, text))
        )
        with client.run_scope():
            client.get_device("m1").hang(0)
        assert (logging.INFO, "Device 'm1' disconnected.") in got
        hal_client.close()
        assert not [t for t in threading.enumerate() if t.name == "HAL log tail"]
    finally:
        _reset_client_module()
        _stop(hal)
        hal_log.stop_log_file(log_path)


class _FakeProcess:
    """What _launch() returns as the started process: one that keeps running."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None


def test_started_hal_follows_the_nonce_not_the_pid(start_hal, monkeypatch, tmp_path):
    # The HAL that answers has the pid of the process "started" (the HAL runs in this
    # process's threads) but not this start's nonce: another HAL, never to be shut down.
    hal = start_hal()
    hal._nonce = "foreign"

    def fake_launch(bench_path, port, log_level, log_dir, **options):
        return client._Launched(_FakeProcess(os.getpid()), "mine", tmp_path / "startup.log", 0)

    monkeypatch.setattr(client, "_launch", fake_launch)
    hal_client = client._start_hal(str(tmp_path / "bench.ini"), hal.port, None, None)
    try:
        assert hal_client.hello.pid == os.getpid()
        assert hal_client.hello.nonce == "foreign"
        assert hal_client.started_hal is False
    finally:
        hal_client._close_long_connection()
    with pytest.raises(client._AnotherHal):
        client.start_hal(tmp_path / "bench.ini", hal.port)


class _RecordingPopen:
    """Stands in for subprocess.Popen in _launch(): records the command, starts nothing."""

    commands: ClassVar[list[list[str]]] = []

    def __init__(self, command, **options) -> None:
        _RecordingPopen.commands.append(list(command))
        self.pid = 4242
        self.args = command

    def poll(self):
        return None


@pytest.mark.parametrize("window", [False, True])
def test_launch_runs_the_hal_with_or_without_its_window(monkeypatch, tmp_path, window):
    _RecordingPopen.commands = []
    monkeypatch.setattr(client.subprocess, "Popen", _RecordingPopen)
    monkeypatch.setattr(client, "_started_processes", [])
    launched = client._launch("C:/bench.ini", 29600, 5, str(tmp_path), window=window)
    command = _RecordingPopen.commands[0]
    # Always the HAL itself: the monitor never starts a HAL (user decision 2026-11-24).
    assert command[1:4] == ["-P", "-m", "pyhal"]
    expected = ["--bench", "C:/bench.ini", "--port", "29600", "--nonce", launched.nonce]
    expected = [*expected, "--log-level", "5", "--log-dir", str(tmp_path.resolve())]
    if window:
        expected = [*expected, "--window"]
    assert command[4:] == expected
    assert launched.startup_path == tmp_path.resolve() / "hal_startup.log"


def test_launch_makes_a_fresh_nonce_each_time(monkeypatch, tmp_path):
    _RecordingPopen.commands = []
    monkeypatch.setattr(client.subprocess, "Popen", _RecordingPopen)
    monkeypatch.setattr(client, "_started_processes", [])
    first = client._launch("C:/bench.ini", 29600, None, str(tmp_path))
    second = client._launch("C:/bench.ini", 29600, None, str(tmp_path))
    assert first.nonce != second.nonce
    assert len(first.nonce) == 32
    assert _RecordingPopen.commands[0][1:4] == ["-P", "-m", "pyhal"]
    assert "--window" not in _RecordingPopen.commands[0]


@pytest.mark.parametrize("show_window", [False, True])
def test_start_hal_asks_for_the_window_through_the_hal(
    start_hal, monkeypatch, tmp_path, show_window
):
    hal = start_hal()
    windows: list[bool] = []

    def fake_launch(bench_path, port, log_level, log_dir, *, window=False):
        windows.append(window)
        return client._Launched(_FakeProcess(os.getpid()), hal._nonce, tmp_path / "s.log", 0)

    monkeypatch.setattr(client, "_launch", fake_launch)
    hal_client = client._start_hal(
        str(tmp_path / "bench.ini"), hal.port, None, None, show_window=show_window
    )
    try:
        assert hal_client.started_hal is True
    finally:
        hal_client._close_long_connection()
    assert windows == [show_window]


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


def test_open_devices_with_only_a_status_poller_are_still_a_warning(start_hal, tmp_path, caplog):
    # PyPTS killed mid-test, restarted, with the HAL's monitor window polling `status`: the
    # window's connection must not pass for a client using the devices (D40).
    bench_text, _marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text)
    opener = RawClient(hal.port)
    assert isinstance(opener.request("open", device="m1"), messages.Opened)
    opener.close()
    poller = RawClient(hal.port)
    assert isinstance(poller.request("status"), messages.StatusReport)
    _wait_for_connections(hal, 1)
    try:
        with caplog.at_level(logging.WARNING, logger="pyhal.client"):
            hal_client = client.connect(tmp_path / "bench.ini", hal.port, scope=False)
        hal_client.close()
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("has devices open that no client is using: m1" in text for text in warnings)
    finally:
        poller.close()


def test_connect_closes_its_client_when_it_fails_after_connecting(
    start_hal, tmp_path, monkeypatch
):
    bench_text, marks = _marking_bench(tmp_path)
    hal = start_hal(bench_text)
    opener = RawClient(hal.port)
    assert isinstance(opener.request("open", device="m1"), messages.Opened)

    def broken_compare(hello, bench_path, port):
        raise RuntimeError("compare broke")

    monkeypatch.setattr(client, "_compare_hello", broken_compare)
    with pytest.raises(RuntimeError, match="compare broke"):
        client.connect(tmp_path / "bench.ini", hal.port, scope=False)
    # The client was closed: its parting request (close_all, it did not start this HAL)
    # closed the open device, and it is not the process's client.
    _wait_for_status(opener, lambda report: report.devices[1]["state"] == "configured")
    assert "teardown m1" in marks.read_text(encoding="utf-8").splitlines()
    with client._state_lock:
        assert client._client is None
    opener.close()
