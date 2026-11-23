"""
Functional tests for the standalone HAL server: `python -m pyhal` and `pyhal.connect()`.

They start real HAL processes - by hand with subprocess, or detached through connect() - each
on a free port of its own (never DEFAULT_PORT) with its log folder in tmp_path. Every test
stops what it started (`python -m pyhal --stop --port N` in the `hal_port` fixture), and a
session fixture checks at the end that nothing listens on any port a test used.

Waits are synchronised on the wire or on the marks file, in bounded polling loops.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import pyhal
from pyhal import DriverError, client
from pyhal.protocol import codec, messages

DRIVERS_FILE = (
    Path(__file__).resolve().parents[1] / "unit_tests" / "hal_test_drivers.py"
).as_posix()
MARKING = f"{DRIVERS_FILE}:MarkingDriver"

#: Every port a test of this module used: none may be listening at the end of the session.
_PORTS_USED: list[int] = []


# --- helpers ---------------------------------------------------------------------------


def _free_port() -> int:
    while True:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        if port != client.DEFAULT_PORT:
            return port


def _listens(port: int) -> bool:
    """Whether something accepts on the port (a loopback connect to a listener is instant)."""
    try:
        probe = socket.create_connection(("127.0.0.1", port), timeout=1.0)
    except OSError:
        return False
    probe.close()
    return True


def _wait_until(condition, seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)


def _pyhal(*arguments: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pyhal", *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _start_by_hand(bench: Path, port: int, log_dir: Path) -> subprocess.Popen:
    """A HAL started the way a technician starts one, and waited for until it says hello."""
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pyhal",
            "--bench",
            str(bench),
            "--port",
            str(port),
            "--log-dir",
            str(log_dir),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    while _hello(port) is None:
        code = process.poll()
        assert code is None, f"the HAL on port {port} exited with code {code}"
        assert time.monotonic() < deadline, f"no HAL said hello on port {port}"
        time.sleep(0.05)
    return process


def _hello(port: int) -> messages.Hello | None:
    try:
        raw = RawClient(port)
    except OSError:
        return None
    raw.close()
    if isinstance(raw.first, messages.Hello):
        return raw.first
    return None


class RawClient:
    """One raw connection, reading the first message."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        self.sock.settimeout(60)
        self.stream = self.sock.makefile("rb")
        self.first = self.receive()

    def receive(self):
        line = codec.read_line(self.stream)
        if line is None:
            return None
        return codec.decode(line, messages.HAL_KINDS)

    def send(self, kind: str, **fields) -> None:
        message = messages.build(messages.CLIENT_KINDS, kind, **fields)
        self.sock.sendall(codec.encode(message))

    def request(self, kind: str, **fields):
        self.send(kind, **fields)
        return self.receive()

    def close(self) -> None:
        self.stream.close()
        self.sock.close()


def _marking_bench(folder: Path, name: str = "bench.ini", slow_teardown_s: float = 0) -> Path:
    marks = folder / "marks.txt"
    bench = folder / name
    bench.write_text(
        f"[m1]\ndriver = {MARKING}\nmarks = {marks.as_posix()}\n"
        f"slow_teardown_s = {slow_teardown_s}\n",
        encoding="utf-8",
    )
    return bench


def _marks(folder: Path) -> list[str]:
    path = folder / "marks.txt"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


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


# --- fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _nothing_left_listening():
    yield
    left = [port for port in _PORTS_USED if _listens(port)]
    for port in left:
        _pyhal("--stop", "--port", str(port))
    assert left == [], f"a HAL was left running on port(s) {left}"


@pytest.fixture
def hal_port():
    """A free port for this test; whatever listens on it afterwards is stopped."""
    _reset_client_module()
    port = _free_port()
    _PORTS_USED.append(port)
    yield port
    _reset_client_module()
    if _listens(port):
        _pyhal("--stop", "--port", str(port))
    _wait_until(lambda: not _listens(port), 120, f"port {port} to be free")


# --- connect or start, and the close ----------------------------------------------------


def test_connect_starts_a_hal_and_close_stops_it(hal_port, tmp_path):
    bench = _marking_bench(tmp_path)
    hal_client = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
    assert hal_client.started_hal is True
    assert hal_client.hello.nonce is not None
    assert os.path.normcase(hal_client.hello.bench) == os.path.normcase(str(bench.resolve()))
    pyhal.get_device("m1").hang(0)
    hal_client.close()
    _wait_until(lambda: not _listens(hal_port), 10, "the HAL to exit")
    assert _marks(tmp_path) == ["connect", "teardown"]
    assert (tmp_path / "logs" / "hal_startup.log").exists()


def test_start_hal_starts_a_detached_hal_and_returns_its_pid(hal_port, tmp_path):
    bench = _marking_bench(tmp_path)
    pid = client.start_hal(bench, hal_port, log_dir=str(tmp_path / "logs"))
    hello = _hello(hal_port)
    assert hello is not None
    assert hello.pid == pid
    assert pid != os.getpid()
    assert hello.nonce is not None
    assert os.path.normcase(hello.bench) == os.path.normcase(str(bench.resolve()))
    # Nothing of this process holds it: start_hal()'s connection is gone, once the HAL has
    # seen it close (it learns that asynchronously).
    _wait_until(
        lambda: _hello(hal_port) is not None and _hello(hal_port).clients == 0,
        10,
        "start_hal()'s connection to be gone",
    )
    assert (tmp_path / "logs" / "hal_startup.log").exists()
    stopped = _pyhal("--stop", "--port", str(hal_port))
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    _wait_until(lambda: not _listens(hal_port), 30, "the HAL to exit")


def test_connect_uses_a_running_hal_and_close_leaves_it_running(hal_port, tmp_path):
    bench = _marking_bench(tmp_path)
    process = _start_by_hand(bench, hal_port, tmp_path / "logs")
    try:
        hal_client = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
        assert hal_client.started_hal is False
        assert hal_client.hello.pid != os.getpid()
        pyhal.get_device("m1").hang(0)
        hal_client.close()
        _wait_until(lambda: _marks(tmp_path) == ["connect", "teardown"], 30, "the close_all")
        assert _hello(hal_port) is not None
        assert process.poll() is None
    finally:
        _pyhal("--stop", "--port", str(hal_port))
        assert process.wait(timeout=60) == 0


STARTER = """
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[4])
from pyhal import client

go = Path(sys.argv[3]) / "go"
while not go.exists():
    time.sleep(0.005)
hal_client = client.connect(sys.argv[1], int(sys.argv[2]), scope=False, log_dir=sys.argv[3])
print(json.dumps({"pid": hal_client.hello.pid, "started": hal_client.started_hal}), flush=True)
done = Path(sys.argv[3]) / "done"
while not done.exists():
    time.sleep(0.05)
hal_client.close()
"""


def test_two_starters_get_one_hal_and_one_owner(hal_port, tmp_path):
    # One client per process: two starters are two processes, as PyPTS and a script are.
    bench = _marking_bench(tmp_path)
    script = tmp_path / "starter.py"
    script.write_text(STARTER, encoding="utf-8")
    src = str(Path(pyhal.__file__).resolve().parents[1])
    starters = [
        subprocess.Popen(
            [sys.executable, str(script), str(bench), str(hal_port), str(tmp_path), src],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        time.sleep(1.0)  # both are importing and polling for "go"
        (tmp_path / "go").write_text("", encoding="utf-8")
        lines = [starter.stdout.readline() for starter in starters]
    finally:
        (tmp_path / "done").write_text("", encoding="utf-8")
        for starter in starters:
            starter.wait(timeout=60)
    answers = [json.loads(line) for line in lines]
    assert answers[0]["pid"] == answers[1]["pid"]
    assert sorted(answer["started"] for answer in answers) == [False, True]
    # The owner's close stops the HAL.
    _wait_until(lambda: not _listens(hal_port), 30, "the HAL to exit")


def test_a_bench_mismatch_warns_and_connects(hal_port, tmp_path, caplog):
    bench = _marking_bench(tmp_path)
    other = _marking_bench(tmp_path, name="other_bench.ini")
    process = _start_by_hand(bench, hal_port, tmp_path / "logs")
    try:
        with caplog.at_level(logging.WARNING, logger="pyhal.client"):
            hal_client = client.connect(other, hal_port, log_dir=str(tmp_path / "logs"))
        assert hal_client.started_hal is False
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            str(bench.resolve()) in text and str(other.resolve()) in text for text in warnings
        )
        hal_client.close()
    finally:
        _pyhal("--stop", "--port", str(hal_port))
        process.wait(timeout=60)


def test_open_devices_without_other_clients_are_a_warning(hal_port, tmp_path, caplog):
    bench = _marking_bench(tmp_path)
    process = _start_by_hand(bench, hal_port, tmp_path / "logs")
    try:
        raw = RawClient(hal_port)
        assert isinstance(raw.request("open", device="m1"), messages.Opened)
        raw.close()
        _wait_until(
            lambda: _hello(hal_port) is not None and _hello(hal_port).clients == 0,
            10,
            "the raw client to be gone",
        )
        with caplog.at_level(logging.DEBUG, logger="pyhal.client"):
            hal_client = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("m1" in text for text in warnings), warnings
        hal_client.close()
    finally:
        _pyhal("--stop", "--port", str(hal_port))
        process.wait(timeout=60)


ATEXIT_SCRIPT = """
import sys
sys.path.insert(0, sys.argv[4])
import pyhal

pyhal.connect(sys.argv[1], int(sys.argv[2]), log_dir=sys.argv[3])
pyhal.get_device("m1").hang(0)
"""


def test_atexit_closes_a_script_without_with(hal_port, tmp_path):
    bench = _marking_bench(tmp_path)
    script = tmp_path / "script.py"
    script.write_text(ATEXIT_SCRIPT, encoding="utf-8")
    src = str(Path(pyhal.__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, str(script), str(bench), str(hal_port), str(tmp_path / "logs"), src],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    _wait_until(lambda: _marks(tmp_path) == ["connect", "teardown"], 30, "the teardown")
    _wait_until(lambda: not _listens(hal_port), 30, "the HAL to exit")


def test_connect_waits_for_a_hal_that_is_shutting_down(hal_port, tmp_path):
    bench = _marking_bench(tmp_path, slow_teardown_s=3)
    process = _start_by_hand(bench, hal_port, tmp_path / "logs")
    first_pid = _hello(hal_port).pid
    raw = RawClient(hal_port)
    assert isinstance(raw.request("open", device="m1"), messages.Opened)
    raw.send("shutdown")

    def refused() -> bool:
        probe = RawClient(hal_port)
        probe.close()
        return isinstance(probe.first, messages.Error)

    _wait_until(refused, 10, "the HAL to refuse new clients")
    hal_client = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
    raw.close()
    assert hal_client.hello.pid != first_pid
    assert hal_client.started_hal is True
    assert process.wait(timeout=60) == 0
    assert _marks(tmp_path) == ["connect", "teardown"]
    hal_client.close()
    _wait_until(lambda: not _listens(hal_port), 30, "the second HAL to exit")


def test_a_second_connect_after_a_starter_waits_for_its_hal_to_exit(hal_port, tmp_path):
    # The first client started HAL A and is never closed; the second connect() closes it,
    # which sends A `shutdown`. A's slow teardown keeps it saying hello for a while: the
    # second connect must not be welcomed by A, about to exit, but start a HAL of its own.
    bench = _marking_bench(tmp_path, slow_teardown_s=2)
    first = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
    assert first.started_hal is True
    pyhal.get_device("m1").hang(0)
    second = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
    assert second.hello.pid != first.hello.pid
    assert second.started_hal is True
    assert _marks(tmp_path) == ["connect", "teardown"]
    pyhal.get_device("m1").hang(0)
    second.close()
    _wait_until(lambda: not _listens(hal_port), 30, "the second HAL to exit")


def test_a_new_hal_binds_the_same_port_right_after_one_exited(hal_port, tmp_path):
    # Windows: SO_EXCLUSIVEADDRUSE and connections left in TIME_WAIT on the port.
    bench = _marking_bench(tmp_path)
    for _ in range(3):
        process = _start_by_hand(bench, hal_port, tmp_path / "logs")
        hal_client = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
        pyhal.get_device("m1").hang(0)
        hal_client.close()
        # A client that stays connected through the exit: the HAL closes it first, so the
        # HAL's end of that connection is left in TIME_WAIT on the port.
        lingering = RawClient(hal_port)
        stopped = _pyhal("--stop", "--port", str(hal_port))
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        assert process.wait(timeout=60) == 0
        lingering.close()
    # The last one, started at once after the previous exit, also bound.
    assert not _listens(hal_port)


# --- the command line ------------------------------------------------------------------


def test_port_in_use_exits_with_code_3(hal_port, tmp_path):
    bench = _marking_bench(tmp_path)
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", hal_port))
    squatter.listen()
    try:
        completed = _pyhal(
            "--bench", str(bench), "--port", str(hal_port), "--log-dir", str(tmp_path), timeout=60
        )
    finally:
        squatter.close()
    assert completed.returncode == 3
    assert completed.stderr.strip() == (
        f"Port {hal_port} cannot be used: another HAL server or program has it, "
        "or the system reserves it. Choose another with --port."
    )


def test_stop_and_close_all_command_line(hal_port, tmp_path):
    bench = _marking_bench(tmp_path)
    process = _start_by_hand(bench, hal_port, tmp_path / "logs")
    raw = RawClient(hal_port)
    assert isinstance(raw.request("open", device="m1"), messages.Opened)
    raw.close()
    closed = _pyhal("--close-all", "--port", str(hal_port))
    assert closed.returncode == 0, closed.stderr
    assert closed.stdout.strip() == "Every device was torn down."
    assert _marks(tmp_path) == ["connect", "teardown"]
    stopped = _pyhal("--stop", "--port", str(hal_port))
    assert stopped.returncode == 0, stopped.stderr
    assert stopped.stdout.strip() == "Every device was torn down."
    assert process.wait(timeout=60) == 0
    assert not _listens(hal_port)
    nobody = _pyhal("--stop", "--port", str(hal_port))
    assert nobody.returncode == 2
    assert str(hal_port) in nobody.stderr


def test_a_hal_that_cannot_start_is_reported_with_the_startup_tail(hal_port, tmp_path):
    missing = tmp_path / "no_such_bench.ini"
    began = time.monotonic()
    with pytest.raises(DriverError) as caught:
        client.connect(missing, hal_port, log_dir=str(tmp_path / "logs"))
    # The HAL exited at once (exit 1): no wait for HAL_START_TIMEOUT_S.
    assert time.monotonic() - began < client.HAL_START_TIMEOUT_S / 2
    assert str(caught.value).startswith("The HAL server could not be started: ")
    assert "no_such_bench.ini" in str(caught.value)


def test_close_does_not_stop_a_hal_it_did_not_start(hal_port, tmp_path):
    # The client started HAL A; A went away behind its back and B was started by hand on the
    # same port. The close's short connection meets B: close_all, never shutdown.
    bench = _marking_bench(tmp_path)
    hal_client = client.connect(bench, hal_port, scope=False, log_dir=str(tmp_path / "logs"))
    assert hal_client.started_hal is True
    stopped = _pyhal("--stop", "--port", str(hal_port))
    assert stopped.returncode == 0, stopped.stderr
    _wait_until(lambda: not _listens(hal_port), 30, "HAL A to exit")
    process = _start_by_hand(bench, hal_port, tmp_path / "logs")
    try:
        raw = RawClient(hal_port)
        assert isinstance(raw.request("open", device="m1"), messages.Opened)
        raw.close()
        hal_client.close()
        # B ran the close_all (m1 torn down) and is still there.
        _wait_until(lambda: _marks(tmp_path) == ["connect", "teardown"], 30, "the close_all")
        assert _hello(hal_port) is not None
        assert process.poll() is None
    finally:
        _pyhal("--stop", "--port", str(hal_port))
        assert process.wait(timeout=60) == 0


def test_a_started_hal_does_not_hold_the_starters_folder(hal_port, tmp_path, monkeypatch):
    # Its working directory is the log folder, and the starter's folder is not on its path
    # (-P): the folder can go while the HAL runs (Windows refuses to remove a cwd in use).
    starter_folder = tmp_path / "starter"
    starter_folder.mkdir()
    monkeypatch.chdir(starter_folder)
    bench = _marking_bench(tmp_path)
    hal_client = client.connect(bench, hal_port, log_dir=str(tmp_path / "logs"))
    assert hal_client.started_hal is True
    assert "-P" in client._started_processes[-1].args
    monkeypatch.chdir(tmp_path)
    starter_folder.rmdir()
    hal_client.close()
    _wait_until(lambda: not _listens(hal_port), 30, "the HAL to exit")
