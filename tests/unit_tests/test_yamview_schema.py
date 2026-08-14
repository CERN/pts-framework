# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Schema-driven YamVIEW form tests."""

from pypts.recipe_language import INPUT_MODELS, OUTPUT_MODELS, STEP_MODELS
from pypts.YamVIEW.recipe_step_setup import (
    DiscriminatedMappingWidget,
    Step_setup,
    recipe_form_description,
)


def discriminator(model):
    field_name = "steptype" if "steptype" in model.model_fields else "type"
    return model.model_fields[field_name].examples[0]


def test_form_selectors_and_metadata_come_from_production_schema():
    description = recipe_form_description()
    assert set(description["steps"]) == {discriminator(model) for model in STEP_MODELS}
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
