"""
Unit tests for run_hal.py in the repository root: it takes no arguments, finds PyPTS's
bench.ini, and starts a HAL with its window (the HAL opens and owns it), or, when a HAL
answers already, opens the monitor on that one. The conftest keeps every test on a bench.ini
of its own under a temporary folder; the start and the monitor are replaced, so no window
opens and no HAL starts.
"""

import importlib.util
import pathlib

from pyhal import client
from pyhal.base_driver import DriverError
from pyhal.monitor import __main__ as monitor_main_module
from pypts.config_handler import file_locations

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _run_hal_module():
    spec = importlib.util.spec_from_file_location("run_hal", REPO_ROOT / "run_hal.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(monkeypatch, run_hal, running_pid=None, start_error=None):
    """Replace the HAL check, the start and the monitor; what each was called with."""
    calls: dict[str, list] = {"start": [], "monitor": []}

    def fake_start_hal(bench, port, **options):
        calls["start"].append((bench, port, options))
        if start_error is not None:
            raise start_error
        return 4242

    def fake_monitor(argv):
        calls["monitor"].append(list(argv))
        return 0

    monkeypatch.setattr(run_hal, "running_hal_pid", lambda: running_pid)
    monkeypatch.setattr(client, "start_hal", fake_start_hal)
    monkeypatch.setattr(monitor_main_module, "main", fake_monitor)
    return calls


def test_no_bench_yet_creates_it_and_starts_a_hal_with_its_window(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record(monkeypatch, run_hal)
    bench_path = file_locations.bench_file_path()
    assert not bench_path.exists()

    assert run_hal.main([]) == run_hal.EXIT_OK

    assert calls["start"] == [(str(bench_path), client.DEFAULT_PORT, {"show_window": True})]
    assert calls["monitor"] == []
    assert bench_path.exists()
    printed = capsys.readouterr().out
    assert "created from the template" in printed
    assert "devices: meteo_Meyrin." in printed
    assert "pid 4242" in printed
    assert "keeps running when the window is closed" in printed


def test_an_existing_bench_is_used_as_it_is(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record(monkeypatch, run_hal)
    bench_path = file_locations.bench_file_path()
    bench_path.write_text("[loop1]\ndriver = pyhal.drivers.loopback.LoopbackDriver\n")

    assert run_hal.main([]) == run_hal.EXIT_OK

    assert calls["start"] == [(str(bench_path), client.DEFAULT_PORT, {"show_window": True})]
    printed = capsys.readouterr().out
    assert "created" not in printed
    assert "devices: loop1." in printed


def test_a_running_hal_gets_only_the_monitor(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record(monkeypatch, run_hal, running_pid=777)

    assert run_hal.main([]) == 0

    assert calls["start"] == []
    assert calls["monitor"] == [[]]
    assert "already running" in capsys.readouterr().out


def test_a_failed_start_says_why(capsys, monkeypatch):
    run_hal = _run_hal_module()
    error = DriverError("The HAL server could not be started: x")
    _record(monkeypatch, run_hal, start_error=error)

    assert run_hal.main([]) == run_hal.EXIT_START_FAILED

    assert "The HAL server could not be started: x" in capsys.readouterr().err


def test_arguments_are_refused(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record(monkeypatch, run_hal)

    assert run_hal.main(["--port", "29601"]) == run_hal.EXIT_USAGE

    assert calls == {"start": [], "monitor": []}
    assert "takes no arguments" in capsys.readouterr().err
    assert not file_locations.bench_file_path().exists()


def test_an_unusable_bench_stops_with_the_reason(capsys, monkeypatch):
    run_hal = _run_hal_module()
    calls = _record(monkeypatch, run_hal)
    file_locations.bench_file_path().write_text("this is not an INI file\n")

    assert run_hal.main([]) == run_hal.EXIT_BAD_BENCH

    assert calls == {"start": [], "monitor": []}
    assert "The bench file cannot be used" in capsys.readouterr().err
