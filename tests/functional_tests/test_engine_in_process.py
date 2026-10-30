# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
In-process end-to-end tests: the real Core, Sequencer and Report wired together.

test_core.py proves every routing branch on a Core whose threads were never
started, and test_api_processes.py proves the whole application - but it starts
real processes and is opt-in, so no default test run exercised the real wiring.
Between the two sat a gap (codebase review 2026-10-14, #24): a regression that
dropped CSV rows could pass every always-on test.

These tests close it. `Core.start()` runs on a thread of the test process and
`start_submodules()` starts the real Sequencer and Report threads; the test
plays the frontend on the HMI link, exactly as a real one would - LoadRecipe,
StartSequence, the shutdown handshake. Only two seams are redirected, both to
tmp_path: config.ini (the Report reads `paths.reports_dir` when it is built)
and the Sequencer's run folders. Everything between the HMI link and the files
on disk is real. There is no Logger process, so there is no run log and
`RunStarted.run_log_path` is empty - same as every other unit test.
"""

import csv
import queue
import threading
import time
from pathlib import Path
from typing import NamedTuple

import pytest

from pypts.config_handler import ConfigHandler, file_locations
from pypts.core.core import Core
from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import (
    HmiStopped,
    LoadRecipe,
    ReportReady,
    ShutdownRequested,
    StartSequence,
    StopHmi,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunStarted,
    SequenceStarted,
    StepFinished,
)
from pypts.recipe.recipe_parser import current_recipe_version
from pypts.sequencer import sequencer as sequencer_module
from pypts.utilities.heartbeat_manager import HMI, REPORT, SEQUENCER

WAIT_RECIPE = Path(__file__).parents[1] / "unit_tests" / "data" / "wait_recipe.yml"

#: How long a test waits for one answer from the engine. Generous, because a
#: loaded CI runner is slow; the happy path never waits it out.
MESSAGE_TIMEOUT_S = 15.0

#: A recipe whose first step errors (negative wait) and whose second still
#: runs - test_sequencer.py's FAILING_RECIPE, taken down to the CSV here.
FAILING_RECIPE = f"""\
name: Fails
version: {current_recipe_version() or "0.2"}
description: The error path.
main_sequence: Main
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Bad wait
    wait_time: '-1'
  - steptype: Wait
    step_name: Never runs
    wait_time: '0'
"""


class Engine(NamedTuple):
    """What the fixture hands a test: the Core, its thread, its run folders."""

    core: Core
    thread: threading.Thread
    reports_dir: Path


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """
    A real Core running on a thread, with the test holding the frontend's two
    ends of the HMI link.

    The configuration is a bootstrapped file in tmp_path, because the Report
    reads `paths.reports_dir` when it is built. The run folders go under
    tmp_path too; `reports_dir_from_config` is replaced on the module *before*
    the threads start, because the Sequencer binds it when it is built.
    """
    monkeypatch.setattr(file_locations, "config_file_path", lambda: tmp_path / "config.ini")
    ConfigHandler.reset_for_testing()
    ConfigHandler.bootstrap()
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(sequencer_module, "reports_dir_from_config", lambda: str(reports_dir))

    core = Core(
        to_hmi=QueueWrapper(queue.Queue()),
        from_hmi=QueueWrapper(queue.Queue()),
    )
    thread = threading.Thread(target=core.start, name="CoreUnderTest", daemon=True)
    thread.start()

    yield Engine(core, thread, reports_dir)

    shut_down(core, thread)
    ConfigHandler.reset_for_testing()


def shut_down(core, thread):
    """
    The frontend's half of the shutdown handshake, tolerant for teardown.

    Deliberately not wait_for(): a teardown must not fail the test a second
    time when the engine is already broken. The threads are daemons, so one
    that really is stuck cannot hold pytest open either way.
    """
    if not thread.is_alive():
        return
    core.from_hmi.send(ShutdownRequested())
    deadline = time.monotonic() + MESSAGE_TIMEOUT_S
    while time.monotonic() < deadline:
        if any(isinstance(message, StopHmi) for message in core.to_hmi.receive()):
            break
        time.sleep(0.01)
    core.from_hmi.send(HmiStopped())
    thread.join(timeout=MESSAGE_TIMEOUT_S)


def wait_for(core, message_type, timeout=MESSAGE_TIMEOUT_S):
    """
    Every message CORE sends the HMI, in arrival order, up to and including
    the first `message_type`. Fails the test if it never arrives.
    """
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        for message in core.to_hmi.receive():
            seen.append(message)
            if isinstance(message, message_type):
                return seen
        time.sleep(0.01)
    names = [type(message).__name__ for message in seen]
    pytest.fail(f"No {message_type.__name__} within {timeout} s; the HMI received: {names}")


def load_recipe(core, path):
    """Load a recipe over the HMI link and return the RecipeLoaded answer."""
    core.from_hmi.send(LoadRecipe(recipe_path=str(path)))
    return wait_for(core, RecipeLoaded)[-1]


def run_to_report(core, sequence_name):
    """Start a sequence and return every HMI message up to its ReportReady."""
    core.from_hmi.send(StartSequence(sequence_name=sequence_name))
    return wait_for(core, ReportReady)


def csv_rows(run_dir):
    """The one CSV in the run folder, read back as DictReader rows."""
    csv_files = sorted(Path(run_dir).glob("*.csv"))
    assert len(csv_files) == 1, f"expected one CSV in {run_dir}, found {csv_files}"
    with csv_files[0].open(encoding="utf-8", newline="") as csv_file:
        return csv_files[0], list(csv.DictReader(csv_file))


def test_a_run_reaches_the_csv_through_the_real_engine(engine):
    """
    LoadRecipe -> StartSequence -> the step rows are in the finished CSV.

    This is the claim no unit test can make: test_core.py proves CORE forwards
    StepExecuted to a Report queue and test_report.py proves a Report given a
    StepExecuted writes a row, but only the real threads prove that the queue
    CORE sends on is the queue the running Report reads.
    """
    core = engine.core
    loaded = load_recipe(core, WAIT_RECIPE)
    assert loaded.recipe_name == "Wait demo"

    events = run_to_report(core, "Main")

    # The run's events reached the HMI in order, the flat step events included.
    kinds = [type(message) for message in events]
    assert kinds.index(RunStarted) < kinds.index(SequenceStarted)
    assert kinds.index(SequenceStarted) < kinds.index(RunFinished)
    finished = [m for m in events if isinstance(m, StepFinished)]
    assert [m.outcome.step_name for m in finished] == ["First wait", "Second wait"]

    # The Sequencer made the run folder where the fixture pointed it, and the
    # ReportReady names that same folder back to the frontend.
    started = next(m for m in events if isinstance(m, RunStarted))
    run_dir = Path(started.run_dir)
    assert run_dir.is_dir()
    assert run_dir.parent == engine.reports_dir
    ready = events[-1]
    assert Path(ready.report_dir) == run_dir
    assert Path(ready.report_path).is_file()

    # The record itself: one row per step, the run-level cells backfilled, and
    # the file renamed from the live report.csv - finish_run() really ran.
    csv_path, rows = csv_rows(run_dir)
    assert csv_path.name != "report.csv"
    assert [row["step_name"] for row in rows] == ["First wait", "Second wait"]
    assert [row["result"] for row in rows] == ["DONE", "DONE"]
    assert {row["run_result"] for row in rows} == {"DONE"}
    assert {row["recipe_name"] for row in rows} == {"Wait demo"}
    assert {row["sequence_name"] for row in rows} == {"Main"}


def test_a_failing_step_reaches_the_csv_with_the_runs_verdict(engine, tmp_path):
    """
    The error path, end to end: the step's ERROR and the run's ERROR are both
    in the CSV, and the step after the failing one still ran and was recorded.
    """
    recipe = tmp_path / "fails.yml"
    recipe.write_text(FAILING_RECIPE, encoding="utf-8")
    core = engine.core
    load_recipe(core, recipe)

    events = run_to_report(core, "Main")

    started = next(m for m in events if isinstance(m, RunStarted))
    _csv_path, rows = csv_rows(started.run_dir)
    assert [row["step_name"] for row in rows] == ["Bad wait", "Never runs"]
    assert [row["result"] for row in rows] == ["ERROR", "DONE"]
    assert "wait_time" in rows[0]["error_info"]
    assert {row["run_result"] for row in rows} == {"ERROR"}


def test_the_shutdown_handshake_ends_the_engine_cleanly(engine):
    """
    ShutdownRequested -> StopHmi comes back -> HmiStopped -> Core.start()
    returns, with every module having reported itself stopped - the handshake
    test_core.py proves message by message, run against the real threads.
    """
    core, thread, _reports_dir = engine

    # Both real threads are alive and beating through the real links before
    # anything is stopped - otherwise a Core that died at startup would make
    # the handshake below pass vacuously.
    deadline = time.monotonic() + MESSAGE_TIMEOUT_S
    while time.monotonic() < deadline:
        if all(core.modules[name].last_heartbeat is not None for name in (SEQUENCER, REPORT)):
            break
        time.sleep(0.01)
    assert core.modules[SEQUENCER].last_heartbeat is not None
    assert core.modules[REPORT].last_heartbeat is not None

    core.from_hmi.send(ShutdownRequested())
    wait_for(core, StopHmi)
    core.from_hmi.send(HmiStopped())
    thread.join(timeout=MESSAGE_TIMEOUT_S)

    assert not thread.is_alive()
    assert core.running is False
    assert all(not core.modules[name].running for name in (HMI, SEQUENCER, REPORT))


def test_an_engineering_run_writes_no_folder_and_no_csv(engine):
    """
    write_report=False, through the real engine: the run finishes on the HMI
    link with an empty run_dir, no ReportReady follows, and nothing at all
    appears under the reports folder.
    """
    core = engine.core
    load_recipe(core, WAIT_RECIPE)

    core.from_hmi.send(StartSequence(sequence_name="Main", write_report=False))
    events = wait_for(core, RunFinished)

    started = next(m for m in events if isinstance(m, RunStarted))
    assert started.run_dir == ""
    assert started.write_report is False
    # A wrongly-routed report would only announce itself after RunFinished, so
    # give it a moment to not arrive before asserting it did not.
    time.sleep(0.5)
    late = list(core.to_hmi.receive())
    assert not any(isinstance(m, ReportReady) for m in events + late)
    # The folder is only made for a run that writes a report, so the parent
    # does not even exist yet.
    assert not engine.reports_dir.exists()
