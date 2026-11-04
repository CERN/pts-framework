"""
Unit tests for ConnectionDriver (src/pypts/hal/connection_driver.py) against
real driver processes - the loopback driver, and the broken ones in
hal_test_drivers.py.

Each test starts at least one process, so each costs a fraction of a second.
"""

import ctypes
import logging
import os
import subprocess
import sys
import threading
import time

import pytest
from hal_test_drivers import TwoArgumentError

from pypts.hal import DriverError, connection_driver, device_info, recover_device
from pypts.hal.connection_driver import ConnectionDriver

LOOPBACK ="pypts.hal.drivers.loopback.LoopbackDriver"


@pytest.fixture
def device():
    connection = ConnectionDriver("loop1", LOOPBACK, {"mode": "test"})
    connection._open()
    yield connection
    connection._close()


def test_open_says_hello_and_connects(device):
    info = device_info(device)
    assert info.name == "loop1"
    assert info.is_open
    assert info.device_type == "Other"
    assert "echo" in info.operations
    assert device.is_connected() is True
    assert device.settings() == {"mode": "test"}


def test_device_info_of_a_device_not_yet_open():
    info = device_info(ConnectionDriver("loop1", LOOPBACK, {}))
    assert info.is_open is False
    assert info.device_type == ""
    assert info.operations == ()


def test_operations_named_like_the_lifecycle_reach_the_driver():
    """No name is reserved: close, open and name are the driver's operations."""
    connection = ConnectionDriver("relay1", "hal_test_drivers.CommonNamesDriver", {})
    connection._open()
    try:
        assert connection.name() == "ACME relay"
        assert connection.close() == "relay closed"
        assert connection.relay() == "closed"
        # The driver's close() ended nothing: the device is still open.
        assert device_info(connection).is_open
        assert connection.open() == "relay open"
        assert connection.relay() == "open"
    finally:
        connection._close()
    assert not device_info(connection).is_open


def test_an_operation_runs_in_another_process(device):
    assert device.echo({"a": [1, 2.5, None]}) == {"a": [1, 2.5, None]}
    assert device.process_id() != os.getpid()


def test_non_ascii_and_large_values_round_trip(device):
    assert device.echo("5 µA ± 2 °C") == "5 µA ± 2 °C"
    big = "x" * 1_000_000
    assert device.echo(big) == big


def test_a_driver_exception_is_a_driver_error_and_the_device_stays_usable(device):
    with pytest.raises(DriverError, match=r"Device 'loop1': 'fail' failed: RuntimeError: nope"):
        device.fail("nope")
    assert device.echo(1) == 1


def test_an_unknown_operation_is_an_attribute_error(device):
    with pytest.raises(AttributeError, match="has no operation 'nope'"):
        device.nope()
    assert not hasattr(device, "nope")


def test_an_argument_pickle_cannot_carry_is_refused_before_sending(device):
    """Review Focus 3."""
    with pytest.raises(DriverError, match="the arguments of 'echo' cannot be sent"):
        device.echo(lambda: 1)
    assert device.echo(2) == 2


def test_a_return_value_pickle_cannot_carry_is_a_driver_error():
    """Review Focus 3."""
    connection = ConnectionDriver("odd1", "hal_test_drivers.UnsendableResultDriver", {})
    connection._open()
    try:
        with pytest.raises(DriverError, match="'lock' returned a value that cannot be sent"):
            connection.lock()
        assert connection.ping() == "pong"
    finally:
        connection._close()


def test_driver_log_records_reach_the_run_log(caplog):
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection._open()
    try:
        connection.log_message("relay 3 closed")
    finally:
        connection._close()
    records = [r for r in caplog.records if r.getMessage() == "Device 'loop1': relay 3 closed"]
    assert records
    assert records[0].levelno == logging.INFO


def test_a_driver_file_runs_in_its_own_process_and_keeps_its_log_level(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    path = tmp_path / "bench_file_driver.py"
    path.write_text(
        "import logging\n"
        "from pypts.hal import Other\n"
        "log = logging.getLogger(__name__)\n"
        "class FileDriver(Other):\n"
        "    def connect(self, config):\n"
        "        log.info('file driver connected')\n"
        "    def teardown(self):\n"
        "        pass\n"
        "    def pid(self):\n"
        "        import os\n"
        "        return os.getpid()\n",
        encoding="utf-8",
    )
    connection = ConnectionDriver("file1", f"{path}:FileDriver", {})
    connection._open()
    try:
        assert connection.pid() != os.getpid()
    finally:
        connection._close()
    records = [
        r for r in caplog.records if r.getMessage() == "Device 'file1': file driver connected"
    ]
    assert records
    assert records[0].levelno == logging.INFO


def test_printed_output_is_logged_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection._open()
    try:
        connection.print_text("vendor banner")
    finally:
        connection._close()
    wanted = "Device 'loop1' printed: vendor banner"
    records = [r for r in caplog.records if r.getMessage() == wanted]
    assert records
    assert records[0].levelno == logging.DEBUG


def test_a_call_that_takes_too_long_stops_the_process():
    connection = ConnectionDriver("loop1", LOOPBACK, {}, call_timeout_s=0.5)
    connection._open()
    try:
        with pytest.raises(DriverError, match="did not answer 'sleep' within"):
            connection.sleep(10)
        assert not connection._is_open()
    finally:
        connection._close()


def test_a_crash_is_a_driver_error_with_the_exit_code():
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection._open()
    try:
        with pytest.raises(DriverError, match=r"stopped unexpectedly \(exit code 3\)"):
            connection.crash(3)
        assert not connection._is_open()
        with pytest.raises(DriverError, match="is not open"):
            connection.echo(1)
    finally:
        connection._close()


def test_recover_starts_a_fresh_process_after_a_crash():
    connection = ConnectionDriver("loop1", LOOPBACK, {"mode": "test"})
    connection._open()
    try:
        first = connection.process_id()
        with pytest.raises(DriverError):
            connection.crash(1)
        recover_device(connection)
        assert connection.process_id() != first
        assert connection.settings() == {"mode": "test"}
    finally:
        connection._close()


def test_recover_on_a_live_process_keeps_the_process(device):
    first = device.process_id()
    recover_device(device)
    assert device.process_id() == first
    assert device.is_connected() is True


def test_recover_escalates_to_a_fresh_process_when_the_driver_cannot(caplog):
    """The driver's own recover() raised: the device is reconnected on a fresh process."""
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("odd1", "hal_test_drivers.FailingRecoverDriver", {})
    connection._open()
    try:
        first = connection.process_id()
        recover_device(connection)
        assert connection.process_id() != first
        assert connection.ping() == "pong"
    finally:
        connection._close()
    assert any(
        record.levelno == logging.WARNING
        and "did not recover and is being connected again" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize(
    ("driver_path", "words"),
    [
        ("pypts.hal.drivers.nothing.Here", "No module named"),
        ("hal_test_drivers.NoDeviceTypeDriver", "belongs to no device type"),
        ("hal_test_drivers.BrokenConstructorDriver", "constructor exploded"),
        ("hal_test_drivers.FailingConnectDriver", "instrument is switched off"),
    ],
)
def test_a_device_that_cannot_open_says_why_and_leaves_nothing_running(driver_path, words):
    connection = ConnectionDriver("bad1", driver_path, {})
    with pytest.raises(DriverError, match=words):
        connection._open()
    assert not connection._is_open()
    connection._close()


def test_close_is_safe_twice_and_before_open():
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection._close()
    connection._open()
    connection._close()
    connection._close()
    assert not connection._is_open()


def test_opening_an_open_device_is_refused_and_keeps_the_process(device):
    first = device.process_id()
    with pytest.raises(DriverError, match="Device 'loop1' is already open"):
        device._open()
    assert device.process_id() == first


def test_a_long_value_is_cut_in_the_trace_but_returned_whole(caplog):
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection._open()
    try:
        big = "y" * 10_000
        assert connection.echo(big) == big
    finally:
        connection._close()
    assert caplog.records
    for record in caplog.records:
        assert len(record.getMessage()) < 600


def test_the_driver_process_ends_when_its_pipe_closes():
    """Review Focus 2: PyPTS dying must take the driver process with it.

    Closing PyPTS's end of the Pipe is what the operating system does when
    PyPTS dies; the driver process must see it, tear down and exit.
    """
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection._open()
    process = connection._process
    pipe_end = connection._conn
    assert process is not None
    assert pipe_end is not None
    pipe_end.close()
    process.join(10.0)
    assert process.exitcode == 0
    connection._conn = None
    connection._process = None


DIES_AT_START = '''
import time
from pypts.hal import DriverError, connection_driver
from pypts.hal.connection_driver import ConnectionDriver

from hal_test_drivers import TwoArgumentError

if __name__ != "__main__":
    raise RuntimeError("the driver process dies while it re-imports this script")

connection_driver.STARTUP_TIMEOUT_S = 20.0
began = time.monotonic()
try:
    ConnectionDriver("loop1", "pypts.hal.drivers.loopback.LoopbackDriver", {})._open()
except DriverError as exc:
    print("seconds=%.1f" % (time.monotonic() - began))
    print(exc)
'''


def test_a_driver_process_that_dies_before_it_starts_is_noticed_at_once(tmp_path):
    """
    A driver process that dies before it takes over its end of the Pipe - an
    unguarded standalone script, re-imported by spawn - closes nothing PyPTS
    can see on Windows. Its death must still be noticed, not waited out.
    """
    script = tmp_path / "dies_at_start.py"
    script.write_text(DIES_AT_START, encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    finished = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    assert "stopped unexpectedly (exit code 1)" in finished.stdout
    seconds = float(finished.stdout.split("seconds=")[1].split()[0])
    assert seconds < 10.0


@pytest.fixture
def odd_device():
    connection = ConnectionDriver("odd1", "hal_test_drivers.OddValuesDriver", {})
    connection._open()
    yield connection
    connection._close()


def test_an_argument_pickle_refuses_with_any_error_is_a_driver_error(device):
    """ctypes refuses with ValueError, not with one of pickle's usual errors."""
    with pytest.raises(DriverError, match="Device 'loop1': the arguments of 'echo' cannot be sent"):
        device.echo(ctypes.pointer(ctypes.c_int(1)))
    assert device.echo(2) == 2


def test_an_argument_the_driver_process_cannot_read_is_a_driver_error(device):
    words = r"Device 'loop1': 'echo' failed: TypeError: .*not be read"
    with pytest.raises(DriverError, match=words):
        device.echo(TwoArgumentError(1, 2))
    assert device.echo(3) == 3


def test_a_return_value_pickle_refuses_with_any_error_is_a_driver_error(odd_device):
    with pytest.raises(DriverError, match="'pointer' returned a value that cannot be sent"):
        odd_device.pointer()
    assert odd_device.ping() == "pong"


def test_a_return_value_pypts_cannot_read_is_a_driver_error(odd_device):
    words = r"Device 'odd1': .*'two_argument_error'.*could not be read"
    with pytest.raises(DriverError, match=words):
        odd_device.two_argument_error()
    assert odd_device.ping() == "pong"


# --------------------------------------------------------------------------
# Making a device safe when its driver is stuck or its run is abandoned
# --------------------------------------------------------------------------

MARKING = "hal_test_drivers.MarkingDriver"


def marks_of(path):
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").split()


@pytest.fixture
def marking(tmp_path):
    """A device whose connect() and teardown() can be seen, even in a fresh process."""
    marks = tmp_path / "marks.txt"
    connection = ConnectionDriver("psu1", MARKING, {"marks": str(marks)}, call_timeout_s=0.5)
    connection._open()
    yield connection, marks
    connection._close()


def test_a_normal_close_runs_teardown_exactly_once(tmp_path):
    """close() sends teardown as a call; the driver process's own net must not repeat it."""
    marks = tmp_path / "marks.txt"
    connection = ConnectionDriver("psu1", MARKING, {"marks": str(marks)})
    connection._open()

    connection._close()

    assert marks_of(marks) == ["connect", "teardown"]


def test_a_pipe_that_closes_without_a_teardown_call_still_tears_down(tmp_path):
    """PyPTS died without a close(): the driver process's own net runs teardown."""
    marks = tmp_path / "marks.txt"
    connection = ConnectionDriver("psu1", MARKING, {"marks": str(marks)})
    connection._open()
    process = connection._process
    pipe_end = connection._conn
    assert process is not None
    assert pipe_end is not None

    pipe_end.close()
    process.join(10.0)

    assert process.exitcode == 0
    assert marks_of(marks) == ["connect", "teardown"]
    connection._conn = None
    connection._process = None


def test_a_call_that_times_out_only_stops_the_process_until_close(marking):
    """No inline rescue: the timeout kills and reports; close() owns the ladder."""
    connection, marks = marking

    with pytest.raises(DriverError, match="its driver process was stopped"):
        connection.hang(30)

    assert not connection._is_open()
    # The stuck process never tore down, and nothing reconnected yet.
    assert marks_of(marks) == ["connect"]


def test_closing_a_device_whose_process_was_stopped_tears_it_down_on_a_fresh_connection(marking):
    """The second rung of the ladder: close() reconnects and tears down."""
    connection, marks = marking
    with pytest.raises(DriverError, match="its driver process was stopped"):
        connection.hang(30)

    connection._close()

    assert not connection._is_open()
    assert marks_of(marks) == ["connect", "connect", "teardown"]


def test_a_close_rescue_that_cannot_connect_is_bounded_and_said(marking, monkeypatch, caplog):
    """The last rung: the rescue fails, the ERROR says so, and nothing tries again."""
    connection, marks = marking
    monkeypatch.setattr(connection_driver, "RESCUE_TIMEOUT_S", 1.0)
    with pytest.raises(DriverError, match="its driver process was stopped"):
        connection.hang(30)
    (marks.parent / (marks.name + ".hang")).write_text("", encoding="utf-8")
    began = time.monotonic()

    connection._close()

    # The rescue's 1 s and the kills - nowhere near the hang.
    assert time.monotonic() - began < 10.0
    assert marks_of(marks) == ["connect"]
    assert any(
        record.levelno == logging.ERROR and "may still be energised" in record.getMessage()
        for record in caplog.records
    )


def test_abandoning_an_idle_device_tears_it_down(marking):
    connection, marks = marking

    assert connection._abandon() is True

    assert not connection._is_open()
    assert marks_of(marks) == ["connect", "teardown"]


def test_an_abandoned_device_cannot_be_opened_or_recovered_again(marking):
    """The run was abandoned: nothing would ever tear a new driver process down."""
    connection, marks = marking

    assert connection._abandon() is True

    with pytest.raises(DriverError, match="its run was abandoned"):
        recover_device(connection)
    with pytest.raises(DriverError, match="its run was abandoned"):
        connection._open()
    assert not connection._is_open()
    # The teardown of abandon() ran; nothing ever connected again.
    assert marks_of(marks) == ["connect", "teardown"]


def test_abandoning_a_device_whose_teardown_hangs_once_rescues_it(marking, monkeypatch):
    """The ladder's second rung: the hung teardown is killed, a fresh process tears down."""
    connection, marks = marking
    monkeypatch.setattr(connection_driver, "ABANDON_TEARDOWN_TIMEOUT_S", 0.5)
    (marks.parent / (marks.name + ".tdhang_once")).write_text("", encoding="utf-8")
    began = time.monotonic()

    assert connection._abandon() is True

    # One timeout, the kill, and the rescue - nowhere near the hang.
    assert time.monotonic() - began < 15.0
    assert not connection._is_open()
    # The hung teardown never marked; the fresh process connected and did.
    assert marks_of(marks) == ["connect", "connect", "teardown"]


def test_abandoning_a_device_whose_teardown_always_hangs_is_bounded_and_reported(
    marking, monkeypatch, caplog
):
    """The driver's stability is not PyPTS's job: the ladder ends, the device is named."""
    connection, marks = marking
    monkeypatch.setattr(connection_driver, "ABANDON_TEARDOWN_TIMEOUT_S", 0.5)
    monkeypatch.setattr(connection_driver, "RESCUE_TIMEOUT_S", 3.0)
    (marks.parent / (marks.name + ".tdhang")).write_text("", encoding="utf-8")
    began = time.monotonic()

    assert connection._abandon() is False

    # The teardown's 0.5 s, the rescue's 3 s, and the kills - nowhere near the hang.
    assert time.monotonic() - began < 15.0
    assert not connection._is_open()
    # Neither teardown ever marked; the rescue's connect() did.
    assert marks_of(marks) == ["connect", "connect"]
    assert any(
        record.levelno == logging.ERROR and "may still be energised" in record.getMessage()
        for record in caplog.records
    )


def test_abandoning_a_device_mid_call_kills_it_and_tears_down_on_a_fresh_process(tmp_path):
    """The abandoned run holds the device's lock: abandon() must not wait for it."""
    marks = tmp_path / "marks.txt"
    connection = ConnectionDriver("psu1", MARKING, {"marks": str(marks)}, call_timeout_s=60.0)
    connection._open()
    failures = []

    def stuck_step():
        try:
            connection.hang(60)
        except DriverError as exc:
            failures.append(str(exc))

    zombie = threading.Thread(target=stuck_step)
    zombie.start()
    try:
        deadline = time.monotonic() + 5.0
        while not connection._lock.locked() and time.monotonic() < deadline:
            time.sleep(0.01)
        began = time.monotonic()

        assert connection._abandon() is True

        assert time.monotonic() - began < 15.0
        zombie.join(timeout=5.0)
        assert not zombie.is_alive()
        # The killed call ends the step as a crash in the stuck thread.
        assert len(failures) == 1
        assert "stopped unexpectedly" in failures[0]
        # The rescue connected and tore down; the stuck process never did.
        assert marks_of(marks) == ["connect", "connect", "teardown"]
        assert not connection._is_open()
    finally:
        connection._close()
