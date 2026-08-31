# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The CenterView content: the operator's focus during a run.

A QStackedWidget with three pages - idle (the logo), a prompt (message, image,
one button per option) and a serial-number form. Page switching happens HERE,
never through the scaffold's set_content(), which deletes what it replaces
(gui.md section 6). The serial form is a page rather than the old modal
dialog: a modal spins a nested event loop, which is the shape gui.md
section 3 says not to reproduce - and a page is testable by driving widgets.

The one invariant: **every request is answered exactly once.** A new request
first declines the unanswered one; answering clears the pending pair *before*
invoking the callback; and cancel_pending() (called on RunFinished) declines
whatever is still open - so a blocked step is never stranded, whatever order
things happen in.
"""

import importlib.resources
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pypts.logger.log import log
from pypts.messages.run_events import SerialNumberRequest, UserPromptRequest

#: The logo never renders larger than this; smaller windows scale it down.
LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT = 800, 500


def load_logo() -> QPixmap:
    """The CERN logo from package data, or a gray block if it is missing."""
    try:
        logo_file = importlib.resources.files("pypts.hmi.gui").joinpath("images/CERN_Logo.png")
        pixmap = QPixmap()
        pixmap.loadFromData(logo_file.read_bytes())
        if not pixmap.isNull():
            return pixmap.scaled(
                LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio
            )
    except OSError as error:
        log.warning("CERN logo not found in package data: %s", error)
    fallback = QPixmap(LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT)
    fallback.fill(Qt.GlobalColor.lightGray)
    return fallback


class CenterContent(QWidget):
    """The three-page stack, and the exactly-once answer bookkeeping."""

    def __init__(self) -> None:
        super().__init__()
        #: (request_id, answer_callable) of the question on screen, or None.
        self._pending: tuple[object, Callable[[str | None], None]] | None = None
        self.option_buttons: list[QPushButton] = []

        self.stack = QStackedWidget()
        self.idle_page = self._build_idle_page()
        self.prompt_page = self._build_prompt_page()
        self.serial_page = self._build_serial_page()
        self.stack.addWidget(self.idle_page)
        self.stack.addWidget(self.prompt_page)
        self.stack.addWidget(self.serial_page)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.stack)

    # --- Page construction -----------------------------------------------------

    def _build_idle_page(self) -> QWidget:
        page = QWidget()
        logo = QLabel()
        logo.setPixmap(load_logo())
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(page)
        layout.addWidget(logo)
        return page

    def _build_prompt_page(self) -> QWidget:
        page = QWidget()
        self.prompt_image = QLabel()
        self.prompt_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_message = QLabel()
        self.prompt_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_message.setWordWrap(True)
        self.button_row = QHBoxLayout()
        layout = QVBoxLayout(page)
        layout.addStretch()
        layout.addWidget(self.prompt_image)
        layout.addWidget(self.prompt_message)
        layout.addLayout(self.button_row)
        layout.addStretch()
        return page

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
        """Put the question on screen; the clicked option goes to `answer`."""
        self.cancel_pending()  # a new question declines the unanswered one
        self._pending = (request.request_id, answer)

        self.prompt_message.setText(request.message)
        self._show_prompt_image(request.image_path)
        self._clear_option_buttons()
        for option in request.options:
            button = QPushButton(option)
            button.clicked.connect(lambda checked=False, value=option: self._answer(value))
            self.button_row.addWidget(button)
            self.option_buttons.append(button)
        self.stack.setCurrentWidget(self.prompt_page)

    def show_serial_request(
        self, request: SerialNumberRequest, answer: Callable[[str | None], None]
    ) -> None:
        self.cancel_pending()
        self._pending = (request.request_id, answer)
        self.serial_input.clear()
        self.stack.setCurrentWidget(self.serial_page)
        self.serial_input.setFocus()

    def cancel_pending(self) -> None:
        """Decline whatever question is still open. Idempotent."""
        if self._pending is not None:
            self._answer(None)

    def _serial_accepted(self) -> None:
        self._answer(self.serial_input.text().strip())

    def _answer(self, value: str | None) -> None:
        """The exactly-once gate: clear first, then call, then back to idle."""
        if self._pending is None:
            return
        _request_id, answer = self._pending
        self._pending = None
        answer(value)
        self._clear_option_buttons()
        self.stack.setCurrentWidget(self.idle_page)

    # --- Helpers ---------------------------------------------------------------

    def _show_prompt_image(self, image_path: str | None) -> None:
        if image_path and Path(image_path).is_file():
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                self.prompt_image.setPixmap(
                    pixmap.scaled(
                        LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio
                    )
                )
                self.prompt_image.show()
                return
            log.warning("Cannot render the prompt image %s", image_path)
        elif image_path:
            log.warning("Prompt image not found: %s", image_path)
        self.prompt_image.hide()

    def _clear_option_buttons(self) -> None:
        for button in self.option_buttons:
            self.button_row.removeWidget(button)
            button.deleteLater()
        self.option_buttons.clear()
