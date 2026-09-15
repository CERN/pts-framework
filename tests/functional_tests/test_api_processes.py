# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Functional tests for pypts.api: the real Logger and CORE processes, driven from code.

Opt-in - set PYPTS_PROCESS_TESTS=1. They start real processes, and those read
the real per-user config.ini and write a run log and a report into the real
per-user folders: there is no override for where those live
(config_handler/file_locations.py), and a spawned child cannot be monkeypatched.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pypts.api import Pts, PtsError, ResultType

WAIT_RECIPE = Path(__file__).parents[1] / "unit_tests" / "data" / "wait_recipe.yml"

pytestmark = pytest.mark.skipif(
    os.environ.get("PYPTS_PROCESS_TESTS") != "1",
    reason="starts real pypts processes; set PYPTS_PROCESS_TESTS=1 to run",
)


def test_a_recipe_runs_headless_from_load_to_report():
    with Pts() as pts:
        loaded = pts.load_recipe(WAIT_RECIPE)
        result = pts.run()

    assert loaded.name == "Wait demo"
    assert result.result is ResultType.DONE
    assert [step.name for step in result.steps] == ["First wait", "Second wait"]
    assert result.report_dir is not None
    assert Path(result.report_dir).is_dir()


def test_a_refused_recipe_raises_and_the_session_still_closes(tmp_path):
    broken = tmp_path / "broken.yml"
    broken.write_text("name: [unclosed", encoding="utf-8")

    with Pts() as pts, pytest.raises(PtsError, match="not loaded"):
        pts.load_recipe(broken)


def test_the_headless_command_line_runs_a_recipe_and_exits_with_its_code():
    completed = subprocess.run(
        [sys.executable, "-m", "pypts", "--mode", "headless", "--recipe", str(WAIT_RECIPE)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Run finished: DONE (2 steps)" in completed.stdout
