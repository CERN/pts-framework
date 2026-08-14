# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Schema-driven YamVIEW form tests."""

import pytest
from PySide6.QtWidgets import QCheckBox, QMessageBox

from pypts.recipe_language import (
    INPUT_MODELS,
    OUTPUT_MODELS,
    STEP_DEFINITION_MODELS,
)
from pypts.YamVIEW.recipe_step_setup import (
    DiscriminatedMappingWidget,
    Step_setup,
    recipe_form_description,
    schema_widget_kind,
)


def discriminator(model):
    field_name = "steptype" if "steptype" in model.model_fields else "type"
    return model.model_fields[field_name].examples[0]


def test_form_selectors_and_metadata_come_from_production_schema():
    description = recipe_form_description()
    assert set(description["steps"]) == {
        discriminator(model) for model in STEP_DEFINITION_MODELS
    }
    assert set(description["inputs"]) == {discriminator(model) for model in INPUT_MODELS}
    assert set(description["outputs"]) == {discriminator(model) for model in OUTPUT_MODELS}

    fields = description["steps"]["PythonModuleStep"]["fields"]
    assert fields["module"]["required"] is True
    assert fields["module"]["description"]
    assert fields["module"]["examples"]
    assert fields["skip"]["default"] is False
    assert fields["input_mapping"]["widget"] == "structured"


def test_step_dialog_round_trips_discriminated_mapping_rows(qapp, qtbot):
    dialog = Step_setup()
    qtbot.addWidget(dialog)
    node = {
        "steptype": "WaitStep",
        "step_name": "pause",
        "description": "Pause briefly.",
        "input_mapping": {"wait_time": {"type": "direct", "value": 0}},
        "output_mapping": {"verdict": {"type": "passfail"}},
    }

    dialog.load_definition(node)
    assert isinstance(
        dialog.schema_form.field_widgets["input_mapping"],
        DiscriminatedMappingWidget,
    )
    dialog.accept()

    authored = dialog.result_step["_node"]
    assert authored["input_mapping"]["wait_time"]["type"] == "direct"
    assert authored["input_mapping"]["wait_time"]["value"] == 0
    assert authored["output_mapping"]["verdict"]["type"] == "passfail"


def test_discriminator_has_one_authoritative_selector(qtbot):
    dialog = Step_setup()
    qtbot.addWidget(dialog)

    assert {
        dialog.list_steptype.itemText(index)
        for index in range(dialog.list_steptype.count())
    } == set(recipe_form_description()["steps"])
    assert "steptype" not in dialog.schema_form.field_widgets

    mapping = DiscriminatedMappingWidget("inputs")
    qtbot.addWidget(mapping)
    mapping.add_row("value", {"type": "direct", "value": 1})
    assert "type" not in mapping.rows[0]["form"].field_widgets


def test_boolean_fields_are_labeled_clickable_and_serialized(qtbot):
    dialog = Step_setup()
    qtbot.addWidget(dialog)
    dialog.load_definition(
        {
            "steptype": "UserInteractionStep",
            "step_name": "Boolean options",
            "description": "Exercise all common execution flags.",
            "skip": True,
            "critical": False,
            "continue_on_error": True,
            "input_mapping": {},
            "output_mapping": {},
        }
    )

    expected = {
        "skip": ("Skip", True),
        "critical": ("Critical", False),
        "continue_on_error": ("Continue on error", True),
    }
    for name, (label, checked) in expected.items():
        widget = dialog.schema_form.field_widgets[name]
        assert isinstance(widget, QCheckBox)
        assert widget.text() == label
        assert widget.toolTip()
        assert widget.isChecked() is checked
        widget.click()

    dialog.accept()
    authored = dialog.result_step["_node"]
    assert authored["skip"] is False
    assert authored["critical"] is True
    assert authored["continue_on_error"] is False


def test_step_type_switch_uses_top_selector_and_honors_confirmation(qtbot, monkeypatch):
    dialog = Step_setup()
    qtbot.addWidget(dialog)
    dialog.load_definition(
        {
            "steptype": "UserInteractionStep",
            "step_name": "Switch me",
            "description": "Keep common fields.",
            "input_mapping": {},
            "output_mapping": {},
        }
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Cancel)
    dialog.list_steptype.setCurrentText("UserWriteStep")
    assert dialog.list_steptype.currentText() == "UserInteractionStep"

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Ok)
    dialog.list_steptype.setCurrentText("UserWriteStep")
    assert dialog.list_steptype.currentText() == "UserWriteStep"
    assert "steptype" not in dialog.schema_form.field_widgets
    assert dialog.schema_form.values()["step_name"] == "Switch me"


STEP_SAMPLES = {
    "PythonModuleStep": {
        "action_type": "method",
        "module": "example_tests.py",
        "method_name": "run",
    },
    "SequenceStep": {"sequence": {"type": "internal", "name": "Other"}},
    "UserInteractionStep": {},
    "WaitStep": {"input_mapping": {"wait_time": {"type": "direct", "value": 0}}},
    "UserLoadingStep": {
        "file_save_location": {"type": "local", "variable": "selected"}
    },
    "UserRunMethodStep": {
        "trigger_response": {"run": True},
        "action_type": "method",
        "module": "example_tests.py",
        "method_name": "run",
    },
    "UserWriteStep": {},
    "SerialNumberStep": {},
    "SSHConnectStep": {},
    "SSHCloseStep": {},
    "SSHUploadStep": {
        "files": [{"local": "payload.bin", "remote": "/tmp/payload.bin"}],
        "permissions": "0755",
    },
}


@pytest.mark.parametrize("step_type", STEP_SAMPLES)
def test_every_step_discriminator_round_trips_through_one_dialog(qtbot, step_type):
    dialog = Step_setup()
    qtbot.addWidget(dialog)
    node = {
        "steptype": step_type,
        "step_name": f"Example {step_type}",
        "description": f"A complete {step_type} example.",
        "input_mapping": {},
        "output_mapping": {},
        **STEP_SAMPLES[step_type],
    }

    dialog.load_definition(node)
    dialog.accept()

    assert dialog.result_step["_node"]["steptype"] == step_type
    assert dialog.result_step["_node"]["description"] == node["description"]


@pytest.mark.parametrize(
    ("mapping_kind", "values"),
    [
        (
            "inputs",
            {
                "literal": {
                    "type": "direct",
                    "value": [1, {"nested": True}],
                    "indexed": False,
                },
                "local": {"type": "local", "local_name": "inside"},
                "global": {"type": "global", "global_name": "shared"},
                "method": {"type": "method", "value": {"call": "helper"}},
            },
        ),
        (
            "outputs",
            {
                "pass": {"type": "passfail"},
                "equal": {"type": "equals", "value": {"answer": 42}},
                "range": {"type": "range", "min": 0, "max": 10},
                "nested": {"type": "passthrough"},
                "local": {"type": "local", "local_name": "inside"},
                "global": {"type": "global", "global_name": "shared"},
                "image": {"type": "image"},
            },
        ),
    ],
)
def test_every_mapping_discriminator_round_trips(qtbot, mapping_kind, values):
    widget = DiscriminatedMappingWidget(mapping_kind)
    qtbot.addWidget(widget)
    widget.load_values(values)

    assert widget.values() == values


def test_schema_widget_selection_covers_structured_and_primitive_json_values():
    assert schema_widget_kind({"type": "array"}) == "structured"
    assert schema_widget_kind({"type": "object"}) == "structured"
    assert schema_widget_kind({}) == "structured"
    assert schema_widget_kind({"type": "boolean"}) == "boolean"
    assert schema_widget_kind({"type": "number"}) == "number"
    assert schema_widget_kind({"type": "string"}) == "text"


def test_invalid_structured_json_is_reported_without_committing(qtbot):
    dialog = Step_setup()
    qtbot.addWidget(dialog)
    dialog._skip_warning = True
    dialog.list_steptype.setCurrentText("SSHUploadStep")
    files = dialog.schema_form.field_widgets["files"]
    files.setPlainText("[not valid JSON")

    with pytest.raises(ValueError, match="files.*valid JSON"):
        dialog.schema_form.values()

    assert not hasattr(dialog, "result_step")


def test_switching_step_type_retains_compatible_common_fields(qtbot):
    dialog = Step_setup()
    qtbot.addWidget(dialog)
    dialog.load_definition(
        {
            "steptype": "UserInteractionStep",
            "step_name": "Keep me",
            "description": "Common description",
            "skip": True,
            "input_mapping": {"message": {"type": "direct", "value": "Hello"}},
            "output_mapping": {},
        }
    )
    dialog._skip_warning = True
    dialog.list_steptype.setCurrentText("UserWriteStep")

    values = dialog.schema_form.values()
    assert values["step_name"] == "Keep me"
    assert values["description"] == "Common description"
    assert values["skip"] is True
    assert values["input_mapping"]["message"] == {
        "type": "direct",
        "value": "Hello",
        "indexed": False,
    }
