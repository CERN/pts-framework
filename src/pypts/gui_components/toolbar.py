# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import xml.etree.ElementTree as _ET

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QSizePolicy, QToolBar, QWidget


def _svg_icon(svg_str: str, size: int = 16) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_str.encode()))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


_FOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round">'
    '<path d="M2 12V5a1 1 0 011-1h3.5l1.5 1.5H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1z"/>'
    "</svg>"
)
_PLAY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="{color}"><polygon points="4,2 14,8 4,14"/></svg>'
)
_STOP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="{color}"><rect x="3" y="3" width="10" height="10" rx="1.5"/></svg>'
)


class PtsToolBar(QToolBar):
    """Top toolbar with Open / Start / Stop actions and right-aligned branding."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.setIconSize(QSize(16, 16))
        self.setObjectName("PtsToolBar")

        self._dark = False
        self._can_start = False
        self._can_stop = False

        self.action_open = QAction("Open", self)
        self.action_start = QAction("Start", self)
        self.action_stop = QAction("Stop", self)

        self.addAction(self.action_open)
        self.addAction(self.action_start)
        self.addAction(self.action_stop)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.addWidget(spacer)

        self._brand = QLabel("pypts")
        self._brand.setStyleSheet("font-size:11px; color:#94a3b8; padding-right:6px;")
        self.addWidget(self._brand)

        self._refresh_states()

    def set_dark(self, dark: bool):
        self._dark = dark
        self._brand.setStyleSheet(
            f"font-size:11px; color:{'#666666' if dark else '#94a3b8'}; padding-right:6px;"
        )
        self._refresh_states()

    def set_can_start(self, value: bool):
        self._can_start = value
        self._refresh_states()

    def set_can_stop(self, value: bool):
        self._can_stop = value
        self._refresh_states()

    def _refresh_states(self):
        self.action_open.setIcon(
            _svg_icon(_FOLDER_SVG.format(color="#7AABDF" if self._dark else "#424242"))
        )
        self.action_start.setEnabled(self._can_start)
        self.action_start.setIcon(
            _svg_icon(_PLAY_SVG.format(color="#1B5E20" if self._can_start else "#BDBDBD"))
        )
        self.action_stop.setEnabled(self._can_stop)
        self.action_stop.setIcon(
            _svg_icon(_STOP_SVG.format(color="#CC0000" if self._can_stop else "#BDBDBD"))
        )
