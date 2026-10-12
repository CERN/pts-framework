"""
Unit tests for RunDisplay (src/pypts/hmi/gui/run_display.py): which picture
the right column shows during a run, and the run card's numbers. No Qt.
"""

import uuid

from pypts.hmi.gui.run_display import RunDisplay
from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import RecipeLoaded, SequenceSummary, StepSummary


def _row(name, image_path=None, depth=0, is_group=False):
    return StepSummary(
        step_id=uuid.uuid4(),
        step_name=name,
        description=f"{name} does things",
        depth=depth,
        is_group=is_group,
        image_path=image_path,
    )


def _outcome(row, result=ResultType.PASS):
    return StepOutcome(step_id=row.step_id, step_name=row.step_name, result=result)


def _display(main_image=None, called_image=None):
    """Main: own (a.png), plain, call (call.png) -> Called: inner, inner_bare."""
    rows = {
        "own": _row("own", "a.png"),
        "plain": _row("plain"),
        "call": _row("Called", "call.png", is_group=True),
        "inner": _row("inner", "inner.png", depth=1),
        "inner_bare": _row("inner_bare", depth=1),
    }
    main = SequenceSummary(
        sequence_name="Main",
        steps=(rows["own"], rows["plain"], rows["call"], rows["inner"], rows["inner_bare"]),
        image_path=main_image,
    )
    called = SequenceSummary(sequence_name="Called", steps=(), image_path=called_image)
    display = RunDisplay()
    display.set_recipe(
        RecipeLoaded(
            recipe_name="r", recipe_version="0.2", main_sequence="Main", sequences=(main, called)
        )
    )
    display.run_started(100.0)
    display.sequence_started("Main")
    return display, rows


def test_a_step_picture_shows_while_the_step_runs_and_goes_after():
    display, rows = _display()

    display.step_started(rows["own"].step_id, 101.0)
    assert display.image_path == "a.png"

    display.step_finished(_outcome(rows["own"]))
    assert display.image_path is None


def test_a_step_without_one_shows_its_sequence_picture():
    display, rows = _display(main_image="main.png")

    display.step_started(rows["plain"].step_id, 101.0)
    assert display.image_path == "main.png"


def test_nothing_anywhere_means_the_run_card():
    display, rows = _display()

    display.step_started(rows["plain"].step_id, 101.0)
    assert display.image_path is None


def test_inside_a_called_sequence_the_nearest_enclosing_picture_wins():
    """inner_bare has none and Called has none, so the Sequence step that
    called it - still running - shows its own."""
    display, rows = _display(main_image="main.png")

    display.step_started(rows["call"].step_id, 101.0)
    display.sequence_started("Called")
    display.step_started(rows["inner"].step_id, 102.0)
    assert display.image_path == "inner.png"
    display.step_finished(_outcome(rows["inner"]))

    display.step_started(rows["inner_bare"].step_id, 103.0)
    assert display.image_path == "call.png"


def test_a_called_sequence_picture_comes_before_the_calling_step():
    display, rows = _display(called_image="called.png")

    display.step_started(rows["call"].step_id, 101.0)
    display.sequence_started("CALLED")
    display.step_started(rows["inner_bare"].step_id, 102.0)
    assert display.image_path == "called.png"


def test_a_finished_sequence_takes_its_picture_with_it():
    display, rows = _display(main_image="main.png", called_image="called.png")

    display.step_started(rows["call"].step_id, 101.0)
    display.sequence_started("Called")
    assert display.image_path == "called.png"
    display.sequence_finished("Called")
    assert display.image_path == "call.png"
    display.step_finished(_outcome(rows["call"]))
    assert display.image_path == "main.png"


def test_a_lost_finish_cannot_leave_a_stale_picture():
    """The inner step's StepFinished never came; the call's pops it too."""
    display, rows = _display()

    display.step_started(rows["call"].step_id, 101.0)
    display.step_started(rows["inner"].step_id, 102.0)
    display.step_finished(_outcome(rows["call"]))

    assert display.image_path is None
    assert display.current_step() == (None, 0.0)


def test_a_finish_with_no_start_changes_nothing():
    """The engine sends a StepFinished for a row it never ran (SKIP)."""
    display, rows = _display()

    display.step_started(rows["own"].step_id, 101.0)
    display.step_finished(_outcome(rows["plain"], ResultType.SKIP))

    assert display.image_path == "a.png"


def test_the_current_step_is_the_innermost_running_one():
    display, rows = _display()

    display.step_started(rows["call"].step_id, 101.0)
    display.step_started(rows["inner"].step_id, 102.5)

    step, started_at = display.current_step()
    assert step == rows["inner"]
    assert started_at == 102.5


def test_counts_skip_the_call_rows_and_remember_the_last_failure():
    display, rows = _display()

    display.step_finished(_outcome(rows["own"], ResultType.PASS))
    display.step_finished(_outcome(rows["plain"], ResultType.FAIL))
    display.step_finished(_outcome(rows["inner"], ResultType.ERROR))
    display.step_finished(_outcome(rows["inner_bare"], ResultType.PASS))
    display.step_finished(_outcome(rows["call"], ResultType.ERROR))

    assert display.count_text() == "2 PASS · 1 FAIL · 1 ERROR"
    assert display.last_failure == "inner"


def test_a_new_run_starts_from_nothing():
    display, rows = _display()
    display.step_finished(_outcome(rows["plain"], ResultType.FAIL))
    display.step_started(rows["own"].step_id, 101.0)

    display.run_started(200.0)

    assert display.count_text() == ""
    assert display.last_failure == ""
    assert display.image_path is None
    assert display.run_started_at == 200.0


def test_run_finished_and_unloading_stop_the_run():
    display, _rows = _display(main_image="main.png")
    display.run_finished()
    assert not display.running
    assert display.image_path is None

    display.run_started(1.0)
    display.set_recipe(None)
    assert not display.running
