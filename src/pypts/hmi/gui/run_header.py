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
    verdicts so far and the last failure (the clocks show tenths of a
    second and tick ten times a second; time paused is not taken off);
    looking back, how long the step took
  - its results: the values it was given and returned against what they were
    checked with, and the reason it failed, if it did - "No results yet."
    while it runs
  - looking back at a sequence (a group row): its steps - the verdict counts,
    then every step under it at any depth, indented, with its state, how long
    it took and why it failed; in a scroll area no taller than STEPS_MAX_HEIGHT

The state is in RunDisplay; this is only the view.
"""

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from pypts.hmi.gui.palette import UNKNOWN_VERDICT, Palette, get_palette
from pypts.hmi.gui.run_display import (
    REVIEW_FINISHED,
    REVIEW_PENDING,
    RunDisplay,
    StepReview,
    steps_counts_text,
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

#: Above a looked-back sequence's steps, followed by their verdict counts.
STEPS_HEADING = "Steps"

#: The tallest the steps list grows, in pixels, before it scrolls.
STEPS_MAX_HEIGHT = 240

#: Before a group's name in the steps list, and the indent for one level deeper.
_GROUP_MARK = "▸"
_STEP_INDENT = "&nbsp;" * 4

#: The chip keys in `Palette.verdicts` for the two states without a verdict.
_PENDING_CHIP = "PENDING"
_RUNNING_CHIP = "RUNNING"


#: How often the live clocks are redrawn: they show tenths of a second.
TICK_MS = 100


def elapsed_text(seconds: float) -> str:
    """
    `0:00.5`, `4:07.3`, or `1:02:07.3` from an hour on. Negative counts as zero.

    Cut down to the tenth, not rounded, so a clock never shows a tenth that
    has not passed yet. The GUI's own timing, from when the events arrive: it
    can differ from the report's `duration_s` by the time a message takes.
    """
    # round() first: 2.3 * 10 is 22.999999999999996, which int() would make 2.2.
    tenths_total = int(round(max(seconds, 0) * 10, 6))
    total, tenth = divmod(tenths_total, 10)
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{rest:02d}.{tenth}"
    return f"{minutes}:{rest:02d}.{tenth}"


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


def steps_heading_text(steps: tuple[StepReview, ...]) -> str:
    """"Steps: 4 PASS · 1 SKIP", or "Steps" while none has finished."""
    counts = steps_counts_text(steps)
    if not counts:
        return STEPS_HEADING
    return f"{STEPS_HEADING}: {counts}"


def steps_html(steps: tuple[StepReview, ...], group_depth: int, palette: Palette) -> str:
    """
    A looked-back sequence's steps as a rich-text table, one row each: the state
    chip, the name indented below the group, how long it took. A FAIL or ERROR
    with a reason has it on a row of its own under the name.
    """
    rows = []
    for review in steps:
        chip = palette.verdicts.get(_review_chip_key(review), UNKNOWN_VERDICT)
        state = html.escape(review_state_text(review))
        indent = _STEP_INDENT * max(review.step.depth - group_depth - 1, 0)
        name = html.escape(review.step.step_name)
        if review.step.is_group:
            name = f"{_GROUP_MARK} {name}"
        took = ""
        if review.duration is not None:
            took = elapsed_text(review.duration)
        rows.append(
            "<tr>"
            f'<td><span style="background-color:{chip.background}; color:{chip.text};'
            f' font-weight:600;">&nbsp;{state}&nbsp;</span></td>'
            f'<td style="color:{palette.text};">{indent}{name}</td>'
            f'<td style="color:{palette.text_muted};" align="right">{took}</td>'
            "</tr>"
        )
        outcome = review.outcome
        if outcome is not None and outcome.error_info:
            reason = html.escape(outcome.error_info).replace("\n", "<br>")
            rows.append(
                "<tr><td></td>"
                f'<td colspan="2" style="color:{palette.danger};">'
                f"{indent}{_STEP_INDENT}{reason}</td></tr>"
            )
    return '<table cellspacing="0" cellpadding="2">' + "".join(rows) + "</table>"


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
        # A looked-back sequence's steps (§19): the heading with the counts, and
        # the list in a scroll area, so a long sequence cannot push the picture
        # and a question off the column.
        self.steps_heading_label = QLabel()
        self.steps_label = QLabel()
        self.steps_label.setTextFormat(Qt.TextFormat.RichText)
        # Wrapped to the card's width, never scrolled sideways: a long reason
        # would push the durations out of sight.
        self.steps_label.setWordWrap(True)
        self.steps_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.steps_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.steps_area = QScrollArea()
        self.steps_area.setWidget(self.steps_label)
        self.steps_area.setWidgetResizable(True)
        self.steps_area.setFrameShape(QFrame.Shape.NoFrame)
        self.steps_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.steps_area.viewport().setAutoFillBackground(False)
        self.steps_label.setAutoFillBackground(False)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        # Only the chip is held to its own width. A word-wrapped label given an
        # alignment gets its preferred width and the height for it, so a long
        # line is wrapped narrow and cut off: the text labels take the full width.
        column.addWidget(self.heading_label)
        column.addWidget(self.step_label)
        column.addWidget(self.description_label)
        column.addWidget(self.state_label, alignment=Qt.AlignmentFlag.AlignLeft)
        column.addWidget(self.info_label)
        column.addWidget(self.results_label)
        column.addWidget(self.error_label)
        column.addWidget(self.steps_heading_label)
        column.addWidget(self.steps_area)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
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
        self.steps_heading_label.setStyleSheet(
            f"font-size:11px; font-weight:600; color:{palette.section_label};"
        )
        self.steps_label.setStyleSheet("font-size:12px; background:transparent;")
        self._paint_chip()
        if self._review is not None:
            # The steps list carries its colours in its text.
            self._set_steps(self._review)

    # --- the clock -------------------------------------------------------------

    def start(self) -> None:
        """Draw now and tick every TICK_MS."""
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
        self._hide_steps()
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
        self._set_steps(review)
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

    def _set_steps(self, review: StepReview) -> None:
        """A sequence's steps under its results; nothing for a step."""
        if not review.steps:
            self._hide_steps()
            return
        palette = get_palette(self._dark)
        self.steps_heading_label.setText(steps_heading_text(review.steps))
        self.steps_heading_label.setVisible(True)
        text = steps_html(review.steps, review.step.depth, palette)
        # The clock redraws the card ten times a second: only a change is laid out.
        if text != self.steps_label.text():
            self.steps_label.setText(text)
            self._fit_steps()
        self.steps_area.setVisible(True)

    def _fit_steps(self) -> None:
        """The steps area as tall as its list at the width it has, up to STEPS_MAX_HEIGHT."""
        width = self.steps_area.viewport().width()
        if width > 0:
            list_height = self.steps_label.heightForWidth(width)
        else:
            list_height = self.steps_label.sizeHint().height()
        self.steps_area.setFixedHeight(min(list_height, STEPS_MAX_HEIGHT))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's name
        """A wrapped list is taller or shorter at a new width."""
        super().resizeEvent(event)
        if not self.steps_area.isHidden():
            self._fit_steps()

    def _hide_steps(self) -> None:
        self.steps_heading_label.setVisible(False)
        self.steps_area.setVisible(False)
        self.steps_label.clear()

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
