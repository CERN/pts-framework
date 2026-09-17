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
"""

from collections.abc import Callable

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.interaction_panel import InteractionPanel
from pypts.hmi.gui.log_panel import LogPanel
from pypts.messages.run_events import UserPathRequest, UserPromptRequest, UserTextRequest


class CenterContent(QWidget):
    """Right-side column: the interaction panel + the log panel."""

    def __init__(self) -> None:
        super().__init__()
        self._pending: tuple[object, Callable[[str | None], None]] | None = None

        self.interaction = InteractionPanel()
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
