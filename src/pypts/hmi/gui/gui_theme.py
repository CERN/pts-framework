# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import contextlib
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pypts.config_handler import ConfigError, ConfigHandler
from pypts.config_handler.configuration_schema import SCHEMA


def configured_theme() -> str:
    """
    `[gui] theme` from config.ini: "light", "dark" or "system".

    Shared by pypts' window and the Recipe Creator, so one setting themes both.
    With no configuration to read - the Recipe Creator started before pypts
    ever ran, or a test - it is the template's value, light.
    """
    try:
        return ConfigHandler().get_parameter("gui.theme")
    except ConfigError:
        return SCHEMA["gui"]["theme"].default


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
