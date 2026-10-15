"""RunRecord: what the Summary tab says about the last run (gui.md §14). No Qt."""

from datetime import datetime
from uuid import uuid4

from pypts.hmi.gui.run_record import RunRecord
from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.core_hmi_communication import ReportReady
from pypts.messages.run_events import RecipeLoaded, RunStarted, SequenceSummary, StepSummary

WALL = datetime(2026, 10, 14, 8, 54, 41)  # noqa: DTZ001 - local time, as the GUI shows it


def a_recipe():
    """Main: 'Checks' (a group) calls 'Measure' and 'Fans'; then 'After'."""
    rows = (
        StepSummary(step_id=uuid4(), step_name="Checks", description="", is_group=True),
        StepSummary(step_id=uuid4(), step_name="Measure", description="", depth=1),
        StepSummary(step_id=uuid4(), step_name="Fans", description="", depth=1),
        StepSummary(step_id=uuid4(), step_name="After", description=""),
    )
    return RecipeLoaded(
        recipe_name="demo",
        recipe_version="1.2",
        main_sequence="Main",
        sequences=(SequenceSummary(sequence_name="Main", steps=rows),),
    )


def outcome(row, result=ResultType.PASS, error_info=""):
    return StepOutcome(
        step_id=row.step_id, step_name=row.step_name, result=result, error_info=error_info
    )


def a_record(recipe=None, **started):
    event = RunStarted(recipe_name="demo", recipe_description="", **started)
    return RunRecord.start(event, "Main", recipe, 100.0, WALL)


def test_a_record_starts_from_run_started_and_the_recipe():
    recipe = a_recipe()
    record = a_record(recipe, pypts_version="0.9", run_dir="C:/runs/1", write_report=False)

    assert record.recipe_version == "1.2", "taken from the recipe when RunStarted has none"
    assert record.sequence_name == "Main"
    assert record.pypts_version == "0.9"
    assert record.run_folder() == "C:/runs/1"
    assert record.write_report is False
    assert record.result is None
    assert record.group_ids == {recipe.sequences[0].steps[0].step_id}


def test_group_rows_are_not_counted_and_times_come_from_the_events():
    recipe = a_recipe()
    checks, measure, fans, after = recipe.sequences[0].steps
    record = a_record(recipe)
    record.step_started(checks.step_id, 100.0)
    record.step_started(measure.step_id, 100.0)
    record.step_finished(outcome(measure), 103.0)
    record.step_started(fans.step_id, 103.0)
    record.step_finished(outcome(fans, ResultType.FAIL, "Too slow."), 104.0)
    record.step_finished(outcome(checks, ResultType.FAIL), 104.0)
    record.step_started(after.step_id, 104.0)
    record.step_finished(outcome(after, ResultType.DONE), 104.5)

    assert [step.step_name for step in record.outcomes] == ["Measure", "Fans", "After"]
    assert record.counts_text() == "1 PASS · 1 FAIL · 1 DONE"
    assert record.pass_rate_text() == "50 % passed (1 of 2 judged steps)"
    assert [(step.step_name, step.seconds) for step in record.slowest(2)] == [
        ("Measure", 3.0),
        ("Fans", 1.0),
    ]
    assert [step.step_name for step in record.failures()] == ["Fans"]
    assert record.duration(110.0) == 10.0, "still running: up to now"


def test_run_finished_outcomes_replace_the_ones_collected():
    recipe = a_recipe()
    checks, measure, fans, _after = recipe.sequences[0].steps
    record = a_record(recipe)
    record.step_finished(outcome(measure), 101.0)

    record.finish(
        ResultType.FAIL, (outcome(measure), outcome(fans, ResultType.ERROR), outcome(checks)), 107.5
    )

    assert record.result == ResultType.FAIL
    assert [step.step_name for step in record.outcomes] == ["Measure", "Fans"]
    assert record.duration(500.0) == 7.5, "finished: the clock has stopped"


def test_no_judged_step_has_no_pass_rate():
    recipe = a_recipe()
    record = a_record(recipe)
    record.finish(ResultType.DONE, (outcome(recipe.sequences[0].steps[3], ResultType.DONE),), 101.0)

    assert record.pass_rate_text() == ""


def test_metadata_keeps_the_latest_value_of_each_name():
    record = a_record()
    record.set_metadata((("serial_number", "SN-1"), ("board", "A")))
    record.set_metadata((("serial_number", "SN-2"),))

    assert record.metadata == {"serial_number": "SN-2", "board": "A"}


def test_the_csv_is_found_beside_the_report_or_as_report_csv(tmp_path):
    record = a_record()
    report = tmp_path / "BOARD_20261014.html"
    record.report_ready(ReportReady(report_path=str(report), report_dir=str(tmp_path)))

    assert record.csv_path() == "", "neither file is on disk"
    assert record.run_folder() == str(tmp_path), "the report names the folder"

    (tmp_path / "report.csv").write_text("x", encoding="utf-8")
    assert record.csv_path() == str(tmp_path / "report.csv")

    (tmp_path / "BOARD_20261014.csv").write_text("x", encoding="utf-8")
    assert record.csv_path() == str(tmp_path / "BOARD_20261014.csv")
