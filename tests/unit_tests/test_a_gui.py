# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import os
from queue import SimpleQueue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import Mock, patch

from pypts import gui, recipe
from pypts.startup import create_and_start_gui
from pypts.gui_components import interaction_panel
from pypts.gui_components.results_panel import StepResultModel


@pytest.fixture
def main_window(qapp, qtbot):
    window = gui.MainWindow()
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


@pytest.fixture
def sample_sequence():
    step1 = recipe.Step(step_name="Test Step 1", description="First step")
    step2 = recipe.Step(step_name="Test Step 2", description="Second step")
    sequence = recipe.Sequence(
        sequence_data={
            "sequence_name": "Test Sequence",
            "locals": {},
            "parameters": {},
            "outputs": {},
            "setup_steps": [],
            "steps": [],
            "teardown_steps": [],
        }
    )
    sequence.steps = [step1, step2]
    return sequence


@pytest.fixture
def sample_results():
    step1 = recipe.Step(step_name="Parent Step")
    step2 = recipe.Step(step_name="Child Step")

    parent_result = recipe.StepResult(step1)
    parent_result.set_result(recipe.ResultType.PASS, outputs={"value": 1})

    child_result = recipe.StepResult(step2, parent=parent_result.uuid)
    child_result.set_result(recipe.ResultType.FAIL, outputs={"value": 2})
    parent_result.subresults = [child_result]
    return [parent_result]


def test_main_window_title_and_initial_actions(main_window):
    assert main_window.windowTitle() == "pypts"
    assert main_window.action_open_recipe.isEnabled()
    assert not main_window.action_start_recipe_execution.isEnabled()
    assert not main_window.action_abort_recipe_execution.isEnabled()


def test_update_sequence_populates_three_columns(main_window, sample_sequence):
    main_window.update_sequence({"sequence": sample_sequence})

    assert main_window.step_list.columnCount() == 3
    assert main_window.step_list.rowCount() == 2
    assert main_window.step_list.item(0, 0).text() == "Test Step 1"
    assert main_window.step_list.item(0, 1).text() == "First step"
    assert main_window.step_list.item(0, 2).text() == "PENDING"
    assert main_window.step_list.item(0, 0).data(gui.Qt.ItemDataRole.UserRole) == str(sample_sequence.steps[0].id)


def test_update_running_step_marks_row_running(main_window, sample_sequence):
    main_window.update_sequence({"sequence": sample_sequence})

    main_window.update_running_step({"step_uuid": sample_sequence.steps[1].id})

    assert main_window.step_list.item(1, 2).text() == "Running..."
    assert main_window.step_list.item(1, 2).font().italic()


def test_update_step_result_updates_row_by_uuid(main_window, sample_sequence):
    main_window.update_sequence({"sequence": sample_sequence})

    main_window.update_step_result(
        {
            "step_uuid": sample_sequence.steps[0].id,
            "status_text": "PASS",
            "status_color": "#C8E6C9",
            "text_color": "#1B4F24",
        }
    )

    assert main_window.step_list.item(0, 2).text() == "PASS"
    assert main_window.step_list.item(0, 2).background().color().name().lower() == "#c8e6c9"


def test_show_message_uses_placeholder_when_image_missing(main_window):
    response_q = SimpleQueue()
    main_window.show_message(
        {
            "response_q": response_q,
            "message": "Connect the DUT and continue.",
            "image_path": "C:/missing/image.png",
            "options": [{"yes": "Continue"}],
        }
    )

    assert main_window.message_box.text() == "Connect the DUT and continue."
    assert main_window._screen_idx == gui.SCREEN_PROMPT
    pixmap = main_window._interaction_panel.current_pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()


def test_show_results_binds_model_and_switches_screen(main_window, sample_results):
    main_window.show_results({"results": sample_results})

    assert main_window._screen_idx == gui.SCREEN_RESULTS
    assert isinstance(main_window.result_list.model(), StepResultModel)


def test_logo_fallback_still_renders_placeholder(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(interaction_panel, "load_cern_logo_pixmap", lambda: None)

    panel = interaction_panel.InteractionPanel()
    qtbot.addWidget(panel)
    panel.show()

    pixmap = panel.current_pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()


def test_create_and_start_gui_shows_window(qapp):
    api = Mock()
    api.input_queue = SimpleQueue()

    with patch("pypts.startup.QApplication", return_value=qapp), patch("pypts.startup.time.sleep"):
        window, app = create_and_start_gui(api)

    try:
        assert app is qapp
        assert window.isVisible()
    finally:
        window.close()
