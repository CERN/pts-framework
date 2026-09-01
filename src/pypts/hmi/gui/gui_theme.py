# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import contextlib
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _style_hints_for(app=None):
    app = app or QApplication.instance()
    if app is None or not hasattr(app, "styleHints"):
        return None
    return app.styleHints()


def detect_system_dark_mode(app=None) -> bool:
    style_hints = _style_hints_for(app)
    if style_hints is None or not hasattr(style_hints, "colorScheme"):
        return False
    return style_hints.colorScheme() == Qt.ColorScheme.Dark


def install_system_theme_sync(app, callback: Callable[[bool], None]) -> Callable[[], None]:
    """Install system-theme synchronisation; return a disconnect callable."""
    style_hints = _style_hints_for(app)
    if style_hints is None or not hasattr(style_hints, "colorSchemeChanged"):
        return lambda: None

    def on_color_scheme_changed(scheme):
        callback(scheme == Qt.ColorScheme.Dark)

    style_hints.colorSchemeChanged.connect(on_color_scheme_changed)
    disconnected = False

    def disconnect() -> None:
        nonlocal disconnected
        if disconnected:
            return
        disconnected = True
        with contextlib.suppress(RuntimeError, TypeError):
            style_hints.colorSchemeChanged.disconnect(on_color_scheme_changed)

    return disconnect
