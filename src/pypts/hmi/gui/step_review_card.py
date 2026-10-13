# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
StepReviewCard: a step looked back at that had no picture (gui.md §19).

The run card's sibling: where the run card follows the step running now, this
one stands still on the step the operator clicked - its name and what it does,
where it got to (not run yet, running, or its verdict), how long it took, the
values it was given and returned against what they were checked with, and the
reason it failed, if it did. It draws a `StepReview`; the state is in
RunDisplay.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.palette import UNKNOWN_VERDICT, get_palette
from pypts.hmi.gui.run_card import elapsed_text
from pypts.hmi.gui.run_display import REVIEW_FINISHED, REVIEW_PENDING, StepReview
from pypts.utilities.common import describe_step_values

#: What the card says above the step name.
HEADING = "LOOKING BACK"

#: The state line before the step has a verdict - also the chip it is drawn on.
PENDING_TEXT = "Not run yet"
RUNNING_TEXT = "Running..."


class StepReviewCard(QWidget):
    """The card for one looked-back step. show_review() draws it."""

    def __init__(self) -> None:
        super().__init__()
        self._dark = False
        self._review: StepReview | None = None

        self.heading_label = QLabel(HEADING)
        self.step_label = QLabel()
        self.step_label.setWordWrap(True)
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.state_label = QLabel()
        self.duration_label = QLabel()
        self.values_label = QLabel()
        self.values_label.setWordWrap(True)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        column.addStretch()
        for label in (
            self.heading_label,
            self.step_label,
            self.description_label,
            self.state_label,
            self.duration_label,
            self.values_label,
            self.error_label,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)
        column.addStretch()
        self.set_dark(False)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        palette = get_palette(dark)
        self.heading_label.setStyleSheet(
            f"font-size:11px; font-weight:600; color:{palette.section_label};"
        )
        self.step_label.setStyleSheet(f"font-size:16px; font-weight:600; color:{palette.text};")
        self.description_label.setStyleSheet(f"font-size:12px; color:{palette.text_muted};")
        self.duration_label.setStyleSheet(f"font-size:13px; color:{palette.text};")
        self.values_label.setStyleSheet(f"font-size:12px; color:{palette.text};")
        failed = palette.verdicts["FAIL"]
        self.error_label.setStyleSheet(
            f"font-size:12px; color:{failed.text}; background-color:{failed.background};"
            "border-radius:4px; padding:2px 8px;"
        )
        self._paint_state()

    def show_review(self, review: StepReview) -> None:
        self._review = review
        step = review.step
        self.step_label.setText(step.step_name)
        self.description_label.setText(step.description)
        self.description_label.setVisible(bool(step.description))

        outcome = review.outcome
        if review.duration is None:
            self.duration_label.setText("")
        else:
            self.duration_label.setText(f"Took {elapsed_text(review.duration)}")
        self.duration_label.setVisible(review.duration is not None)

        lines = []
        error_text = ""
        if outcome is not None:
            lines = describe_step_values(
                dict(outcome.inputs), dict(outcome.outputs), dict(outcome.expectations)
            )
            error_text = outcome.error_info
        self.values_label.setText("\n".join(lines))
        self.values_label.setVisible(bool(lines))
        self.error_label.setText(error_text)
        self.error_label.setVisible(bool(error_text))
        self._paint_state()

    def state_text(self) -> str:
        """The state line: "Not run yet", "Running..." or the verdict's name."""
        review = self._review
        if review is None:
            return ""
        if review.state == REVIEW_PENDING:
            return PENDING_TEXT
        if review.state == REVIEW_FINISHED and review.outcome is not None:
            return str(review.outcome.result)
        return RUNNING_TEXT

    def _paint_state(self) -> None:
        """The state line on its verdict chip's colours, in the current theme."""
        review = self._review
        if review is None:
            return
        if review.state == REVIEW_PENDING:
            key = "PENDING"
        elif review.state == REVIEW_FINISHED and review.outcome is not None:
            key = review.outcome.result.name
        else:
            key = "RUNNING"
        chip = get_palette(self._dark).verdicts.get(key, UNKNOWN_VERDICT)
        self.state_label.setText(self.state_text())
        self.state_label.setStyleSheet(
            f"font-size:13px; font-weight:600; color:{chip.text};"
            f"background-color:{chip.background}; border-radius:4px; padding:2px 10px;"
        )
