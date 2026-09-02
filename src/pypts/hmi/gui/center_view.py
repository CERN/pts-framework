# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The right-side content: InteractionPanel (idle / prompt / text) + LogPanel.

The left side (idle placeholder / step table / results) is owned by
PtsMainWindow and managed via _switch_screen(). This widget manages only the
right column and the exact-once answer contract:

  - A new request first declines any unanswered one.
  - Answering clears the pending pair *before* invoking the callback.
  - cancel_pending() declines whatever is still open. Three things call it:
    RunFinished, a superseding request, and the operator's own Cancel button.
    All three answer None, and the step that asked turns that into an ERROR.

Both questions live in the one InteractionPanel, which is why there is no
stack here any more: a button prompt and a text prompt differ by which row is
shown under the same picture and the same message. The panel that used to sit
beside it asked specifically for a serial number - a question the framework no
longer has an opinion about, since a recipe asks it with a UserWrite step.
"""

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.interaction_panel import InteractionPanel
from pypts.hmi.gui.log_panel import LogPanel
from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import UserPromptRequest, UserTextRequest


class CenterContent(QWidget):
    """Right-side column: the interaction panel + the log panel.

    `results` is injected by the assembler (gui.py) after construction so that
    update_results() can call set_results() on the ResultsPanel that lives in
    the left stack.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pending: tuple[object, Callable[[str | None], None]] | None = None
        self._auto_switch = True

        self.interaction = InteractionPanel()
        self.interaction.response_given.connect(self._on_interaction_response)
        self.interaction.cancelled.connect(self.cancel_pending)

        # results is set by gui.py after construction
        self.results = None

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

    def set_auto_switch(self, auto: bool) -> None:
        """Pause mode: False blocks interaction while operator browses freely."""
        self._auto_switch = auto
        self.interaction.set_interaction_blocked(not auto)

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

    def show_idle(self) -> None:
        self.interaction.set_idle()

    def update_results(self, outcomes: tuple[StepOutcome, ...]) -> None:
        """Incremental update during a run; forwarded to the left-stack ResultsPanel."""
        if self.results is not None:
            self.results.set_results(outcomes)

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
