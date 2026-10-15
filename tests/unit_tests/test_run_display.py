"""
Unit tests for RunDisplay (src/pypts/hmi/gui/run_display.py): which picture
the right column shows during a run, and the header's numbers. No Qt.
"""

import uuid

from pypts.hmi.gui.run_display import (
    REVIEW_FINISHED,
    REVIEW_PENDING,
    REVIEW_RUNNING,
    RunDisplay,
    steps_counts_text,
)
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

    display.step_finished(_outcome(rows["own"]), 110.0)
    assert display.image_path is None


def test_a_step_without_one_shows_its_sequence_picture():
    display, rows = _display(main_image="main.png")

    display.step_started(rows["plain"].step_id, 101.0)
    assert display.image_path == "main.png"


def test_nothing_anywhere_means_the_logo():
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
    display.step_finished(_outcome(rows["inner"]), 110.0)

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
    display.step_finished(_outcome(rows["call"]), 110.0)
    assert display.image_path == "main.png"


def test_a_lost_finish_cannot_leave_a_stale_picture():
    """The inner step's StepFinished never came; the call's pops it too."""
    display, rows = _display()

    display.step_started(rows["call"].step_id, 101.0)
    display.step_started(rows["inner"].step_id, 102.0)
    display.step_finished(_outcome(rows["call"]), 110.0)

    assert display.image_path is None
    assert display.current_step() == (None, 0.0)


def test_a_finish_with_no_start_changes_nothing():
    """The engine sends a StepFinished for a row it never ran (SKIP)."""
    display, rows = _display()

    display.step_started(rows["own"].step_id, 101.0)
    display.step_finished(_outcome(rows["plain"], ResultType.SKIP), 110.0)

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

    display.step_finished(_outcome(rows["own"], ResultType.PASS), 110.0)
    display.step_finished(_outcome(rows["plain"], ResultType.FAIL), 110.0)
    display.step_finished(_outcome(rows["inner"], ResultType.ERROR), 110.0)
    display.step_finished(_outcome(rows["inner_bare"], ResultType.PASS), 110.0)
    display.step_finished(_outcome(rows["call"], ResultType.ERROR), 110.0)

    assert display.count_text() == "2 PASS · 1 FAIL · 1 ERROR"
    assert display.last_failure == "inner"


def test_a_new_run_starts_from_nothing():
    display, rows = _display()
    display.step_finished(_outcome(rows["plain"], ResultType.FAIL), 110.0)
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


# --- Looking back at a step (gui.md §19) --------------------------------------


def test_nothing_to_look_back_at_before_the_first_run():
    display = RunDisplay()
    rows = {"own": _row("own", "a.png")}
    display.set_recipe(
        RecipeLoaded(
            recipe_name="r",
            recipe_version="0.2",
            main_sequence="Main",
            sequences=(SequenceSummary(sequence_name="Main", steps=(rows["own"],)),),
        )
    )

    assert display.review(rows["own"].step_id) is None


def test_a_finished_step_is_remembered_with_the_picture_it_had():
    """'plain' has none of its own: what was on screen was Main's picture."""
    display, rows = _display(main_image="main.png")
    display.step_started(rows["plain"].step_id, 101.0)
    display.step_finished(_outcome(rows["plain"], ResultType.FAIL), 103.5)

    review = display.review(rows["plain"].step_id)

    assert review.state == REVIEW_FINISHED
    assert review.image_path == "main.png"
    assert review.outcome.result == ResultType.FAIL
    assert review.duration == 2.5


def test_a_step_in_a_called_sequence_keeps_the_calling_step_picture():
    display, rows = _display()
    display.step_started(rows["call"].step_id, 101.0)
    display.sequence_started("Called")
    display.step_started(rows["inner_bare"].step_id, 102.0)
    display.step_finished(_outcome(rows["inner_bare"]), 103.0)

    assert display.review(rows["inner_bare"].step_id).image_path == "call.png"


def test_a_step_with_nothing_on_screen_has_no_picture_to_review():
    display, rows = _display()
    display.step_started(rows["plain"].step_id, 101.0)
    display.step_finished(_outcome(rows["plain"]), 102.0)

    assert display.review(rows["plain"].step_id).image_path is None


def test_a_step_not_run_yet_shows_its_own_picture():
    display, rows = _display(main_image="main.png")

    review = display.review(rows["own"].step_id)
    assert review.state == REVIEW_PENDING
    assert review.image_path == "a.png"
    assert review.outcome is None
    assert review.duration is None


def test_a_running_step_is_running_and_the_innermost_one_is_live():
    display, rows = _display()
    display.step_started(rows["call"].step_id, 101.0)
    display.step_started(rows["inner"].step_id, 102.0)

    assert display.review(rows["call"].step_id).state == REVIEW_RUNNING
    assert display.is_running_step(rows["inner"].step_id)
    assert not display.is_running_step(rows["call"].step_id)


def test_a_finished_run_can_still_be_looked_back_at_and_a_new_one_forgets_it():
    display, rows = _display()
    display.step_started(rows["own"].step_id, 101.0)
    display.step_finished(_outcome(rows["own"]), 102.0)
    display.run_finished()

    assert display.review(rows["own"].step_id).state == REVIEW_FINISHED

    display.run_started(200.0)
    assert display.review(rows["own"].step_id).state == REVIEW_PENDING


def test_a_skipped_step_that_never_started_is_finished_with_no_picture():
    display, rows = _display(main_image="main.png")
    display.step_finished(_outcome(rows["plain"], ResultType.SKIP), 105.0)

    review = display.review(rows["plain"].step_id)
    assert review.state == REVIEW_FINISHED
    assert review.outcome.result == ResultType.SKIP
    assert review.image_path is None


def test_a_group_is_looked_back_at_with_every_step_under_it():
    display, rows = _display()
    display.step_started(rows["call"].step_id, 101.0)
    display.step_started(rows["inner"].step_id, 102.0)
    display.step_finished(_outcome(rows["inner"]), 104.0)
    display.step_started(rows["inner_bare"].step_id, 104.0)
    display.step_finished(_outcome(rows["inner_bare"], ResultType.FAIL), 105.0)
    display.step_finished(_outcome(rows["call"], ResultType.FAIL), 105.0)

    review = display.review(rows["call"].step_id)

    assert [inner.step.step_name for inner in review.steps] == ["inner", "inner_bare"]
    assert [inner.outcome.result for inner in review.steps] == [ResultType.PASS, ResultType.FAIL]
    assert review.steps[0].duration == 2.0
    assert steps_counts_text(review.steps) == "1 PASS · 1 FAIL"
    assert display.review(rows["plain"].step_id).steps == ()


def test_a_group_steps_reach_every_depth_and_stop_at_its_own():
    """G opens a(1), H(1) -> b(2), c(1); d is back at G's depth."""
    rows = [
        _row("G", is_group=True),
        _row("a", depth=1),
        _row("H", depth=1, is_group=True),
        _row("b", depth=2),
        _row("c", depth=1),
        _row("d"),
    ]
    display = RunDisplay()
    display.set_recipe(
        RecipeLoaded(
            recipe_name="r",
            recipe_version="0.2",
            main_sequence="Main",
            sequences=(SequenceSummary(sequence_name="Main", steps=tuple(rows)),),
        )
    )
    display.run_started(100.0)
    display.step_finished(_outcome(rows[2]), 101.0)
    display.step_finished(_outcome(rows[3]), 101.0)

    outer = display.review(rows[0].step_id)
    inner = display.review(rows[2].step_id)

    assert [step.step.step_name for step in outer.steps] == ["a", "H", "b", "c"]
    assert [step.step.step_name for step in inner.steps] == ["b"]
    assert outer.steps[0].state == REVIEW_PENDING
    assert steps_counts_text(outer.steps) == "1 PASS", "the H call row is not counted"
