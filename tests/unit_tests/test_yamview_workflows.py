# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""End-to-end working-state tests for the YamVIEW editor shell."""

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from pypts.recipe_language import Sequence
from pypts.recipe_parser import parse_recipe_text, recipe_to_yaml
from pypts.YamVIEW.customGUIModules import RecipeCreatorApp
from pypts.YamVIEW.recipe_creator import RecipeEditorMainMenu
from pypts.YamVIEW.recipe_sequencer_setup import _sequence_node

RECIPE_PATH = Path(__file__).parents[2] / "src" / "pypts" / "recipes" / "simple_recipe.yml"


def _window_with_recipe(qtbot):
    window = RecipeEditorMainMenu()
    qtbot.addWidget(window)
    assert window.load_yaml_recipe(RECIPE_PATH)
    return window


def test_open_valid_recipe_populates_sequencer_and_enables_save(qtbot):
    window = _window_with_recipe(qtbot)

    assert window.is_recipe_valid
    assert window.sequencer.isEnabled()
    assert window.save_action.isEnabled()
    assert window.save_as_action.isEnabled()
    assert window.sequencer.steps[0]["steptype"] == "preamble"
    assert window.sequencer.steps[1]["steptype"] == "sequence_folder"
    visible_types = {
        window.sequencer.list_widget.item(index).data(Qt.UserRole).get("steptype")
        for index in range(window.sequencer.list_widget.count())
    }
    assert "preamble" not in visible_types


def test_structured_edit_preserves_exact_discriminator_and_stage(qtbot):
    window = _window_with_recipe(qtbot)
    sequence = window.sequencer.steps[1]
    main = sequence["children"][1]
    step = main["children"][0]
    step["_node"]["description"] = "Changed through the structured editor."

    window.on_sequencer_updated(window.sequencer.steps)

    reparsed = parse_recipe_text(window.temporary_recipe_contents)
    assert reparsed.is_valid
    authored = reparsed.require_recipe().sequences[0].steps[0]
    assert authored.steptype == "UserInteractionStep"
    assert authored.description == "Changed through the structured editor."
    assert step["_parent"] == "main_folder"


def test_add_and_edit_step_actions_keep_selected_stage_identity(qtbot, monkeypatch):
    window = _window_with_recipe(qtbot)
    sequence = window.sequencer.steps[1]
    teardown = sequence["children"][2]
    window.sequencer.expanded = True
    window.sequencer.refresh()
    for index in range(window.sequencer.list_widget.count()):
        item = window.sequencer.list_widget.item(index)
        if item.data(Qt.UserRole).get("_id") == teardown["_id"]:
            window.sequencer.list_widget.setCurrentItem(item)
            break

    class FakeStepDialog:
        def __init__(self, parent=None):
            self.result_step = {
                "steptype": "UserInteractionStep",
                "step_name": "Added",
                "_node": {
                    "steptype": "UserInteractionStep",
                    "step_name": "Added",
                    "description": "Added through the dialog action.",
                    "input_mapping": {},
                    "output_mapping": {},
                },
                "_id": "added-step",
            }

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(
        "pypts.YamVIEW.recipe_sequencer_setup.Step_setup", FakeStepDialog
    )
    window.sequencer.on_add_step()
    added = teardown["children"][-1]
    assert added["_parent"] == "teardown_folder"
    assert added["_sequence_id"] == sequence["_sequence_id"]

    replacement = {
        **added,
        "step_name": "Edited",
        "_node": {**added["_node"], "step_name": "Edited"},
    }
    window.sequencer.current_setup_window = SimpleNamespace(result_step=replacement)
    window.sequencer._finish_edit(QDialog.Accepted, added)

    assert teardown["children"][-1]["step_name"] == "Edited"
    assert teardown["children"][-1]["_parent"] == "teardown_folder"


def test_step_move_and_delete_use_stable_sequence_and_folder_identity(qtbot):
    window = _window_with_recipe(qtbot)
    sequence = window.sequencer.steps[1]
    main = sequence["children"][1]
    teardown = sequence["children"][2]
    step = main["children"][0]

    assert window.sequencer.move_step(
        step, sequence["_sequence_id"], "teardown_folder", 0
    )
    assert step in teardown["children"]
    assert step not in main["children"]
    assert step["_parent"] == "teardown_folder"

    assert window.sequencer.delete_node(step, confirm=False)
    assert step not in teardown["children"]


def test_new_sequence_is_kept_in_document_order(qtbot):
    window = _window_with_recipe(qtbot)
    sequence = Sequence(
        sequence_name="Other",
        description="Second sequence.",
        parameters={},
        outputs={},
        locals={},
        setup_steps=[],
        steps=[],
        teardown_steps=[],
    )
    document = sequence.model_dump(mode="python", by_alias=True, exclude_none=True)
    window.sequencer.steps.append(_sequence_node(document, "sequence:other"))

    window.on_sequencer_updated(window.sequencer.steps)

    parsed = parse_recipe_text(window.temporary_recipe_contents)
    assert [item.sequence_name for item in parsed.require_recipe().sequences] == [
        "Main",
        "Other",
    ]


def test_structurally_invalid_sequence_deletion_is_rolled_back(qtbot):
    window = _window_with_recipe(qtbot)
    original_text = window.temporary_recipe_contents
    only_sequence = window.sequencer.steps[1]

    assert not window.sequencer.delete_node(only_sequence, confirm=False)

    assert window.temporary_recipe_contents == original_text
    assert window.is_recipe_valid
    assert len(window.sequencer.steps) == 2


def test_semantically_invalid_gui_edit_is_retained_and_blocks_save(qtbot):
    window = _window_with_recipe(qtbot)
    valid_text = window.last_valid_recipe
    window.sequencer.steps[0]["_node"]["main_sequence"] = "Missing"

    window.on_sequencer_updated(window.sequencer.steps)

    assert "main_sequence: Missing" in window.temporary_recipe_contents
    assert not window.is_recipe_valid
    assert window.sequencer.isEnabled()
    assert not window.save_action.isEnabled()
    assert not window.save_as_action.isEnabled()
    assert window.last_valid_recipe == valid_text

    window.on_action_restore_recipe_clicked()
    assert window.is_recipe_valid
    assert window.temporary_recipe_contents == valid_text


def test_schema_invalid_raw_edit_is_retained_and_disables_sequencer(qtbot):
    window = _window_with_recipe(qtbot)
    invalid = window.temporary_recipe_contents.replace(
        "UserInteractionStep", "userinteractionstep", 1
    )

    window.yaml_viewer.setText(invalid)

    assert window.temporary_recipe_contents == invalid
    assert "userinteractionstep" in window.temporary_recipe_contents
    assert not window.is_recipe_valid
    assert not window.sequencer.isEnabled()
    assert window.yaml_viewer.extraSelections()


def test_canonical_save_uses_recipe_to_yaml(tmp_path, qtbot):
    window = _window_with_recipe(qtbot)
    destination = tmp_path / "saved.yaml"
    expected = recipe_to_yaml(parse_recipe_text(window.temporary_recipe_contents).require_recipe())

    assert window._write_recipe(destination)

    assert destination.read_text(encoding="utf-8") == expected
    assert destination.read_text(encoding="utf-8").startswith("---\n")
    assert parse_recipe_text(destination.read_text(encoding="utf-8")).is_valid


def test_save_as_uses_selected_path_and_canonical_output(tmp_path, qtbot, monkeypatch):
    window = _window_with_recipe(qtbot)
    destination = tmp_path / "save-as.yaml"
    monkeypatch.setattr(
        "pypts.YamVIEW.recipe_creator.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), "YAML Files (*.yaml *.yml)"),
    )

    window.on_save_as_clicked()

    assert window.current_file_path == str(destination)
    assert parse_recipe_text(destination.read_text(encoding="utf-8")).is_valid
    assert destination.read_text(encoding="utf-8").startswith("---\n")


def test_new_recipe_wizard_template_is_valid_v2_and_deterministic():
    generator = RecipeCreatorApp()
    data = {
        "name": "Generated",
        "version": "1.0",
        "recipe_version": "2.0.0",
        "description": "Generated through YamVIEW.",
        "main_sequence": "Main",
        "num_steps": 1,
    }

    generated = generator.generate_template_yaml(data)
    parsed = parse_recipe_text(generated)

    assert parsed.is_valid
    assert recipe_to_yaml(parsed.require_recipe()) in generated
