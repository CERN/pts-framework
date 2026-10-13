# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The right-side content: InteractionPanel (idle / prompt / text / path) + LogPanel.

The left side (the Run | Results tabs) is owned by PtsMainWindow. This widget
manages only the right column and the exact-once answer contract:

  - A new request first declines any unanswered one.
  - Answering clears the pending pair *before* invoking the callback.
  - cancel_pending() declines whatever is still open. Three things call it:
    RunFinished, a superseding request, and the operator's own Cancel button.
    All three answer None, and the step that asked turns that into an ERROR.

All three questions live in the one InteractionPanel, which is why there is no
stack here any more: a button prompt, a text prompt and a path prompt differ by
which row is shown under the same picture and the same message. The panel that used to sit
beside it asked specifically for a serial number - a question the framework no
longer has an opinion about, since a recipe asks it with a UserWrite step.

**The picture area during a run** (gui.md §18) is decided here, from a
RunDisplay fed the run's events: the innermost step or sequence picture, or
the run card when there is none. An open question with a picture of its own
owns the area while it is open, and the run's view comes back when it is
answered; a question without one leaves the run's view where it is. Outside a
run the area shows the logo - or, once a run has ended, the logo marked
"TESTS PASSED" or "TESTS FAILED" until the next run or another recipe.

**Looking back at a step** (gui.md §19): a click on a step row during or after
a run shows that step's picture - the one it had - or its card, under a bar
naming it. During a run the live view comes back when the next step starts, a
question arrives, or the operator presses Back to live; after a run, Back
returns to the end-of-run picture. Clicking the step running now is the live
view. While a question is open a click shows nothing new: the question needs
the area.
"""

import time
from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.interaction_panel import InteractionPanel
from pypts.hmi.gui.log_panel import LogPanel
from pypts.hmi.gui.resources import RUN_FAILED_IMAGE, RUN_PASSED_IMAGE
from pypts.hmi.gui.run_display import RunDisplay
from pypts.logger.log import log
from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import (
    RecipeLoaded,
    UserPathRequest,
    UserPromptRequest,
    UserTextRequest,
)


def run_result_image(result: ResultType) -> str | None:
    """
    Which end-of-run picture a run's result gets: PASS and DONE passed,
    FAIL, ERROR and STOP failed. SKIP tested nothing, so it keeps the plain
    logo (None).
    """
    if result in (ResultType.PASS, ResultType.DONE):
        return RUN_PASSED_IMAGE
    if result in (ResultType.FAIL, ResultType.ERROR, ResultType.STOP):
        return RUN_FAILED_IMAGE
    return None


class CenterContent(QWidget):
    """Right-side column: the interaction panel + the log panel."""

    def __init__(self) -> None:
        super().__init__()
        self._pending: tuple[object, Callable[[str | None], None]] | None = None
        # The open question's own picture. Only a question that has one takes
        # the picture area away from the run.
        self._pending_image_path: str | None = None
        # The step being looked back at (gui.md §19), None for none.
        self._reviewing: UUID | None = None
        self.run_display = RunDisplay()

        self.interaction = InteractionPanel(self.run_display)
        self.interaction.response_given.connect(self._on_interaction_response)
        self.interaction.cancelled.connect(self.cancel_pending)
        self.interaction.review_closed.connect(self.close_review)

        log_label = QLabel("LOG OUTPUT")
        log_label.setObjectName("sectionLabel")
        self.log_panel = LogPanel()

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.interaction, stretch=1)
        column.addWidget(log_label)
        column.addWidget(self.log_panel)

    # --- Compatibility properties for tests ------------------------------------

    @property
    def prompt_message(self):
        return self.interaction.message_label

    @property
    def option_buttons(self):
        return self.interaction._buttons

    # --- Dark mode -------------------------------------------------------------

    def set_dark(self, dark: bool) -> None:
        self.interaction.set_dark(dark)
        self.log_panel.set_dark(dark)

    # --- The questions ---------------------------------------------------------

    def show_prompt(
        self, request: UserPromptRequest, answer: Callable[[str | None], None]
    ) -> None:
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.interaction.set_prompt(
            request.message,
            [{"label": opt, "value": opt} for opt in request.options],
            request.image_path,
        )
        self._question_shown(request.image_path)

    def show_text_request(
        self, request: UserTextRequest, answer: Callable[[str | None], None]
    ) -> None:
        """The free-text question. Same contract as show_prompt(), same panel."""
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.interaction.set_text_prompt(request.message, request.image_path)
        self._question_shown(request.image_path)

    def show_path_request(
        self, request: UserPathRequest, answer: Callable[[str | None], None]
    ) -> None:
        """The file-or-folder question. Same contract as show_prompt(), same panel."""
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.interaction.set_path_prompt(request.message, request.select, request.image_path)
        self._question_shown(request.image_path)

    def _question_shown(self, image_path: str | None) -> None:
        """
        A question without a picture of its own puts the run's view back over
        the logo the panel drew for it - the operator keeps seeing the run.
        A question also ends a look back at a step: it needs the operator.
        """
        self._end_review()
        self._pending_image_path = image_path
        self._show_run_view()

    def show_idle(self) -> None:
        self.interaction.set_idle()

    # --- Looking back at a step ------------------------------------------------

    def review_step(self, step_id: UUID) -> None:
        """
        A click on a step row: show the picture that step had, or its card.

        Nothing before the first run since the recipe was loaded, nothing while a
        question is open, and the step running now is simply the live view.
        """
        if self._pending is not None:
            log.debug("Step %s clicked: a question is open, nothing to look back at.", step_id)
            return
        review = self.run_display.review(step_id)
        if review is None:
            log.debug("Step %s clicked: no run to look back at.", step_id)
            return
        if self.run_display.running and self.run_display.is_running_step(step_id):
            log.debug("Step %s clicked: it is the running step, the live view.", step_id)
            self.close_review()
            return
        log.debug("Looking back at step '%s' (%s).", review.step.step_name, review.state)
        self._reviewing = step_id
        self.interaction.show_review(review, during_run=self.run_display.running)

    def is_reviewing(self) -> bool:
        return self._reviewing is not None

    def close_review(self) -> None:
        """Back to the live view during a run, to the end-of-run picture after one."""
        self._end_review()
        if self.run_display.running:
            self._show_run_view()
        else:
            self.show_idle()

    def _end_review(self) -> None:
        """Forget the step looked at and take the bar down; the caller repaints."""
        self._reviewing = None
        self.interaction.hide_review()

    # --- The picture area during a run -----------------------------------------

    def set_recipe(self, recipe: RecipeLoaded | None) -> None:
        """The recipe whose pictures the run will show; None when unloaded."""
        self._end_review()
        self.run_display.set_recipe(recipe)
        self.interaction.run_card.stop()
        # The last run's verdict belonged to the recipe it ran.
        self.interaction.set_run_result(None)

    def run_started(self) -> None:
        self._end_review()
        self.interaction.set_run_result(None)
        self.run_display.run_started(time.monotonic())
        self.interaction.run_card.start()
        self._show_run_view()

    def run_finished(self, result: ResultType) -> None:
        """
        Back to the logo, marked with how the run ended: the run's pictures
        and card belong to the run. Its steps can still be looked back at.
        """
        self._end_review()
        self.run_display.run_finished()
        self.interaction.run_card.stop()
        self.cancel_pending()
        self.show_idle()
        self.interaction.set_run_result(run_result_image(result))

    def sequence_started(self, sequence_name: str) -> None:
        self.run_display.sequence_started(sequence_name)
        self._show_run_view()

    def sequence_finished(self, sequence_name: str) -> None:
        self.run_display.sequence_finished(sequence_name)
        self._show_run_view()

    def step_started(self, step_id: UUID) -> None:
        # The next step: the live view comes back (gui.md §19).
        self._end_review()
        self.run_display.step_started(step_id, time.monotonic())
        self._show_run_view()

    def step_finished(self, outcome: StepOutcome) -> None:
        self.run_display.step_finished(outcome, time.monotonic())
        self._show_run_view()

    def _show_run_view(self) -> None:
        """
        The run's picture, or its card - unless a question with a picture owns
        the area, or a step is being looked back at.
        """
        if not self.run_display.running:
            return
        if self._pending is not None and self._pending_image_path:
            return
        if self._reviewing is not None:
            return
        image_path = self.run_display.image_path
        if image_path:
            self.interaction.set_image(image_path)
        else:
            self.interaction.show_run_card()

    def cancel_pending(self) -> None:
        """Decline whatever question is still open. Idempotent."""
        if self._pending is not None:
            self._answer(None)

    def _on_interaction_response(self, value: str) -> None:
        self._answer(value)

    def _answer(self, value: str | None) -> None:
        """The exactly-once gate: clear first, then call, then back to idle."""
        if self._pending is None:
            return
        _request_id, answer = self._pending
        self._pending = None
        self._pending_image_path = None
        answer(value)
        self.interaction.set_idle()
        self._show_run_view()
