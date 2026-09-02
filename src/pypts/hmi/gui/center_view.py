# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The right-side content: InteractionPanel (idle / prompt / serial) + LogPanel.

The left side (idle placeholder / step table / results) is owned by
PtsMainWindow and managed via _switch_screen(). This widget manages only the
right column and the exact-once answer contract:

  - A new request first declines any unanswered one.
  - Answering clears the pending pair *before* invoking the callback.
  - cancel_pending() declines whatever is still open. Three things call it:
    RunFinished, a superseding request, and the operator's own Cancel button.
    All three answer None, and the step that asked turns that into an ERROR.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.interaction_panel import InteractionPanel
from pypts.hmi.gui.log_panel import LogPanel
from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import SerialNumberRequest, UserPromptRequest

_PAGE_INTERACTION = 0
_PAGE_SERIAL = 1


class CenterContent(QWidget):
    """Right-side column: interaction stack (idle/prompt/serial) + log panel.

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

        self.serial_page = self._build_serial_page()

        # results is set by gui.py after construction
        self.results = None

        self.stack = QStackedWidget()
        self.stack.addWidget(self.interaction)   # index 0
        self.stack.addWidget(self.serial_page)   # index 1

        log_label = QLabel("LOG OUTPUT")
        log_label.setObjectName("sectionLabel")
        self.log_panel = LogPanel()

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.stack, stretch=1)
        column.addWidget(log_label)
        column.addWidget(self.log_panel)

    # --- Compatibility properties for tests ------------------------------------

    @property
    def idle_page(self):
        return self.interaction

    @property
    def prompt_page(self):
        return self.interaction

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

    # --- Serial page -----------------------------------------------------------

    def _build_serial_page(self) -> QWidget:
        page = QWidget()
        self.serial_message = QLabel("Serial number of the unit under test:")
        self.serial_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.serial_input = QLineEdit()
        self.serial_input.setMaximumWidth(300)
        self.serial_ok_button = QPushButton("OK")
        self.serial_ok_button.clicked.connect(self._serial_accepted)
        self.serial_input.returnPressed.connect(self._serial_accepted)
        self.serial_cancel_button = QPushButton("Cancel")
        self.serial_cancel_button.clicked.connect(lambda: self._answer(None))
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.serial_ok_button)
        buttons.addWidget(self.serial_cancel_button)
        buttons.addStretch()
        layout = QVBoxLayout(page)
        layout.addStretch()
        layout.addWidget(self.serial_message)
        layout.addWidget(self.serial_input, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(buttons)
        layout.addStretch()
        return page

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
        self.stack.setCurrentIndex(_PAGE_INTERACTION)

    def show_serial_request(
        self, request: SerialNumberRequest, answer: Callable[[str | None], None]
    ) -> None:
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.serial_input.clear()
        self.stack.setCurrentIndex(_PAGE_SERIAL)
        self.serial_input.setFocus()

    def show_idle(self) -> None:
        self.interaction.set_idle()
        self.stack.setCurrentIndex(_PAGE_INTERACTION)

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

    def _serial_accepted(self) -> None:
        self._answer(self.serial_input.text().strip())

    def _answer(self, value: str | None) -> None:
        """The exactly-once gate: clear first, then call, then back to idle."""
        if self._pending is None:
            return
        _request_id, answer = self._pending
        self._pending = None
        answer(value)
        self.interaction.set_idle()
        self.stack.setCurrentIndex(_PAGE_INTERACTION)
