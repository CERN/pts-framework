# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from pypts.gui import MainWindow
from pypts.YamVIEW.recipe_creator import RecipeEditorMainMenu
from pypts.gui_components.styles import CERN_BLUE
from pypts.gui_theme import detect_system_dark_mode, install_system_theme_sync


class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _FakeStyleHints:
    def __init__(self, scheme):
        self._scheme = scheme
        self.colorSchemeChanged = _FakeSignal()

    def colorScheme(self):
        return self._scheme


class _FakeApp:
    def __init__(self, scheme):
        self._style_hints = _FakeStyleHints(scheme)

    def styleHints(self):
        return self._style_hints


def test_detect_system_dark_mode_returns_true_for_dark_scheme():
    app = _FakeApp(Qt.ColorScheme.Dark)

    assert detect_system_dark_mode(app) is True


def test_detect_system_dark_mode_returns_false_for_light_scheme():
    app = _FakeApp(Qt.ColorScheme.Light)

    assert detect_system_dark_mode(app) is False


def test_install_system_theme_sync_invokes_callback_for_changes():
    app = _FakeApp(Qt.ColorScheme.Light)
    callback = Mock()

    install_system_theme_sync(app, callback)

    assert len(app.styleHints().colorSchemeChanged.callbacks) == 1

    app.styleHints().colorSchemeChanged.callbacks[0](Qt.ColorScheme.Dark)
    callback.assert_called_once_with(True)


def test_main_window_uses_detected_system_theme(qtbot):
    with patch("pypts.gui.detect_system_dark_mode", return_value=True):
        window = MainWindow()

    qtbot.addWidget(window)
    try:
        assert window._dark_mode is True
    finally:
        window.close()


def test_recipe_editor_uses_detected_system_theme(qtbot):
    with patch("pypts.YamVIEW.recipe_creator.detect_system_dark_mode", return_value=True):
        window = RecipeEditorMainMenu()

    qtbot.addWidget(window)
    try:
        assert window.dark_mode is True
        assert window.toggle_dark_mode_action.isChecked() is True
    finally:
        window.close()


def test_recipe_editor_uses_shared_light_palette(qtbot):
    with patch("pypts.YamVIEW.recipe_creator.detect_system_dark_mode", return_value=False):
        window = RecipeEditorMainMenu()

    qtbot.addWidget(window)
    try:
        assert CERN_BLUE in window.styleSheet()
        assert window.sequencer._dark is False
        assert window.yaml_viewer.dark_mode is False
    finally:
        window.close()


def test_recipe_editor_toggle_dark_propagates_to_child_widgets(qtbot):
    window = RecipeEditorMainMenu()

    qtbot.addWidget(window)
    try:
        window.toggle_dark_mode(True)

        assert window.dark_mode is True
        assert window.sequencer._dark is True
        assert window.yaml_viewer.dark_mode is True
    finally:
        window.close()


def test_recipe_editor_sequencer_rows_reserve_enough_height_for_text(qtbot):
    window = RecipeEditorMainMenu()
    qtbot.addWidget(window)

    try:
        window.sequencer.set_yaml_data(
            [
                {
                    "step_name": "Sequence: Long Sequence Name",
                    "steptype": "sequence_folder",
                    "children": [
                        {
                            "step_name": "Setup Steps",
                            "steptype": "setup_folder",
                            "children": [
                                {
                                    "step_name": "A step with a readable title",
                                    "steptype": "userinteractionstep",
                                }
                            ],
                        }
                    ],
                }
            ]
        )
        window.sequencer.expanded = True
        window.sequencer.refresh()

        for index in range(window.sequencer.list_widget.count()):
            item = window.sequencer.list_widget.item(index)
            widget = window.sequencer.list_widget.itemWidget(item)
            if widget is None:
                continue
            assert item.sizeHint().height() >= widget.sizeHint().height()
            assert item.sizeHint().height() >= 30
    finally:
        window.close()
