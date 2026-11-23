"""
Unit tests for the bench file reader (src/pyhal/bench.py) and the open devices
(src/pyhal/devices.py), the latter against real driver processes - the loopback
driver and the marking ones in hal_test_drivers.py.
"""

import hashlib
from pathlib import Path

import pytest

from pyhal import DriverError, connection_driver
from pyhal.bench import read_bench, split_section
from pyhal.devices import Devices

NL = "\n"
LOOPBACK = "pyhal.drivers.loopback.LoopbackDriver"


def test_split_section_separates_the_driver_key_from_driver_keys():
    driver_path, settings = split_section(
        "ssh1", {"driver": " pkg.Ssh ", "host": "h", "port": 22}
    )
    assert driver_path == "pkg.Ssh"
    assert settings == {"host": "h", "port": "22"}


def test_a_call_timeout_key_is_the_drivers_like_any_other():
    """The call timeout is fixed (CALL_TIMEOUT_S); bench.ini does not set it."""
    _, settings = split_section("x", {"driver": "pkg.X", "call_timeout_s": "2.5"})
    assert settings == {"call_timeout_s": "2.5"}


def test_split_section_explains_a_section_without_a_driver():
    with pytest.raises(DriverError, match="has no 'driver' key"):
        split_section("x", {"host": "h"})


def test_the_removed_python_key_is_refused():
    """Review Focus 4: a bench.ini written for the previous version."""
    words = r"Device 'x'.*'python' key.*Remove it from the \[x\] section"
    with pytest.raises(DriverError, match=words):
        split_section("x", {"driver": "pkg.X", "python": "C:/py32/python.exe"})


def test_read_bench_anchors_a_relative_driver_file_to_the_bench_folder(tmp_path):
    path = tmp_path / "bench.ini"
    path.write_text(
        "[psu1]\ndriver = drivers/acme_psu.py:AcmePsuDriver\n"
        "[psu2]\ndriver = ~/acme_psu.py:AcmePsuDriver\n"
        "[loop1]\ndriver = pkg.Loop\n",
        encoding="utf-8",
    )
    sections, _digest = read_bench(path)
    assert sections["psu1"]["driver"] == f"{tmp_path / 'drivers' / 'acme_psu.py'}:AcmePsuDriver"
    assert sections["psu2"]["driver"] == (
        f"{Path('~').expanduser() / 'acme_psu.py'}:AcmePsuDriver"
    )
    assert sections["loop1"]["driver"] == "pkg.Loop"


def test_read_bench_returns_sections_and_hash(tmp_path):
    path = tmp_path / "bench.ini"
    path.write_text(
        "[loop1]\ndriver = pkg.Loop\n[psu1]\ndriver = drivers/psu.py:Psu\n", encoding="utf-8"
    )
    sections, digest = read_bench(path)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert sections["loop1"] == {"driver": "pkg.Loop"}
    assert sections["psu1"]["driver"] == f"{tmp_path / 'drivers' / 'psu.py'}:Psu"


def _marking(tmp_path, tag=""):
    section = {"driver": "hal_test_drivers.MarkingDriver", "marks": str(tmp_path / "marks.txt")}
    if tag:
        section["tag"] = tag
    return section


def _marks(tmp_path):
    return (tmp_path / "marks.txt").read_text(encoding="utf-8")


@pytest.fixture
def loop_devices():
    devices = Devices({"loop1": {"driver": LOOPBACK}})
    yield devices
    devices.close_all()


def test_open_reuses_an_open_device(loop_devices):
    device_type, operations = loop_devices.open("loop1")
    first = loop_devices.call("loop1", "process_id", [], {})
    assert device_type == "Other"
    assert "echo" in operations
    loop_devices.open("loop1")
    assert loop_devices.call("loop1", "process_id", [], {}) == first
    assert loop_devices.open_names() == ["loop1"]


def test_an_unknown_device_names_the_configured_ones(loop_devices):
    with pytest.raises(DriverError, match=r"No device 'nope' is configured.*loop1"):
        loop_devices.open("nope")


def test_call_opens_a_closed_device(loop_devices):
    loop_devices.open("loop1")
    assert loop_devices.close("loop1") is True
    assert loop_devices.open_names() == []
    assert loop_devices.call("loop1", "echo", [5], {}) == 5
    assert loop_devices.open_names() == ["loop1"]


def test_a_driver_that_raises_stays_open(loop_devices):
    with pytest.raises(DriverError, match="boom"):
        loop_devices.call("loop1", "fail", ["boom"], {})
    assert loop_devices.open_names() == ["loop1"]


def test_a_crashed_driver_is_rescued_at_once(tmp_path):
    section = _marking(tmp_path)
    section["driver"] = "hal_test_drivers.CrashingMarkingDriver"
    devices = Devices({"m1": section})
    with pytest.raises(DriverError, match="stopped unexpectedly"):
        devices.call("m1", "crash", [3], {})
    assert _marks(tmp_path).endswith("connect" + NL + "teardown" + NL)
    assert devices.open_names() == []
    assert devices.snapshot()[0]["state"] == "failed"


def test_a_call_timeout_rescues_the_device_at_once(tmp_path):
    devices = Devices({"m1": _marking(tmp_path)}, call_timeout_s=1.0)
    with pytest.raises(DriverError, match="did not answer"):
        devices.call("m1", "hang", [5], {})
    assert _marks(tmp_path).endswith("teardown" + NL)
    assert devices.open_names() == []


def test_close_all_closes_newest_first_and_lists_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(connection_driver, "RESCUE_TIMEOUT_S", 1.0)
    devices = Devices(
        {"m1": _marking(tmp_path, "m1"), "m2": _marking(tmp_path, "m2")}, call_timeout_s=1.0
    )
    devices.open("m1")
    devices.open("m2")
    (tmp_path / "marks.txt.tdhang.m2").write_text("", encoding="utf-8")
    assert devices.close_all() == ["m2"]
    assert devices.open_names() == []
    lines = _marks(tmp_path).splitlines()
    # m2 went first: its rescue connected before m1's teardown ran.
    last_m2 = max(i for i, line in enumerate(lines) if line == "connect m2")
    assert last_m2 < lines.index("teardown m1")
    assert "teardown m2" not in lines


def test_snapshot_lists_every_bench_device():
    devices = Devices({"loop1": {"driver": LOOPBACK}, "bad1": {"host": "h"}})
    try:
        assert [row["state"] for row in devices.snapshot()] == ["configured", "configured"]
        devices.open("loop1")
        with pytest.raises(DriverError, match="has no 'driver' key"):
            devices.open("bad1")
        rows = {row["name"]: row for row in devices.snapshot()}
        assert rows["loop1"] == {
            "name": "loop1",
            "device_type": "Other",
            "state": "open",
            "last_error": None,
        }
        assert rows["bad1"]["state"] == "failed"
        assert "no 'driver' key" in rows["bad1"]["last_error"]
    finally:
        devices.close_all()


def test_info_of_a_closed_device(loop_devices):
    assert loop_devices.info("loop1") == ("", [], False)
    loop_devices.open("loop1")
    device_type, operations, is_open = loop_devices.info("loop1")
    assert (device_type, is_open) == ("Other", True)
    assert "echo" in operations


def test_a_recover_that_cannot_reopen_leaves_the_device_closed(tmp_path):
    gate = tmp_path / "off"
    devices = Devices(
        {
            "f1": {
                "driver": "hal_test_drivers.FlakyConnectDriver",
                "fail_connect_file": str(gate),
            }
        }
    )
    try:
        devices.open("f1")
        gate.write_text("", encoding="utf-8")
        with pytest.raises(DriverError):
            devices.recover("f1")
        assert devices.open_names() == []
        assert devices.snapshot()[0]["state"] == "failed"
        gate.unlink()
        assert devices.call("f1", "ping", [], {}) == "pong"
        assert devices.open_names() == ["f1"]
    finally:
        devices.close_all()


def test_lifecycle_names_are_not_operations(loop_devices):
    for name in ("connect", "teardown", "recover"):
        message = f"Device 'loop1': '{name}' is not an operation; the HAL server runs it itself."
        with pytest.raises(DriverError) as caught:
            loop_devices.call("loop1", name, [], {})
        assert str(caught.value) == message


def _crashing(tmp_path):
    return {
        "driver": "hal_test_drivers.FlakyConnectDriver",
        "fail_connect_file": str(tmp_path / "never"),
    }


def test_the_failed_rescue_keeps_the_original_error(tmp_path, monkeypatch):
    monkeypatch.setattr(connection_driver, "RESCUE_TIMEOUT_S", 1.0)
    section = _marking(tmp_path)
    section["driver"] = "hal_test_drivers.CrashingMarkingDriver"
    devices = Devices({"m1": section})
    devices.open("m1")
    (tmp_path / "marks.txt.tdhang").write_text("", encoding="utf-8")
    with pytest.raises(DriverError, match="stopped unexpectedly"):
        devices.call("m1", "crash", [3], {})
    last_error = devices.snapshot()[0]["last_error"]
    assert "stopped unexpectedly" in last_error
    assert "may still be energised" in last_error


def test_recover_brings_a_device_back(loop_devices):
    loop_devices.open("loop1")
    loop_devices.recover("loop1")
    assert loop_devices.call("loop1", "echo", [7], {}) == 7
    assert loop_devices.open_names() == ["loop1"]


def test_last_error_clears_on_a_successful_reopen(tmp_path):
    devices = Devices({"f1": _crashing(tmp_path)})
    try:
        with pytest.raises(DriverError, match="stopped unexpectedly"):
            devices.call("f1", "crash", [3], {})
        assert devices.snapshot()[0]["state"] == "failed"
        assert devices.call("f1", "ping", [], {}) == "pong"
        row = devices.snapshot()[0]
        assert row["state"] == "open"
        assert row["last_error"] is None
    finally:
        devices.close_all()


def test_close_of_a_rescued_device_is_harmless(tmp_path):
    devices = Devices({"f1": _crashing(tmp_path)})
    with pytest.raises(DriverError, match="stopped unexpectedly"):
        devices.call("f1", "crash", [3], {})
    assert devices.close("f1") is True
