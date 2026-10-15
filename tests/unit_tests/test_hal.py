"""
Unit tests for the hardware layer (src/pypts/hal/): the driver base and the
device types, the driver-process half of connection_driver.py run in-process, and
the local setup.

No test here starts a process; ConnectionDriver's process tests live in
test_hal_connection.py.
"""

import importlib
import threading
import time
from typing import ClassVar

import pytest

from pypts.hal import (
    DMM,
    PSU,
    SSH,
    BaseDriver,
    DriverError,
    Load,
    LocalSetup,
    Other,
    Scope,
    get_device,
)
from pypts.hal import local_setup as local_setup_module
from pypts.hal.base_driver import LIFECYCLE_METHODS, operations_of
from pypts.hal.connection_driver import ERROR, RESULT, answer, load_driver_class
from pypts.hal.device_types import DEVICE_TYPE_NAMES, DEVICE_TYPES
from pypts.hal.drivers.loopback import LoopbackDriver
from pypts.hal.local_setup import (
    DEFAULT_CALL_TIMEOUT_S,
    abandon_active_setup,
    bench_sections,
    ini_device_sections,
    split_section,
)


@pytest.mark.parametrize(
    "gone",
    [
        "pypts.hardware_layer",
        "pypts.hal.driver",
        "pypts.hal.bench",
        "pypts.hal.proxy",
        "pypts.hal.runner",
        "pypts.hal.protocol",
    ],
)
def test_the_old_modules_are_gone(gone):
    importlib.import_module("pypts.hal")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(gone)


class _Plain(Other):
    def __init__(self):
        self.calls = []

    def connect(self, config):
        self.calls.append(("connect", config))

    def teardown(self):
        self.calls.append(("teardown",))

    def measure(self):
        return 1.0

    def _helper(self):
        return 2.0


def test_driver_cannot_be_built_without_connect_and_teardown():
    with pytest.raises(TypeError):
        BaseDriver()  # type: ignore[abstract]


def test_recover_tears_down_then_connects_again():
    driver = _Plain()
    driver.connect({"host": "a"})
    driver.recover({"host": "b"})
    assert driver.calls == [("connect", {"host": "a"}), ("teardown",), ("connect", {"host": "b"})]


def test_operations_are_the_public_methods_without_the_lifecycle():
    assert operations_of(_Plain) == ["measure"]
    assert LIFECYCLE_METHODS == ("connect", "teardown", "recover")


def test_every_device_type_names_itself():
    assert DEVICE_TYPE_NAMES == ("PSU", "DMM", "Scope", "SSH", "Load", "Other")
    assert [device_type.DEVICE_TYPE for device_type in DEVICE_TYPES] == list(DEVICE_TYPE_NAMES)
    assert BaseDriver.DEVICE_TYPE == ""


def test_device_type_verbs_are_abstract():
    assert operations_of(PSU) == [
        "measure_current",
        "measure_voltage",
        "output_off",
        "output_on",
        "set_current_limit",
        "set_voltage",
    ]
    assert operations_of(DMM) == [
        "measure_ac_voltage",
        "measure_dc_current",
        "measure_dc_voltage",
        "measure_resistance",
    ]
    assert operations_of(Scope) == [
        "arm_single",
        "read_waveform",
        "set_timebase",
        "set_vertical_scale",
    ]
    assert operations_of(Load) == [
        "input_off",
        "input_on",
        "measure_current",
        "measure_voltage",
        "set_level",
        "set_mode",
    ]
    assert operations_of(SSH) == ["execute", "get_file", "put_file"]
    assert operations_of(Other) == []
    with pytest.raises(TypeError):
        SSH()  # type: ignore[abstract]


def test_driver_error_is_an_exception():
    assert issubclass(DriverError, Exception)


LOOPBACK = "pypts.hal.drivers.loopback.LoopbackDriver"


def test_the_loopback_driver_is_an_other():
    assert LoopbackDriver.DEVICE_TYPE == "Other"
    assert "echo" in operations_of(LoopbackDriver)


def test_load_driver_class_finds_a_driver():
    assert load_driver_class(LOOPBACK) is LoopbackDriver


@pytest.mark.parametrize(
    ("dotted", "words"),
    [
        ("LoopbackDriver", "not a dotted path"),
        ("pypts.hal.drivers.loopback.Nope", "has no class 'Nope'"),
        ("pypts.hal.base_driver.DriverError", "is not a driver"),
        ("pypts.hal.base_driver.BaseDriver", "belongs to no device type"),
    ],
)
def test_load_driver_class_explains_a_bad_path(dotted, words):
    with pytest.raises(ValueError, match=words):
        load_driver_class(dotted)


def test_answer_runs_an_operation():
    assert answer(LoopbackDriver(), ["echo"], ("echo", [42], {})) == (RESULT, 42)


def test_answer_runs_a_lifecycle_method_that_is_not_an_operation():
    driver = LoopbackDriver()
    reply = answer(driver, ["echo"], ("connect", [{"a": "1"}], {}))
    assert reply[0] == RESULT
    assert driver.settings() == {"a": "1"}


def test_answer_refuses_what_is_not_an_operation():
    reply = answer(LoopbackDriver(), ["echo"], ("__class__", [], {}))
    assert reply[0] == ERROR
    assert reply[1] == "AttributeError"


def test_answer_reports_an_exception_with_its_traceback():
    reply = answer(LoopbackDriver(), ["fail"], ("fail", ["instrument said no"], {}))
    assert reply[0] == ERROR
    assert reply[1] == "RuntimeError"
    assert reply[2] == "instrument said no"
    assert "Traceback" in reply[3]


class _FakeConnection:
    """Stands in for ConnectionDriver: records what the LocalSetup does with it."""

    made: ClassVar[list["_FakeConnection"]] = []

    def __init__(self, name, driver_path, settings, *, call_timeout_s):
        self.name = name
        self.driver_path = driver_path
        self.settings = settings
        self.call_timeout_s = call_timeout_s
        self.events: list[str] = []
        _FakeConnection.made.append(self)

    def open(self):
        self.events.append("open")

    def close(self):
        self.events.append("close")

    def abandon(self):
        self.events.append("abandon")
        return True


@pytest.fixture
def fake_connections(monkeypatch):
    _FakeConnection.made = []
    monkeypatch.setattr(local_setup_module, "ConnectionDriver", _FakeConnection)
    return _FakeConnection.made


SECTIONS = {
    "ssh1": {"driver": "pkg.Ssh", "host": "h", "call_timeout_s": "5"},
    "loop1": {"driver": "pkg.Loop"},
}


def test_split_section_separates_framework_keys_from_driver_keys():
    driver_path, call_timeout_s, settings = split_section(
        "ssh1", {"driver": " pkg.Ssh ", "host": "h", "port": 22}
    )
    assert driver_path == "pkg.Ssh"
    assert call_timeout_s == DEFAULT_CALL_TIMEOUT_S
    assert settings == {"host": "h", "port": "22"}


def test_split_section_reads_the_call_timeout():
    _, call_timeout_s, settings = split_section("x", {"driver": "pkg.X", "call_timeout_s": "2.5"})
    assert call_timeout_s == 2.5
    assert settings == {}


@pytest.mark.parametrize(
    ("section", "words"),
    [
        ({"host": "h"}, "has no 'driver' key"),
        ({"driver": "pkg.X", "call_timeout_s": "soon"}, "positive number of seconds"),
        ({"driver": "pkg.X", "call_timeout_s": "0"}, "positive number of seconds"),
    ],
)
def test_split_section_explains_a_bad_section(section, words):
    with pytest.raises(DriverError, match=words):
        split_section("x", section)


def test_the_removed_python_key_is_refused():
    """Review Focus 4: a bench.ini written for the previous version."""
    words = r"Device 'x'.*'python' key.*Remove it from the \[x\] section"
    with pytest.raises(DriverError, match=words):
        split_section("x", {"driver": "pkg.X", "python": "C:/py32/python.exe"})


def test_ini_device_sections_reads_every_section_as_a_device(tmp_path):
    path = tmp_path / "setup.ini"
    path.write_text("[loop1]\ndriver = pkg.Loop\n[dmm1]\ndriver = pkg.Dmm\n", encoding="utf-8")
    assert ini_device_sections(path) == {
        "loop1": {"driver": "pkg.Loop"},
        "dmm1": {"driver": "pkg.Dmm"},
    }


def test_bench_sections_returns_the_devices_of_the_bench_file(monkeypatch):
    import importlib
    from pathlib import Path

    bench_module = importlib.import_module("pypts.config_handler.bench_config")
    from pypts.config_handler import BenchConfig, BenchOutcome

    monkeypatch.setattr(
        bench_module,
        "bench_config",
        lambda: BenchConfig(
            devices={"loop1": {"driver": "pkg.Loop"}},
            outcome=BenchOutcome.LOADED,
            problem=None,
            path=Path("bench.ini"),
        ),
    )

    assert bench_sections() == {"loop1": {"driver": "pkg.Loop"}}


def test_bench_sections_raises_when_the_bench_file_was_discarded(monkeypatch):
    import importlib
    from pathlib import Path

    bench_module = importlib.import_module("pypts.config_handler.bench_config")
    from pypts.config_handler import BenchConfig, BenchOutcome

    monkeypatch.setattr(
        bench_module,
        "bench_config",
        lambda: BenchConfig(
            devices={},
            outcome=BenchOutcome.DISCARDED,
            problem="it is broken",
            path=Path("bench.ini"),
        ),
    )

    with pytest.raises(DriverError, match=r"discarded.*it is broken"):
        bench_sections()


def test_a_device_opens_once_and_is_reused(fake_connections):
    setup = LocalSetup(lambda: SECTIONS)
    first = setup.get_device("ssh1")
    assert setup.get_device("ssh1") is first
    assert len(fake_connections) == 1
    assert first.events == ["open"]
    assert first.settings == {"host": "h"}
    assert first.call_timeout_s == 5.0


def test_the_sections_are_read_lazily_and_once(fake_connections):
    reads = []

    def read():
        reads.append(1)
        return SECTIONS

    setup = LocalSetup(read)
    with setup:
        pass
    assert reads == []
    setup.get_device("ssh1")
    setup.get_device("loop1")
    assert reads == [1]


def test_an_unknown_device_names_the_configured_ones(fake_connections):
    setup = LocalSetup(lambda: SECTIONS)
    with pytest.raises(DriverError, match=r"No device 'dmm1'.*Configured devices: loop1, ssh1"):
        setup.get_device("dmm1")
    assert setup.device_names() == ["loop1", "ssh1"]


def test_one_bad_section_does_not_stop_the_others(fake_connections):
    setup = LocalSetup(lambda: {"bad": {"host": "h"}, "loop1": {"driver": "pkg.Loop"}})
    with pytest.raises(DriverError):
        setup.get_device("bad")
    assert setup.get_device("loop1").events == ["open"]


def test_close_closes_every_device_newest_first(fake_connections):
    setup = LocalSetup(lambda: SECTIONS)
    order = []
    ssh = setup.get_device("ssh1")
    loop = setup.get_device("loop1")
    ssh.close = lambda: order.append("ssh1")
    loop.close = lambda: order.append("loop1")
    setup.close()
    assert order == ["loop1", "ssh1"]
    setup.close()
    assert order == ["loop1", "ssh1"]


def test_get_device_needs_an_active_local_setup():
    with pytest.raises(DriverError, match="No local setup is active"):
        get_device("ssh1")


def test_get_device_asks_the_active_local_setup_until_it_closes(fake_connections):
    with LocalSetup(lambda: SECTIONS) as setup:
        device = get_device("ssh1")
        assert device is setup.get_device("ssh1")
    assert device.events == ["open", "close"]
    with pytest.raises(DriverError, match="No local setup is active"):
        get_device("ssh1")


def test_get_device_works_from_another_thread(fake_connections):
    """Test code may start threads of its own."""
    found = []
    with LocalSetup(lambda: SECTIONS):
        worker = threading.Thread(target=lambda: found.append(get_device("loop1")))
        worker.start()
        worker.join(timeout=5.0)
    assert found and found[0].name == "loop1"


def test_a_newer_local_setup_replaces_an_older_one(fake_connections):
    """An abandoned run never leaves its with-block; the next run must still work."""
    old = LocalSetup(lambda: SECTIONS)
    new = LocalSetup(lambda: {"loop1": {"driver": "pkg.Other"}})
    old.__enter__()
    with new:
        assert get_device("loop1").driver_path == "pkg.Other"
    old.__exit__(None, None, None)
    with pytest.raises(DriverError, match="No local setup is active"):
        get_device("loop1")


# --------------------------------------------------------------------------
# A run that will not end: its devices are made safe without it
# --------------------------------------------------------------------------


def test_abandoning_takes_the_setup_away_and_makes_every_device_safe(fake_connections):
    setup = LocalSetup(lambda: SECTIONS)
    setup.__enter__()
    ssh = setup.get_device("ssh1")
    loop = setup.get_device("loop1")

    assert abandon_active_setup(time_limit_s=5.0) == []

    assert ssh.events == ["open", "abandon"]
    assert loop.events == ["open", "abandon"]
    with pytest.raises(DriverError, match="No local setup is active"):
        get_device("loop1")


def test_an_abandoned_setup_opens_no_device_for_the_run_it_was_taken_from(fake_connections):
    """The stuck run's next get_device() must not quietly reopen what was just made safe."""
    setup = LocalSetup(lambda: SECTIONS)
    setup.__enter__()
    abandon_active_setup(time_limit_s=5.0)

    with pytest.raises(DriverError, match="abandoned"):
        setup.get_device("ssh1")
    assert fake_connections == []
    # Its own with-block ending later is harmless.
    setup.__exit__(None, None, None)


def test_devices_are_made_safe_side_by_side_and_the_slow_ones_named(fake_connections):
    setup = LocalSetup(lambda: SECTIONS)
    setup.__enter__()
    ssh = setup.get_device("ssh1")
    loop = setup.get_device("loop1")
    release = threading.Event()

    def slow():
        release.wait(10.0)
        return True

    ssh.abandon = slow
    loop.abandon = lambda: False
    began = time.monotonic()

    unsafe = abandon_active_setup(time_limit_s=0.5)

    release.set()
    assert time.monotonic() - began < 3.0
    assert sorted(unsafe) == ["loop1", "ssh1"]


def test_abandoning_with_no_active_setup_does_nothing():
    assert abandon_active_setup(time_limit_s=1.0) == []
