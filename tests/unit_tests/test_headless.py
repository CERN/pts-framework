"""
Unit tests for headless mode (src/pypts/api/headless.py) and the launcher
arguments that reach it (src/pypts/launcher/startup.py).

No process is started: headless_main() is given a scripted stand-in for Pts,
and main() is stopped at headless_main() or at argparse.
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from pypts.api import headless
from pypts.api.embedding import LoadedRecipe, PtsError, RunResult, StepVerdict
from pypts.launcher import startup
from pypts.messages.common_messages import ResultType


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (ResultType.PASS, 0),
        (ResultType.DONE, 0),
        (ResultType.FAIL, 1),
        (ResultType.ERROR, 2),
        (ResultType.STOP, 2),
        (ResultType.SKIP, 2),
    ],
)
def test_exit_code_for_each_run_result(result, code):
    assert headless.exit_code_for(result) == code


# --------------------------------------------------------------------------
# headless_main()
# --------------------------------------------------------------------------

LOADED = LoadedRecipe(
    name="Bench", version="1.0", main_sequence="Main", sequences=("Main", "Cal")
)


class FakePts:
    """Everything headless_main() uses of Pts, with the answers scripted."""

    def __init__(self, load=LOADED, result=ResultType.PASS, run_error=None):
        self.load = load
        self.result = result
        self.run_error = run_error
        self.run_calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True

    def load_recipe(self, path):
        if isinstance(self.load, Exception):
            raise self.load
        return self.load

    def run(self, sequence=None, answer=None, on_step=None):
        self.run_calls.append((sequence, answer))
        if self.run_error is not None:
            raise self.run_error
        step = StepVerdict("First step", self.result)
        on_step(step)
        return RunResult(
            sequence=sequence or "Main", result=self.result, steps=(step,), report_dir="C:/r/1"
        )


@pytest.fixture
def recipe(tmp_path):
    path = tmp_path / "bench.yml"
    path.write_text("name: Bench\n")
    return str(path)


def use_fake(monkeypatch, fake):
    monkeypatch.setattr(headless, "HeadlessPts", lambda **kwargs: fake)


def test_a_passing_run_exits_zero_and_prints_the_run(monkeypatch, capsys, recipe):
    fake = FakePts()
    use_fake(monkeypatch, fake)

    assert headless.headless_main(recipe) == 0

    assert fake.run_calls == [(None, headless.decline_question)]
    assert fake.closed is True
    printed = capsys.readouterr().out
    assert "Recipe loaded: Bench (version 1.0)" in printed
    assert "First step: PASS" in printed
    assert "Run finished: PASS (1 steps)" in printed
    assert "Report: C:/r/1" in printed


def test_a_failing_run_exits_one(monkeypatch, recipe):
    use_fake(monkeypatch, FakePts(result=ResultType.FAIL))

    assert headless.headless_main(recipe, "Cal") == 1


def test_a_missing_recipe_exits_three_without_starting_anything(monkeypatch, capsys, tmp_path):
    def must_not_start(**kwargs):
        raise AssertionError("nothing is started for a recipe that is not there")

    monkeypatch.setattr(headless, "HeadlessPts", must_not_start)

    assert headless.headless_main(str(tmp_path / "missing.yml")) == 3
    assert "Recipe file not found" in capsys.readouterr().err


def test_a_refused_recipe_exits_three_and_closes_the_engine(monkeypatch, capsys, recipe):
    fake = FakePts(load=PtsError("The recipe was not loaded: bad step"))
    use_fake(monkeypatch, fake)

    assert headless.headless_main(recipe) == 3
    assert fake.closed is True
    assert "bad step" in capsys.readouterr().err


def test_an_unknown_sequence_exits_three_without_running(monkeypatch, capsys, recipe):
    fake = FakePts()
    use_fake(monkeypatch, fake)

    assert headless.headless_main(recipe, "Nope") == 3
    assert fake.run_calls == []
    assert "Main, Cal" in capsys.readouterr().err


def test_an_engine_that_stops_mid_run_exits_three(monkeypatch, recipe):
    stopped = PtsError("The engine stopped while the run was going.")
    use_fake(monkeypatch, FakePts(run_error=stopped))

    assert headless.headless_main(recipe) == 3


def test_an_engine_that_cannot_start_exits_three(monkeypatch, capsys, recipe):
    def broken(**kwargs):
        raise OSError("no queues today")

    monkeypatch.setattr(headless, "HeadlessPts", broken)

    assert headless.headless_main(recipe) == 3
    assert "no queues today" in capsys.readouterr().err


def test_every_question_is_declined_and_said_on_the_console(capsys):
    request = SimpleNamespace(message="Is the LED on?")

    assert headless.decline_question(request) is None
    assert "Question declined (headless mode): Is the LED on?" in capsys.readouterr().out


def test_headless_mode_names_itself_in_the_run_log():
    assert headless.HeadlessPts.MODE == "headless"


# --------------------------------------------------------------------------
# The launcher's arguments
# --------------------------------------------------------------------------


def bootstrap_must_not_run():
    raise AssertionError("a rejected command line starts nothing")


def run_main(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["pypts", *arguments])
    monkeypatch.setattr(startup.ConfigHandler, "bootstrap", bootstrap_must_not_run)
    with pytest.raises(SystemExit) as exit_info:
        startup.main()
    return exit_info.value.code


def test_a_bad_command_line_exits_with_headless_modes_no_run_code():
    assert startup.USAGE_EXIT_CODE == headless.EXIT_NOT_RUN


def test_headless_mode_needs_a_recipe(monkeypatch, capsys):
    assert run_main(monkeypatch, "--mode", "headless") == 3
    assert "needs --recipe" in capsys.readouterr().err


@pytest.mark.parametrize("argument", ["--recipe", "--sequence"])
def test_recipe_and_sequence_are_refused_outside_headless_mode(monkeypatch, argument):
    assert run_main(monkeypatch, "--mode", "cli", argument, "x") == 3


def test_an_unknown_option_exits_three(monkeypatch):
    assert run_main(monkeypatch, "--no-such-option") == 3


def test_headless_mode_hands_over_to_headless_main(monkeypatch):
    calls = []

    def fake_headless_main(recipe, sequence, log_level, debug_monitor):
        calls.append((recipe, sequence, log_level, debug_monitor))
        return 1

    monkeypatch.setattr(headless, "headless_main", fake_headless_main)

    code = run_main(
        monkeypatch, "--mode", "headless", "--recipe", "b.yml", "--sequence", "Cal",
        "--log-level", "INFO",
    )

    assert code == 1
    # Off by default in headless mode: there is nobody to look at the window.
    assert calls == [("b.yml", "Cal", "INFO", False)]

    calls.clear()
    run_main(monkeypatch, "--mode", "headless", "--recipe", "b.yml", "--debug-monitor")
    assert calls == [("b.yml", None, None, True)]


def test_the_headless_mode_does_not_import_qt():
    check = (
        "import sys, pypts.api.headless; "
        "sys.exit(any(m.startswith('PySide6') for m in sys.modules))"
    )

    subprocess.run([sys.executable, "-c", check], check=True)
