"""
Settings shared by every test: Qt offscreen, and a temporary bench.ini (below).

Qt runs offscreen unless QT_QPA_PLATFORM already names a platform. Without
this, every GUI test opens a real window on the developer's screen - well over
a hundred of them, some maximised, each taking focus - and a test run fights
the person at the keyboard for the mouse. Set here, at import time, so it is in
place before pytest-qt creates the QApplication, and inherited by any process a
test starts. To watch a test on screen, set QT_QPA_PLATFORM=windows (or xcb)
before running pytest.
"""

import importlib
import os

import pytest

from pypts.config_handler import file_locations

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _bench_file_in_tmp(tmp_path_factory, monkeypatch):
    """
    Keep every test off the real per-user bench.ini.

    `bench_config()` creates the file on first use, and the launcher, the Pts
    API and the engine tests all reach it. Each test gets its own file under a
    temporary directory and a cold cache. The package re-exports the function
    `bench_config`, which shadows the submodule's name, so the module is
    imported by its full path.
    """
    bench_module = importlib.import_module("pypts.config_handler.bench_config")
    path = tmp_path_factory.mktemp("bench") / "bench.ini"
    monkeypatch.setattr(file_locations, "bench_file_path", lambda: path)
    bench_module.reset_for_testing()
    yield
    bench_module.reset_for_testing()
