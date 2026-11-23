"""
Unit tests for the hardware layer (src/pyhal/): the driver base and the
device types, the driver-process half of connection_driver.py run in-process, and
the local setup.

No test here starts a process; ConnectionDriver's process tests live in
test_hal_connection.py.
"""

import importlib
import sys
import threading
from typing import ClassVar

import pytest

from pyhal import (
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
from pyhal import local_setup as local_setup_module
from pyhal.base_driver import LIFECYCLE_METHODS, operations_of
from pyhal.connection_driver import (
    DRIVER_FILE_MODULE_PREFIX,
    ERROR,
    RESULT,
    answer,
    driver_module_name,
    load_driver_class,
    split_driver_file,
)
from pyhal.device_types import DEVICE_TYPE_NAMES, DEVICE_TYPES
from pyhal.drivers.loopback import LoopbackDriver


@pytest.mark.parametrize(
    "gone",
    [
        "pypts.hardware_layer",
        "pypts.hal",
        "pypts.hal.driver",
        "pypts.hal.bench",
        "pypts.hal.proxy",
        "pypts.hal.runner",
        "pypts.hal.protocol",
    ],
)
def test_the_old_modules_are_gone(gone):
    importlib.import_module("pyhal")
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
        "configure_waveform_acquisition",
        "get_frequency",
        "measure_point",
        "read_waveform",
    ]
    assert operations_of(Scope) == [
        "configure_waveform_acquisition",
        "measure_point",
        "read_waveform",
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


LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"


def test_the_loopback_driver_is_an_other():
    assert LoopbackDriver.DEVICE_TYPE == "Other"
    assert "echo" in operations_of(LoopbackDriver)


def test_load_driver_class_finds_a_driver():
    assert load_driver_class(LOOPBACK) is LoopbackDriver


@pytest.mark.parametrize(
    ("dotted", "words"),
    [
        ("LoopbackDriver", "not a dotted path"),
        ("pyhal.drivers.loopback.Nope", "has no class 'Nope'"),
        ("pyhal.base_driver.DriverError", "is not a driver"),
        ("pyhal.base_driver.BaseDriver", "belongs to no device type"),
    ],
)
def test_load_driver_class_explains_a_bad_path(dotted, words):
    with pytest.raises(ValueError, match=words):
        load_driver_class(dotted)


FILE_DRIVER_SOURCE = """
import logging

from pyhal import Other

log = logging.getLogger(__name__)


class FileDriver(Other):
    def connect(self, config):
        log.info("file driver connected")

    def teardown(self):
        pass

    def module_name(self):
        return __name__
"""


@pytest.fixture
def driver_file(tmp_path):
    """A driver in a file of its own, outside every package; its module is forgotten after."""
    path = tmp_path / "bench_file_driver.py"
    path.write_text(FILE_DRIVER_SOURCE, encoding="utf-8")
    yield path
    sys.modules.pop(DRIVER_FILE_MODULE_PREFIX + "bench_file_driver", None)


def test_load_driver_class_loads_a_driver_file(driver_file):
    found = load_driver_class(f"{driver_file}:FileDriver")
    assert found.DEVICE_TYPE == "Other"
    assert found().module_name() == DRIVER_FILE_MODULE_PREFIX + "bench_file_driver"


@pytest.mark.parametrize(
    ("spelling", "words"),
    [
        ("{folder}/missing.py:FileDriver", "does not exist"),
        ("{file}:Nope", "has no class 'Nope'"),
        ("{file}", "names a file but no class"),
    ],
)
def test_load_driver_class_explains_a_bad_driver_file(driver_file, spelling, words):
    driver_path = spelling.format(folder=driver_file.parent, file=driver_file)
    with pytest.raises(ValueError, match=words):
        load_driver_class(driver_path)


@pytest.mark.parametrize(
    ("driver_path", "expected"),
    [
        ("C:\\bench\\acme_psu.py:AcmePsuDriver", ("C:\\bench\\acme_psu.py", "AcmePsuDriver")),
        ("drivers/acme_psu.py:AcmePsuDriver", ("drivers/acme_psu.py", "AcmePsuDriver")),
        ("bench_drivers.acme_psu.AcmePsuDriver", None),
        ("C:\\bench\\acme_psu.py", None),
    ],
)
def test_split_driver_file_keeps_the_drive_letter_in_the_file(driver_path, expected):
    assert split_driver_file(driver_path) == expected


def test_driver_module_name_follows_the_spelling():
    assert driver_module_name("bench_drivers.acme_psu.AcmePsuDriver") == "bench_drivers.acme_psu"
    assert driver_module_name("C:/bench/acme_psu.py:AcmePsuDriver") == (
        DRIVER_FILE_MODULE_PREFIX + "acme_psu"
    )


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

    def __init__(self, name, driver_path, settings):
        self.name = name
        self.driver_path = driver_path
        self.settings = settings
        self.events: list[str] = []
        _FakeConnection.made.append(self)

    def _open(self):
        self.events.append("open")

    def _close(self):
        self.events.append("close")


@pytest.fixture
def fake_connections(monkeypatch):
    _FakeConnection.made = []
    monkeypatch.setattr(local_setup_module, "ConnectionDriver", _FakeConnection)
    return _FakeConnection.made


SECTIONS = {
    "ssh1": {"driver": "pkg.Ssh", "host": "h"},
    "loop1": {"driver": "pkg.Loop"},
}


def test_a_device_opens_once_and_is_reused(fake_connections):
    setup = LocalSetup(lambda: SECTIONS)
    first = setup.get_device("ssh1")
    assert setup.get_device("ssh1") is first
    assert len(fake_connections) == 1
    assert first.events == ["open"]
    assert first.settings == {"host": "h"}


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
    ssh._close = lambda: order.append("ssh1")
    loop._close = lambda: order.append("loop1")
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
    """A script that never leaves its with-block must not break the next setup."""
    old = LocalSetup(lambda: SECTIONS)
    new = LocalSetup(lambda: {"loop1": {"driver": "pkg.Other"}})
    old.__enter__()
    with new:
        assert get_device("loop1").driver_path == "pkg.Other"
    old.__exit__(None, None, None)
    with pytest.raises(DriverError, match="No local setup is active"):
        get_device("loop1")


def test_an_old_pypts_hal_path_says_to_use_pyhal():
    with pytest.raises(ValueError, match=r"pyhal\.drivers\.loopback\.LoopbackDriver"):
        load_driver_class("pypts.hal.drivers.loopback.LoopbackDriver")
