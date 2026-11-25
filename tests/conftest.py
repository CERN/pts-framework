"""
Settings shared by every test: Qt offscreen, the HAL turned off, and a temporary bench.ini
(below).

Qt runs offscreen unless QT_QPA_PLATFORM already names a platform. Without
this, every GUI test opens a real window on the developer's screen - well over
a hundred of them, some maximised, each taking focus - and a test run fights
the person at the keyboard for the mouse. Set here, at import time, so it is in
place before pytest-qt creates the QApplication, and inherited by any process a
test starts. To watch a test on screen, set QT_QPA_PLATFORM=windows (or xcb)
before running pytest.
"""

import os

import pytest

from pypts.config_handler import file_locations

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# No CORE a test starts connects to the HAL server or starts one (core/hal_link.py): the
# real port and the real bench stay untouched. Set at import time, so the engine processes
# a test spawns inherit it. A test that wants a connect removes it with
# monkeypatch.delenv("PYPTS_HAL", raising=False). A non-empty value already in the shell wins
# (PYPTS_HAL=on runs the suite against a real HAL); an empty one (`PYPTS_HAL=`) does not, since
# hal_link would take it for "on".
if not os.environ.get("PYPTS_HAL", "").strip():
    os.environ["PYPTS_HAL"] = "off"


@pytest.fixture(autouse=True)
def _bench_file_in_tmp(tmp_path_factory, monkeypatch):
    """
    Keep every test off the real per-user bench.ini.

    `bench_config()` creates the file on first use, and the launcher, the Pts
    API and the engine tests all reach it. Each test gets its own file under a
    temporary directory.
    """
    path = tmp_path_factory.mktemp("bench") / "bench.ini"
    monkeypatch.setattr(file_locations, "bench_file_path", lambda: path)
    yield
