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

import pytest
from hal_test_drivers import TwoArgumentError

from pypts.hal import DriverError
from pypts.hal.connection_driver import ConnectionDriver

LOOPBACK = "pypts.hal.drivers.loopback.LoopbackDriver"


@pytest.fixture
def device():
    connection = ConnectionDriver("loop1", LOOPBACK, {"mode": "test"})
    connection.open()
    yield connection
    connection.close()


def test_open_says_hello_and_connects(device):
    assert device.is_open()
    assert device.family == "Other"
    assert "echo" in device.operations
    assert device.is_connected() is True
    assert device.settings() == {"mode": "test"}


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
    connection.open()
    try:
        with pytest.raises(DriverError, match="'lock' returned a value that cannot be sent"):
            connection.lock()
        assert connection.ping() == "pong"
    finally:
        connection.close()


def test_driver_log_records_reach_the_run_log(caplog):
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection.open()
    try:
        connection.log_message("relay 3 closed")
    finally:
        connection.close()
    records = [r for r in caplog.records if r.getMessage() == "Device 'loop1': relay 3 closed"]
    assert records
    assert records[0].levelno == logging.INFO


def test_printed_output_is_logged_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection.open()
    try:
        connection.print_text("vendor banner")
    finally:
        connection.close()
    wanted = "Device 'loop1' printed: vendor banner"
    records = [r for r in caplog.records if r.getMessage() == wanted]
    assert records
    assert records[0].levelno == logging.DEBUG


def test_connect_settings_are_masked_in_the_trace(caplog):
    """Review Focus 5."""
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {"password": "hunter2"})
    connection.open()
    connection.close()
    assert "hunter2" not in caplog.text


def test_recover_on_a_live_process_does_not_trace_the_secrets(caplog):
    """Review Focus 5: recover() hands the settings over again."""
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {"password": "hunter2"})
    connection.open()
    try:
        connection.recover()
    finally:
        connection.close()
    assert "hunter2" not in caplog.text


def test_a_call_that_takes_too_long_stops_the_process():
    connection = ConnectionDriver("loop1", LOOPBACK, {}, call_timeout_s=0.5)
    connection.open()
    try:
        with pytest.raises(DriverError, match="did not answer 'sleep' within"):
            connection.sleep(10)
        assert not connection.is_open()
    finally:
        connection.close()


def test_a_crash_is_a_driver_error_with_the_exit_code():
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection.open()
    try:
        with pytest.raises(DriverError, match=r"stopped unexpectedly \(exit code 3\)"):
            connection.crash(3)
        assert not connection.is_open()
        with pytest.raises(DriverError, match="is not open"):
            connection.echo(1)
    finally:
        connection.close()


def test_recover_starts_a_fresh_process_after_a_crash():
    connection = ConnectionDriver("loop1", LOOPBACK, {"mode": "test"})
    connection.open()
    try:
        first = connection.process_id()
        with pytest.raises(DriverError):
            connection.crash(1)
        connection.recover()
        assert connection.process_id() != first
        assert connection.settings() == {"mode": "test"}
    finally:
        connection.close()


def test_recover_on_a_live_process_keeps_the_process(device):
    first = device.process_id()
    device.recover()
    assert device.process_id() == first
    assert device.is_connected() is True


@pytest.mark.parametrize(
    ("driver_path", "words"),
    [
        ("pypts.hal.drivers.nothing.Here", "No module named"),
        ("hal_test_drivers.NoFamilyDriver", "belongs to no device family"),
        ("hal_test_drivers.BrokenConstructorDriver", "constructor exploded"),
        ("hal_test_drivers.FailingConnectDriver", "instrument is switched off"),
    ],
)
def test_a_device_that_cannot_open_says_why_and_leaves_nothing_running(driver_path, words):
    connection = ConnectionDriver("bad1", driver_path, {})
    with pytest.raises(DriverError, match=words):
        connection.open()
    assert not connection.is_open()
    connection.close()


def test_close_is_safe_twice_and_before_open():
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection.close()
    connection.open()
    connection.close()
    connection.close()
    assert not connection.is_open()


def test_opening_an_open_device_is_refused_and_keeps_the_process(device):
    first = device.process_id()
    with pytest.raises(DriverError, match="Device 'loop1' is already open"):
        device.open()
    assert device.process_id() == first


def test_a_long_value_is_cut_in_the_trace_but_returned_whole(caplog):
    caplog.set_level(logging.DEBUG)
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection.open()
    try:
        big = "y" * 10_000
        assert connection.echo(big) == big
    finally:
        connection.close()
    assert caplog.records
    for record in caplog.records:
        assert len(record.getMessage()) < 600


def test_the_driver_process_ends_when_its_pipe_closes():
    """Review Focus 2: PyPTS dying must take the driver process with it.

    Closing PyPTS's end of the Pipe is what the operating system does when
    PyPTS dies; the driver process must see it, tear down and exit.
    """
    connection = ConnectionDriver("loop1", LOOPBACK, {})
    connection.open()
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
    ConnectionDriver("loop1", "pypts.hal.drivers.loopback.LoopbackDriver", {}).open()
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
    connection.open()
    yield connection
    connection.close()


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
