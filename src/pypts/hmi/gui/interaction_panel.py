# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.palette import get_palette
from pypts.hmi.gui.resources import load_cern_logo_pixmap, make_placeholder_pixmap

#: The button every prompt carries beyond the recipe's own options, so the
#: operator is never trapped in front of a question they cannot answer. It is
#: not one of the options: it emits `cancelled`, not `response_given`, so a
#: recipe that happens to offer its own "Cancel" option keeps it distinct.
CANCEL_LABEL = "Cancel"


class InteractionPanel(QWidget):
    response_given = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._logo_pixmap = load_cern_logo_pixmap(get_palette(False).logo_tint)
        self._selected_button_index = -1
        self._current_image_path: str | None = None
        self._mode = "idle"
        self._interaction_blocked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._frame = QFrame()
        self._frame.setObjectName("interactionFrame")
        self._frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._frame)

        self._inner = QVBoxLayout(self._frame)
        self._inner.setContentsMargins(16, 16, 16, 16)
        self._inner.setSpacing(12)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self._inner.addWidget(self.image_label, stretch=1)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        self._inner.addWidget(self.message_label)

        self._button_row = QWidget()
        self._button_layout = QHBoxLayout(self._button_row)
        self._button_layout.setContentsMargins(0, 0, 0, 0)
        self._button_layout.setSpacing(8)
        self._button_layout.addStretch()
        self._button_row.setVisible(False)
        self._inner.addWidget(self._button_row)

        self._buttons: list[QPushButton] = []

        # The text row is the free-text half of the panel, used by set_text_prompt()
        # instead of the button row. It is built once and hidden, the way the button
        # row is, so a prompt only ever toggles visibility.
        self._text_row = QWidget()
        text_layout = QHBoxLayout(self._text_row)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        self.text_input = QLineEdit()
        self.text_input.setMaximumWidth(360)
        self.text_input.textChanged.connect(self._refresh_text_ok_enabled)
        self.text_input.returnPressed.connect(self._text_accepted)
        self.text_ok_button = QPushButton("OK")
        self.text_ok_button.setObjectName("primaryBtn")
        self.text_ok_button.clicked.connect(self._text_accepted)
        self.text_cancel_button = QPushButton(CANCEL_LABEL)
        self.text_cancel_button.setObjectName("stopBtn")
        self.text_cancel_button.clicked.connect(self.cancelled.emit)
        text_layout.addStretch()
        text_layout.addWidget(self.text_input)
        text_layout.addWidget(self.text_ok_button)
        text_layout.addWidget(self.text_cancel_button)
        text_layout.addStretch()
        self._text_row.setVisible(False)
        self._inner.addWidget(self._text_row)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.set_idle()

    def set_dark(self, dark: bool):
        self._dark = dark
        palette = get_palette(dark)
        # The logo is artwork, not a stylesheet colour, so it is reloaded rather
        # than restyled - dark tints it, light draws the file as it is.
        self._logo_pixmap = load_cern_logo_pixmap(palette.logo_tint)
        if self._current_image_path is None:
            self._refresh_idle_visual()
        frame_bg = palette.panel_background
        border = palette.border
        text_color = palette.text
        self._frame.setStyleSheet(
            "QFrame#interactionFrame {"
            f"background-color:{frame_bg}; border:1px solid {border}; border-radius:8px;"
            "}"
        )
        self.message_label.setStyleSheet(
            f"font-size:13px; font-weight:500; color:{text_color}; padding:4px 0;"
        )
        self._refresh_visual()

    def set_idle(self):
        self._interaction_blocked = False
        self.clear_buttons()
        self.message_label.clear()
        self.message_label.setVisible(False)
        self._button_row.setVisible(False)
        self._text_row.setVisible(False)
        self.text_input.clear()
        self._mode = "idle"
        self._refresh_idle_visual()

    def is_idle(self) -> bool:
        """No question on screen. Logical state, not Qt visibility: a child of
        a window that has not been shown reports isVisible() False whatever was
        asked of it."""
        return self._mode == "idle"

    def set_prompt(self, message: str, buttons: list[dict], image_path: str | None = None):
        self._text_row.setVisible(False)
        self._set_image_from_path(image_path)
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        self.clear_buttons()
        for index, button_def in enumerate(buttons):
            label = button_def.get("label", "")
            value = button_def.get("value", label)
            self.add_button(label, value, primary=index == 0)
        # Always last, and never primary, so Enter on a freshly shown prompt
        # answers rather than declines. It joins _buttons like any other, so
        # the arrow keys reach it.
        self.add_button(CANCEL_LABEL, CANCEL_LABEL, on_click=self.cancelled.emit)
        self._button_row.setVisible(True)
        self._mode = "prompt"
        if self._buttons:
            self._set_selected_button(0)
            self._buttons[0].setFocus(Qt.FocusReason.OtherFocusReason)
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_text_prompt(self, message: str, image_path: str | None = None):
        """
        The free-text prompt: same picture and message, a line edit instead of
        buttons.

        It answers through the same two signals a button prompt does -
        `response_given` with the typed text, `cancelled` from Cancel - so
        CenterContent's exactly-once gate, RunFinished and a superseding
        request all reach it with no special case of their own.

        OK stays disabled while the field is empty. That is the whole of the
        "no empty answers" rule: the operator can type something or cancel,
        and no recipe has to spell an `allow_empty` out.
        """
        self.clear_buttons()
        self._button_row.setVisible(False)
        self._set_image_from_path(image_path)
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        self.text_input.clear()
        self._refresh_text_ok_enabled()
        self._text_row.setVisible(True)
        self._mode = "text"
        self.text_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _text_accepted(self):
        text = self.text_input.text().strip()
        if text:
            self.response_given.emit(text)

    def _refresh_text_ok_enabled(self):
        self.text_ok_button.setEnabled(bool(self.text_input.text().strip()))

    def set_image(self, image_path: str | None):
        self._set_image_from_path(image_path)

    def set_interaction_blocked(self, blocked: bool):
        self._interaction_blocked = blocked
        self._button_row.setAttribute(Qt.WA_TransparentForMouseEvents, blocked)
        self._text_row.setAttribute(Qt.WA_TransparentForMouseEvents, blocked)

    def add_button(self, label: str, value: str, primary: bool = False, on_click=None):
        """One prompt button. `on_click` replaces the default answer-with-value
        wiring - it is what makes Cancel decline instead of answering."""
        button = QPushButton(label)
        button.setProperty("promptSelected", False)
        if primary:
            button.setObjectName("primaryBtn")
        elif label.lower() in {"abort", "stop", "cancel"}:
            button.setObjectName("stopBtn")
        if on_click is None:
            button.clicked.connect(
                lambda _checked=False, response=value: self.response_given.emit(response)
            )
        else:
            button.clicked.connect(lambda _checked=False: on_click())
        button.installEventFilter(self)
        self._button_layout.insertWidget(self._button_layout.count() - 1, button)
        self._buttons.append(button)

    def clear_buttons(self):
        for button in self._buttons:
            self._button_layout.removeWidget(button)
            button.deleteLater()
        self._buttons.clear()
        self._selected_button_index = -1

    def current_pixmap(self) -> QPixmap | None:
        return self.image_label.pixmap()

    def _set_image_from_path(self, image_path: str | None):
        self._current_image_path = image_path
        self._refresh_visual()

    def _refresh_visual(self):
        image_path = self._current_image_path
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                self.image_label.setPixmap(
                    pixmap.scaled(640, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self.image_label.setText("")
                return
        self._refresh_idle_visual()

    def _refresh_idle_visual(self):
        pixmap = self._logo_pixmap
        if pixmap is None or pixmap.isNull():
            pixmap = make_placeholder_pixmap(420, 220)
        self.image_label.setPixmap(
            pixmap.scaled(420, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.image_label.setText("")

    def eventFilter(self, watched, event):  # noqa: N802 - Qt virtual
        if watched in self._buttons and event.type() == QEvent.Type.FocusIn:
            index = self._buttons.index(watched)
            self._set_selected_button(index)
        elif watched in self._buttons and event.type() == QEvent.Type.KeyPress:
            if self._handle_navigation_key(event.key()):
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt virtual
        if self._handle_navigation_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_navigation_key(self, key: int) -> bool:
        if not self._buttons or self._interaction_blocked:
            return False

        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._move_selection(1)
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._move_selection(-1)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            selected = self.selected_button()
            if selected is not None:
                selected.click()
                return True
        return False

    def _move_selection(self, offset: int):
        if not self._buttons:
            return
        if self._selected_button_index < 0:
            next_index = 0
        else:
            next_index = (self._selected_button_index + offset) % len(self._buttons)
        self._set_selected_button(next_index)
        self._buttons[next_index].setFocus(Qt.FocusReason.OtherFocusReason)

    def _set_selected_button(self, index: int):
        if index < 0 or index >= len(self._buttons):
            return
        self._selected_button_index = index
        for button_index, button in enumerate(self._buttons):
            is_selected = button_index == index
            if button.property("promptSelected") != is_selected:
                button.setProperty("promptSelected", is_selected)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def selected_button(self) -> QPushButton | None:
        if 0 <= self._selected_button_index < len(self._buttons):
            return self._buttons[self._selected_button_index]
        return None
