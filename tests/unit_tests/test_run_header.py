"""The step card's layout (gui.md §18): what it shows must fit on it."""

from uuid import uuid4

from pypts.hmi.gui.run_display import REVIEW_FINISHED, RunDisplay, StepReview
from pypts.hmi.gui.run_header import RunHeader
from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import StepSummary


def test_a_long_results_line_takes_the_card_width_and_is_not_cut_off(qapp):
    step = StepSummary(step_id=uuid4(), step_name="Wind at CERN", description="Wind speed.")
    outcome = StepOutcome(
        step_id=step.step_id,
        step_name=step.step_name,
        result=ResultType.PASS,
        outputs=(("wind_speed_kmh", "0.8"), ("wind_direction_deg", "117")),
        expectations=(("wind_speed_kmh", "range 0 .. 200"), ("wind_direction_deg", "not judged")),
    )
    card = RunHeader(RunDisplay())
    card.resize(300, 400)
    card.show()
    card.show_review(StepReview(step, REVIEW_FINISHED, None, outcome, 1.0))
    qapp.processEvents()

    label = card.results_label
    assert "wind_speed_kmh = 0.8 (range 0 .. 200)" in label.text()
    assert label.width() == card.width()
    assert label.height() >= label.heightForWidth(label.width())
    card.close()
