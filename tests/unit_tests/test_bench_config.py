"""
Unit tests for config_handler/bench_config.py: the bench file reader.

Everything runs against tmp_path: the `bench_path` fixture monkeypatches
`file_locations.bench_file_path`, the only place the reader asks where its
file lives, and clears the per-process cache around each test.
"""

import configparser
import importlib
import logging
from pathlib import Path

import pytest

from pypts.config_handler import file_locations
from pypts.config_handler.bench_config import BenchOutcome, bench_config

# The package re-exports the function `bench_config`, which shadows the
# submodule's name on the package; import the module by its full path.
bench_module = importlib.import_module("pypts.config_handler.bench_config")


@pytest.fixture
def bench_path(tmp_path, monkeypatch):
    """Point the reader at tmp_path."""
    path = tmp_path / "bench.ini"
    monkeypatch.setattr(file_locations, "bench_file_path", lambda: path)
    yield path


# --- creation ---------------------------------------------------------------


def test_a_missing_file_is_created_from_the_template_with_its_demo_device(bench_path):
    assert not bench_path.exists()

    result = bench_config()

    assert result.outcome is BenchOutcome.CREATED
    # The template's one device, read back from the file just written.
    assert result.devices == {
        "meteo_Meyrin": {
            "driver": "pyhal.drivers.weather.OpenMeteoDriver",
            "place": "CERN Meyrin",
            "latitude": "46.23",
            "longitude": "6.05",
        }
    }
    assert result.problem is None
    assert result.path == bench_path
    assert bench_path.exists()
    # The created file also documents the format with a commented example.
    assert "# [ssh1]" in bench_path.read_text(encoding="utf-8")


def test_the_shipped_template_declares_only_the_demo_weather_station():
    text = (Path(bench_module.__file__).parent / bench_module.BENCH_TEMPLATE_FILE_NAME).read_text(
        encoding="utf-8"
    )
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    assert parser.sections() == ["meteo_Meyrin"]
    assert parser["meteo_Meyrin"]["driver"] == "pyhal.drivers.weather.OpenMeteoDriver"


def test_a_file_that_cannot_be_created_is_discarded_with_the_reason(bench_path, monkeypatch):
    def refuse(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(bench_module.template_writer, "write", refuse)

    result = bench_config()

    assert result.outcome is BenchOutcome.DISCARDED
    assert result.devices == {}
    assert "could not be created" in (result.problem or "")


# --- reading ----------------------------------------------------------------


def test_every_section_is_a_device_with_every_value_as_text(bench_path):
    bench_path.write_text(
        "[ssh1]\ndriver = pkg.Mod\nport = 22\n[dmm1]\ndriver = pkg.Dmm\n", encoding="utf-8"
    )

    result = bench_config()

    assert result.outcome is BenchOutcome.LOADED
    assert result.problem is None
    assert result.devices == {
        "ssh1": {"driver": "pkg.Mod", "port": "22"},
        "dmm1": {"driver": "pkg.Dmm"},
    }


def test_every_call_reads_the_file_afresh(bench_path):
    """Stateless, like ConfigHandler: nothing is kept between calls."""
    bench_path.write_text("[a]\ndriver = x.Y\n", encoding="utf-8")

    first = bench_config()
    bench_path.write_text("[b]\ndriver = x.Y\n", encoding="utf-8")

    assert list(first.devices) == ["a"]
    assert list(bench_config().devices) == ["b"]


def test_a_file_saved_with_a_notepad_bom_still_reads(bench_path):
    bench_path.write_bytes(b"\xef\xbb\xbf[ssh1]\ndriver = x.Y\n")

    assert bench_config().devices == {"ssh1": {"driver": "x.Y"}}


def test_a_percent_sign_in_a_value_is_kept_verbatim(bench_path):
    bench_path.write_text("[ssh1]\ndriver = x.Y\npath = C:\\x\\%temp%\n", encoding="utf-8")

    assert bench_config().devices["ssh1"]["path"] == "C:\\x\\%temp%"


# --- discarding -------------------------------------------------------------


def test_a_file_that_is_not_ini_is_discarded_with_the_reason(bench_path, caplog):
    bench_path.write_text("not an ini file at all\n", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        result = bench_config()

    assert result.outcome is BenchOutcome.DISCARDED
    assert result.devices == {}
    assert "cannot be read" in (result.problem or "")
    assert "no devices" in caplog.text


def test_a_file_that_cannot_be_opened_is_discarded_with_its_own_reason(bench_path):
    # A directory at the file's path: exists() is true, open() raises OSError.
    bench_path.mkdir()

    result = bench_config()

    assert result.outcome is BenchOutcome.DISCARDED
    assert "cannot be opened" in (result.problem or "")
