"""
Unit tests for the hardware layer (src/pyhal/): the driver base and the
device types, and the driver-process half of connection_driver.py run in-process.

No test here starts a process; ConnectionDriver's process tests live in
test_hal_connection.py.
"""

import importlib
import sys

import pytest

from pyhal import (
    DMM,
    PSU,
    SSH,
    BaseDriver,
    DriverError,
    Load,
    Other,
    Scope,
)
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
        "pyhal.local_setup",
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


def test_an_old_pypts_hal_path_says_to_use_pyhal():
    with pytest.raises(ValueError, match=r"pyhal\.drivers\.loopback\.LoopbackDriver"):
        load_driver_class("pypts.hal.drivers.loopback.LoopbackDriver")
