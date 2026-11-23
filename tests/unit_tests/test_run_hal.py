"""
Unit tests for run_hal.py in the repository root: it takes no arguments, finds PyPTS's
bench.ini, and opens the monitor in serve mode on it. The conftest keeps every test on a
bench.ini of its own under a temporary folder; the monitor itself is replaced, so no window
opens and no HAL starts.
"""

import importlib.util
import pathlib

from pyhal.monitor import __main__ as monitor_main_module
from pypts.config_handler import file_locations

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _run_hal_module():
    spec = importlib.util.spec_from_file_location("run_hal", REPO_ROOT / "run_hal.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_monitor(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_main(argv):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(monitor_main_module, "main", fake_main)
    return calls


def test_no_bench_yet_creates_it_and_serves_it_in_the_window(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record_monitor(monkeypatch)
    bench_path = file_locations.bench_file_path()
    assert not bench_path.exists()

    assert run_hal.main([]) == 0

    assert calls == [["--bench", str(bench_path), "--serve"]]
    assert bench_path.exists()
    printed = capsys.readouterr().out
    assert "created from the template" in printed
    assert "devices: meteo_Meyrin." in printed


def test_an_existing_bench_is_served_as_it_is(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record_monitor(monkeypatch)
    bench_path = file_locations.bench_file_path()
    bench_path.write_text("[loop1]\ndriver = pyhal.drivers.loopback.LoopbackDriver\n")

    assert run_hal.main([]) == 0

    assert calls == [["--bench", str(bench_path), "--serve"]]
    printed = capsys.readouterr().out
    assert "created" not in printed
    assert "devices: loop1." in printed


def test_arguments_are_refused(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record_monitor(monkeypatch)

    assert run_hal.main(["--port", "29601"]) == run_hal.EXIT_USAGE

    assert calls == []
    assert "takes no arguments" in capsys.readouterr().err
    assert not file_locations.bench_file_path().exists()


def test_an_unusable_bench_stops_with_the_reason(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record_monitor(monkeypatch)
    file_locations.bench_file_path().write_text("this is not an INI file\n")

    assert run_hal.main([]) == run_hal.EXIT_BAD_BENCH

    assert calls == []
    assert "The bench file cannot be used" in capsys.readouterr().err
