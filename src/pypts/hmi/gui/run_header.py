# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
RunHeader: the step card on top of the right column during a run (gui.md §18).

Always there while a run is on, above the picture - when there is one - and
any question:

  - the heading: NOW RUNNING, or LOOKING BACK for a clicked step (§19)
  - the step's name and what it does
  - its state on a chip in the verdict colours: Running..., or - looking
    back - its verdict, Not run yet or Running...
  - a time line: live, how long the run and the step have taken, the
    verdicts so far and the last failure (the clocks tick once a second;
    time paused is not taken off); looking back, how long the step took
  - its results: the values it was given and returned against what they were
    checked with, and the reason it failed, if it did - "No results yet."
    while it runs

The state is in RunDisplay; this is only the view.
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.palette import UNKNOWN_VERDICT, get_palette
from pypts.hmi.gui.run_display import (
    REVIEW_FINISHED,
    REVIEW_PENDING,
    RunDisplay,
    StepReview,
)
from pypts.utilities.common import describe_step_values

#: What the card says above the step name: live, and looking back.
LIVE_HEADING = "NOW RUNNING"
REVIEW_HEADING = "LOOKING BACK"

#: Shown in place of a step name between steps.
NO_STEP = "-"

#: A step's state before it has a verdict - also the chip it is drawn on.
PENDING_TEXT = "Not run yet"
RUNNING_TEXT = "Running..."

#: The results line while the step runs, and for a finished one with none.
NO_RESULTS_YET_TEXT = "No results yet."
NO_VALUES_TEXT = "No values recorded."

#: The chip keys in `Palette.verdicts` for the two states without a verdict.
_PENDING_CHIP = "PENDING"
_RUNNING_CHIP = "RUNNING"


def elapsed_text(seconds: float) -> str:
    """`4:07`, or `1:02:07` from an hour on. Negative counts as zero."""
    total = int(max(seconds, 0))
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{rest:02d}"
    return f"{minutes}:{rest:02d}"


def review_state_text(review: StepReview) -> str:
    """"Not run yet", "Running..." or the verdict's name."""
    if review.state == REVIEW_PENDING:
        return PENDING_TEXT
    if review.state == REVIEW_FINISHED and review.outcome is not None:
        return str(review.outcome.result)
    return RUNNING_TEXT


def _review_chip_key(review: StepReview) -> str:
    if review.state == REVIEW_PENDING:
        return _PENDING_CHIP
    if review.state == REVIEW_FINISHED and review.outcome is not None:
        return review.outcome.result.name
    return _RUNNING_CHIP


class RunHeader(QWidget):
    """The step card. show_live() follows the run; show_review() stands on one step."""

    def __init__(self, display: RunDisplay) -> None:
        super().__init__()
        self._display = display
        self._dark = False
        self._review: StepReview | None = None
        # The chip key the state label is painted in, "" when it is hidden.
        self._chip_key = ""

        self.heading_label = QLabel(LIVE_HEADING)
        self.step_label = QLabel(NO_STEP)
        self.step_label.setWordWrap(True)
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.state_label = QLabel()
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.results_label = QLabel()
        self.results_label.setWordWrap(True)
        self.results_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        for label in (
            self.heading_label,
            self.step_label,
            self.description_label,
            self.state_label,
            self.info_label,
            self.results_label,
            self.error_label,
        ):
            column.addWidget(label, alignment=Qt.AlignmentFlag.AlignLeft)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.set_dark(False)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        palette = get_palette(dark)
        self.heading_label.setStyleSheet(
            f"font-size:11px; font-weight:600; color:{palette.section_label};"
        )
        self.step_label.setStyleSheet(f"font-size:16px; font-weight:600; color:{palette.text};")
        self.description_label.setStyleSheet(f"font-size:12px; color:{palette.text_muted};")
        self.info_label.setStyleSheet(f"font-size:11px; color:{palette.text_muted};")
        self.results_label.setStyleSheet(f"font-size:12px; color:{palette.text};")
        failed = palette.verdicts["FAIL"]
        self.error_label.setStyleSheet(
            f"font-size:12px; color:{failed.text}; background-color:{failed.background};"
            "border-radius:4px; padding:2px 8px;"
        )
        self._paint_chip()

    # --- the clock -------------------------------------------------------------

    def start(self) -> None:
        """Draw now and tick once a second."""
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def is_ticking(self) -> bool:
        return self._timer.isActive()

    # --- what it shows ---------------------------------------------------------

    def show_live(self) -> None:
        """Follow the run again."""
        self._review = None
        self.refresh()

    def show_review(self, review: StepReview) -> None:
        """Stand on one looked-back step until show_live()."""
        self._review = review
        self.refresh()

    def is_reviewing(self) -> bool:
        return self._review is not None

    def state_text(self) -> str:
        """The chip's text, "" when there is no chip (between steps)."""
        if self.state_label.isHidden():
            return ""
        return self.state_label.text()

    def refresh(self) -> None:
        if self._review is not None:
            self._draw_review(self._review)
        else:
            self._draw_live()

    def _draw_live(self) -> None:
        display = self._display
        now = time.monotonic()
        step, step_started_at = display.current_step()
        self.heading_label.setText(LIVE_HEADING)
        parts = [f"Run {elapsed_text(now - display.run_started_at)}"]
        if step is None:
            self.step_label.setText(NO_STEP)
            self._set_description("")
            self._set_chip("", "")
            self._set_results([], "")
        else:
            self.step_label.setText(step.step_name)
            self._set_description(step.description)
            self._set_chip(RUNNING_TEXT, _RUNNING_CHIP)
            parts.append(f"Step {elapsed_text(now - step_started_at)}")
            self._set_results([NO_RESULTS_YET_TEXT], "")
        if display.count_text():
            parts.append(display.count_text())
        if display.last_failure:
            parts.append(f"Last failure: {display.last_failure}")
        self._set_info("  ·  ".join(parts))

    def _draw_review(self, review: StepReview) -> None:
        self.heading_label.setText(REVIEW_HEADING)
        self.step_label.setText(review.step.step_name)
        self._set_description(review.step.description)
        self._set_chip(review_state_text(review), _review_chip_key(review))
        if review.duration is None:
            self._set_info("")
        else:
            self._set_info(f"Took {elapsed_text(review.duration)}")
        outcome = review.outcome
        if outcome is None:
            if review.state == REVIEW_PENDING:
                self._set_results([], "")
            else:
                self._set_results([NO_RESULTS_YET_TEXT], "")
            return
        lines = describe_step_values(
            dict(outcome.inputs), dict(outcome.outputs), dict(outcome.expectations)
        )
        if not lines and not outcome.error_info:
            lines = [NO_VALUES_TEXT]
        self._set_results(lines, outcome.error_info)

    # --- the labels ------------------------------------------------------------

    def _set_description(self, text: str) -> None:
        self.description_label.setText(text)
        self.description_label.setVisible(bool(text))

    def _set_info(self, text: str) -> None:
        self.info_label.setText(text)
        self.info_label.setVisible(bool(text))

    def _set_results(self, lines: list[str], error_text: str) -> None:
        self.results_label.setText("\n".join(lines))
        self.results_label.setVisible(bool(lines))
        self.error_label.setText(error_text)
        self.error_label.setVisible(bool(error_text))

    def _set_chip(self, text: str, key: str) -> None:
        """The state chip: `text` on the verdict colours of `key`; "" hides it."""
        self.state_label.setText(text)
        self.state_label.setVisible(bool(text))
        if key != self._chip_key:
            self._chip_key = key
            self._paint_chip()

    def _paint_chip(self) -> None:
        if not self._chip_key:
            return
        chip = get_palette(self._dark).verdicts.get(self._chip_key, UNKNOWN_VERDICT)
        self.state_label.setStyleSheet(
            f"font-size:12px; font-weight:600; color:{chip.text};"
            f"background-color:{chip.background}; border-radius:4px; padding:2px 10px;"
        )
