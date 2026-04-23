# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from pypts.gui_components.resources import load_cern_logo_pixmap, make_placeholder_pixmap


class InteractionPanel(QWidget):
    response_given = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._logo_pixmap = load_cern_logo_pixmap()

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
        self.set_idle()

    def set_dark(self, dark: bool):
        self._dark = dark
        frame_bg = "#1e1e1e" if dark else "#F0F4FA"
        border = "#3a3a3a" if dark else "#e2e8f0"
        text_color = "#f0f0f0" if dark else "#1a1a2e"
        self._frame.setStyleSheet(
            "QFrame#interactionFrame {"
            f"background-color:{frame_bg}; border:1px solid {border}; border-radius:8px;"
            "}"
        )
        self.message_label.setStyleSheet(f"font-size:13px; font-weight:500; color:{text_color}; padding:4px 0;")
        self._refresh_idle_visual()

    def set_idle(self):
        self.clear_buttons()
        self.message_label.clear()
        self.message_label.setVisible(False)
        self._button_row.setVisible(False)
        self._refresh_idle_visual()

    def set_prompt(self, message: str, buttons: list[dict], image_path: str | None = None):
        self._set_image_from_path(image_path)
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        self.clear_buttons()
        for index, button_def in enumerate(buttons):
            label = button_def.get("label", "")
            value = button_def.get("value", label)
            self.add_button(label, value, primary=index == 0)
        self._button_row.setVisible(bool(buttons))

    def set_image(self, image_path: str | None):
        self._set_image_from_path(image_path)

    def add_button(self, label: str, value: str, primary: bool = False):
        button = QPushButton(label)
        if primary:
            button.setObjectName("primaryBtn")
        elif label.lower() in {"abort", "stop", "cancel"}:
            button.setObjectName("stopBtn")
        button.clicked.connect(lambda _checked=False, response=value: self.response_given.emit(response))
        self._button_layout.insertWidget(self._button_layout.count() - 1, button)
        self._buttons.append(button)

    def clear_buttons(self):
        for button in self._buttons:
            self._button_layout.removeWidget(button)
            button.deleteLater()
        self._buttons.clear()

    def current_pixmap(self) -> QPixmap | None:
        return self.image_label.pixmap()

    def _set_image_from_path(self, image_path: str | None):
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
