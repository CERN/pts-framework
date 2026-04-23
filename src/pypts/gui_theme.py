# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pypts.gui_components.styles import CERN_BLUE, MTA_BLUE, get_stylesheet


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


def install_system_theme_sync(app, callback: Callable[[bool], None]) -> None:
    style_hints = _style_hints_for(app)
    if style_hints is None or not hasattr(style_hints, "colorSchemeChanged"):
        return

    style_hints.colorSchemeChanged.connect(lambda scheme: callback(scheme == Qt.ColorScheme.Dark))


def get_theme_colors(dark: bool) -> dict[str, str]:
    if dark:
        return {
            "panel_bg": "#232323",
            "surface_bg": "#2b2b2b",
            "surface_alt": "#3c3f41",
            "border": "#3a3a3a",
            "muted_text": "#666666",
            "body_text": "#f0f0f0",
            "header_text": "#7AABDF",
            "selection": "#1a2840",
            "line_number_bg": "#232323",
            "line_number_text": "#7f8a99",
            "current_line": "#1f2937",
            "log_bg": "#1e1e1e",
            "success_text": "#6abf69",
            "warning_text": "#FFCC80",
            "danger_text": "#F28B82",
        }
    return {
        "panel_bg": "#F8FAFC",
        "surface_bg": "#f5f7fa",
        "surface_alt": "#ffffff",
        "border": "#e2e8f0",
        "muted_text": "#94a3b8",
        "body_text": "#1a1a2e",
        "header_text": MTA_BLUE,
        "selection": "#EEF5FF",
        "line_number_bg": "#F0F4FA",
        "line_number_text": "#718096",
        "current_line": "#E6F1FF",
        "log_bg": "#ffffff",
        "success_text": "#1B5E20",
        "warning_text": "#C49000",
        "danger_text": "#B42318",
    }


def get_yamview_stylesheet(dark: bool = False) -> str:
    colors = get_theme_colors(dark)
    return (
        get_stylesheet(dark)
        + f"""
QWidget#yamRoot {{
    background-color: {colors["surface_bg"]};
}}
QTextEdit#recipeStatus {{
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    background-color: {colors["surface_alt"]};
    color: {colors["header_text"]};
    font-size: 12px;
    font-style: normal;
    padding: 6px 10px;
}}
QTextEdit#yamLogConsole, QPlainTextEdit#yamlEditor {{
    background-color: {colors["log_bg"]};
    color: {colors["body_text"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
}}
QListWidget#sequencerList {{
    background-color: {colors["surface_alt"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 6px;
}}
QListWidget#sequencerList::item {{
    border: none;
    padding: 2px;
}}
QListWidget#sequencerList::item:selected {{
    background-color: {colors["selection"]};
}}
QFrame#sequencerCard {{
    background-color: {colors["panel_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
}}
QLabel#sequencerStepTitle {{
    color: {colors["body_text"]};
    font-size: 12px;
    font-weight: 600;
    padding: 4px 8px;
}}
QLabel#sequencerHeader {{
    color: {colors["header_text"]};
    font-size: 11px;
    font-weight: 600;
    padding: 6px 8px;
}}
QToolBar#yamSequencerToolbar {{
    background-color: {colors["panel_bg"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 4px 6px;
    spacing: 2px;
}}
QToolBar#yamSequencerToolbar QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 8px;
    color: {colors["body_text"]};
}}
QToolBar#yamSequencerToolbar QToolButton:hover {{
    background-color: {colors["selection"]};
    color: {CERN_BLUE};
}}
"""
    )
