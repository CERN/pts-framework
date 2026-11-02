"""
The stepgraph demo recipe, run through the real engine: both of its streams
must land in <run folder>/streams/ as CSV files.

The engine fixture and helpers are test_engine_in_process.py's. The demo is
copied to tmp_path with sine_tests.py beside it and a short `duration_s`, so
the test takes a second instead of twelve.
"""

import csv
import logging
import shutil
import threading
from pathlib import Path

from test_engine_in_process import (  # noqa: F401  (engine is a pytest fixture)
    engine,
    load_recipe,
    run_to_report,
)

from pypts.messages.run_events import RunStarted

DEMO_DIR = Path(__file__).parents[2] / "resources" / "recipes" / "stepgraph_recipes"


def test_stepgraph_demo_writes_both_streams(engine, tmp_path, caplog):  # noqa: F811
    """The blocking and the background stream each leave a CSV with rows."""
    work_dir = tmp_path / "demo"
    work_dir.mkdir()
    shutil.copy(DEMO_DIR / "sine_tests.py", work_dir / "sine_tests.py")
    recipe_text = (DEMO_DIR / "stepgraph_demo.yml").read_text(encoding="utf-8")
    assert "duration_s: 10" in recipe_text
    recipe_text = recipe_text.replace("duration_s: 10", "duration_s: 0.3")
    recipe_text = recipe_text.replace("wait_time: 12", "wait_time: 1")
    recipe = work_dir / "stepgraph_demo.yml"
    recipe.write_text(recipe_text, encoding="utf-8")

    load_recipe(engine.core, recipe)
    with caplog.at_level(logging.WARNING):
        events = run_to_report(engine.core, "Main")

    started = next(m for m in events if isinstance(m, RunStarted))
    streams_dir = Path(started.run_dir) / "streams"
    for name in ("sine", "bg_sine"):
        with (streams_dir / f"{name}.csv").open(encoding="utf-8", newline="") as csv_file:
            rows = list(csv.reader(csv_file))
        assert rows[0] == ["x", "y [V]"]
        assert len(rows) > 1, f"{name}.csv has no sample rows"

    typo_warnings = [r for r in caplog.records if "no stream of that name" in r.getMessage()]
    assert typo_warnings == []
    assert not any(t.name == "bg_sine" and t.is_alive() for t in threading.enumerate())
