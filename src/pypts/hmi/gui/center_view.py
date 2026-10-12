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
the run card when there is none. An open question owns the area while it is
open - its own picture, or the logo - and the run's view comes back when it is
answered. Outside a run the area shows the logo.
"""

import time
from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.interaction_panel import InteractionPanel
from pypts.hmi.gui.log_panel import LogPanel
from pypts.hmi.gui.run_display import RunDisplay
from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import (
    RecipeLoaded,
    UserPathRequest,
    UserPromptRequest,
    UserTextRequest,
)


class CenterContent(QWidget):
    """Right-side column: the interaction panel + the log panel."""

    def __init__(self) -> None:
        super().__init__()
        self._pending: tuple[object, Callable[[str | None], None]] | None = None
        self.run_display = RunDisplay()

        self.interaction = InteractionPanel(self.run_display)
        self.interaction.response_given.connect(self._on_interaction_response)
        self.interaction.cancelled.connect(self.cancel_pending)

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

    def show_text_request(
        self, request: UserTextRequest, answer: Callable[[str | None], None]
    ) -> None:
        """The free-text question. Same contract as show_prompt(), same panel."""
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.interaction.set_text_prompt(request.message, request.image_path)

    def show_path_request(
        self, request: UserPathRequest, answer: Callable[[str | None], None]
    ) -> None:
        """The file-or-folder question. Same contract as show_prompt(), same panel."""
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.interaction.set_path_prompt(request.message, request.select, request.image_path)

    def show_idle(self) -> None:
        self.interaction.set_idle()

    # --- The picture area during a run -----------------------------------------

    def set_recipe(self, recipe: RecipeLoaded | None) -> None:
        """The recipe whose pictures the run will show; None when unloaded."""
        self.run_display.set_recipe(recipe)
        self.interaction.run_card.stop()

    def run_started(self) -> None:
        self.run_display.run_started(time.monotonic())
        self.interaction.run_card.start()
        self._show_run_view()

    def run_finished(self) -> None:
        """Back to the logo: the run's pictures and card belong to the run."""
        self.run_display.run_finished()
        self.interaction.run_card.stop()
        self.cancel_pending()
        self.show_idle()

    def sequence_started(self, sequence_name: str) -> None:
        self.run_display.sequence_started(sequence_name)
        self._show_run_view()

    def sequence_finished(self, sequence_name: str) -> None:
        self.run_display.sequence_finished(sequence_name)
        self._show_run_view()

    def step_started(self, step_id: UUID) -> None:
        self.run_display.step_started(step_id, time.monotonic())
        self._show_run_view()

    def step_finished(self, outcome: StepOutcome) -> None:
        self.run_display.step_finished(outcome)
        self._show_run_view()

    def _show_run_view(self) -> None:
        """The run's picture, or its card - unless a question owns the area."""
        if not self.run_display.running or self._pending is not None:
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
        answer(value)
        self.interaction.set_idle()
        self._show_run_view()
