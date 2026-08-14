# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Production recipe-language model and parser evaluation suite."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pypts import recipe_language, recipe_parser
from pypts.recipe_artifacts import (
    render_json_schema,
    write_artifacts,
)
from pypts.recipe_language import (
    INPUT_MODELS,
    OUTPUT_MODELS,
    STEP_DEFINITION_MODELS,
)
from pypts.recipe_parser import (
    RecipeParseError,
    parse_recipe_file,
    parse_recipe_text,
    recipe_to_yaml,
)
from pypts.recipe_reference import render_reference

ROOT = Path(__file__).parents[2]
RECIPES = ROOT / "src" / "pypts" / "recipes"
SETUP_TEMPLATES = ROOT / "src" / "pypts" / "examples" / "environment_setup_tools"
MAINTAINED_RECIPES = sorted(RECIPES.glob("*.yml"))
MAINTAINED_TEMPLATES = sorted(SETUP_TEMPLATES.glob("*/*.yml"))


def test_step_definition_names_are_the_only_public_union_and_model_registry():
    assert hasattr(recipe_language, "StepDefinition")
    assert hasattr(recipe_language, "STEP_DEFINITION_MODELS")
    assert not hasattr(recipe_language, "Step")
    assert not hasattr(recipe_language, "CommonStep")
    assert not hasattr(recipe_language, "STEP_MODELS")


def header(**updates):
    value = {
        "name": "Pydantic spike",
        "version": "1.0",
        "recipe_version": "2.0.0",
        "description": "Candidate recipe.",
        "main_sequence": "Main",
        "globals": {},
    }
    value.update(updates)
    return value


def sequence(steps=None, **updates):
    value = {
        "sequence_name": "Main",
        "description": "Main sequence.",
        "parameters": {},
        "outputs": {},
        "locals": {},
        "setup_steps": [],
        "steps": steps or [],
        "teardown_steps": [],
    }
    value.update(updates)
    return value


def source(*documents):
    return yaml.safe_dump_all(documents, explicit_start=True, sort_keys=False)


def common(kind, **updates):
    value = {
        "steptype": kind,
        "step_name": kind,
        "description": f"Exercise {kind}.",
        "input_mapping": {},
        "output_mapping": {},
    }
    value.update(updates)
    return value


STEP_EXAMPLES = {
    "PythonModuleStep": common(
        "PythonModuleStep", action_type="method", module="tests.py", method_name="run"
    ),
    "SequenceStep": common(
        "SequenceStep", sequence={"type": "internal", "name": "Target"}
    ),
    "UserInteractionStep": common("UserInteractionStep"),
    "WaitStep": common(
        "WaitStep", input_mapping={"wait_time": {"type": "direct", "value": 0}}
    ),
    "UserLoadingStep": common(
        "UserLoadingStep",
        file_save_location={"type": "local", "variable": "selected"},
    ),
    "UserRunMethodStep": common(
        "UserRunMethodStep",
        trigger_response="run",
        action_type="method",
        module="tests.py",
        method_name="run",
    ),
    "UserWriteStep": common("UserWriteStep"),
    "SerialNumberStep": common("SerialNumberStep"),
    "SSHConnectStep": common("SSHConnectStep"),
    "SSHCloseStep": common("SSHCloseStep"),
    "SSHUploadStep": common(
        "SSHUploadStep",
        files=[{"local": "bin/tool", "remote": "/tmp/tool"}],
        permissions="0755",
        skip_if_sha256_match=True,
        local_package="fixtures",
    ),
}


def recipe_for_step(step):
    globals_value = {
        "ssh_client": None,
        "host": "target",
        "user": "root",
        "port": 22,
        "password": "secret",
    }
    main = sequence([step])
    documents = [header(globals=globals_value), main]
    if step["steptype"] == "SequenceStep":
        documents.append(sequence(sequence_name="Target"))
    elif step["steptype"] == "SSHUploadStep":
        main["setup_steps"] = [common("SSHConnectStep")]
        main["teardown_steps"] = [common("SSHCloseStep")]
    elif step["steptype"] == "SSHConnectStep":
        main["teardown_steps"] = [common("SSHCloseStep")]
    return source(*documents)


@pytest.mark.parametrize(
    "model", STEP_DEFINITION_MODELS, ids=lambda model: model.__name__
)
def test_every_step_validates_serializes_and_reparses(model):
    first = parse_recipe_text(recipe_for_step(STEP_EXAMPLES[model.__name__]))
    assert first.is_valid, first.errors
    second = parse_recipe_text(recipe_to_yaml(first.require_recipe()))
    assert second.is_valid, second.errors
    assert second.recipe == first.recipe


INPUT_EXAMPLES = {
    "DirectInput": {"type": "direct", "value": [1, 2], "indexed": True},
    "LocalInput": {"type": "local", "local_name": "local_value"},
    "GlobalInput": {"type": "global", "global_name": "global_value"},
    "MethodInput": {"type": "method", "value": "helper"},
}


@pytest.mark.parametrize("model", INPUT_MODELS, ids=lambda model: model.__name__)
def test_every_input_mapping_validates_serializes_and_reparses(model):
    step = STEP_EXAMPLES["PythonModuleStep"] | {
        "input_mapping": {"example": INPUT_EXAMPLES[model.__name__]}
    }
    first = parse_recipe_text(recipe_for_step(step))
    assert isinstance(first.require_recipe().sequences[0].steps[0].input_mapping["example"], model)
    assert parse_recipe_text(recipe_to_yaml(first.require_recipe())).recipe == first.recipe


OUTPUT_EXAMPLES = {
    "PassFailOutput": {"type": "passfail"},
    "EqualsOutput": {"type": "equals", "value": 3},
    "RangeOutput": {"type": "range", "min": 1, "max": 4},
    "PassthroughOutput": {"type": "passthrough"},
    "LocalOutput": {"type": "local", "local_name": "saved"},
    "GlobalOutput": {"type": "global", "global_name": "saved"},
    "ImageOutput": {"type": "image"},
}


@pytest.mark.parametrize("model", OUTPUT_MODELS, ids=lambda model: model.__name__)
def test_every_output_mapping_validates_serializes_and_reparses(model):
    step = STEP_EXAMPLES["PythonModuleStep"] | {
        "output_mapping": {"example": OUTPUT_EXAMPLES[model.__name__]}
    }
    first = parse_recipe_text(recipe_for_step(step))
    assert isinstance(first.require_recipe().sequences[0].steps[0].output_mapping["example"], model)
    assert parse_recipe_text(recipe_to_yaml(first.require_recipe())).recipe == first.recipe


def test_defaults_are_typed_dumped_and_models_are_frozen():
    recipe = parse_recipe_text(recipe_for_step(STEP_EXAMPLES["UserInteractionStep"])).require_recipe()
    step = recipe.sequences[0].steps[0]
    assert step.skip is step.critical is step.continue_on_error is False
    assert recipe.header.report == "overwrite"
    dumped = recipe_to_yaml(recipe)
    assert "report: overwrite" in dumped and "skip: false" in dumped
    with pytest.raises(ValidationError):
        step.skip = True


def test_recipe_to_yaml_is_deterministic_explicit_and_formatting_destructive():
    assert recipe_parser.recipe_to_yaml is recipe_to_yaml
    assert not hasattr(recipe_parser, "dump_recipe")
    text = recipe_for_step(STEP_EXAMPLES["UserInteractionStep"])
    commented = "# This comment is intentionally not retained.\n" + text
    recipe = parse_recipe_text(commented).require_recipe()

    first = recipe_to_yaml(recipe)
    second = recipe_to_yaml(recipe)

    assert first == second
    assert first.startswith("---\n")
    assert first.count("---\n") == 2
    assert "report: overwrite" in first
    assert "# This comment" not in first
    assert parse_recipe_text(first).require_recipe() == recipe
    with pytest.raises(TypeError, match="recipe_to_yaml expects a Recipe"):
        recipe_to_yaml({})


def test_strict_types_unknown_fields_and_structural_rules_are_rejected():
    bad = STEP_EXAMPLES["PythonModuleStep"] | {
        "skip": 0,
        "surprise": True,
        "method_name": None,
    }
    codes = {item.code for item in parse_recipe_text(recipe_for_step(bad)).errors}
    assert {"invalid-field-type", "unknown-field"} <= codes

    missing_method = STEP_EXAMPLES["PythonModuleStep"] | {"method_name": None}
    assert "missing-method-name" in {
        item.code for item in parse_recipe_text(recipe_for_step(missing_method)).errors
    }

    wait = common("WaitStep")
    assert "missing-required-input" in {
        item.code for item in parse_recipe_text(recipe_for_step(wait)).errors
    }

    nested = STEP_EXAMPLES["PythonModuleStep"] | {
        "input_mapping": {"local": {"type": "local", "local_name": 1}}
    }
    finding = next(
        item for item in parse_recipe_text(recipe_for_step(nested)).errors
        if item.code == "invalid-field-type"
    )
    assert finding.path[-2:] == ("local", "local_name")


def test_discriminators_are_explicit_and_canonical():
    lowercase = common(
        "waitstep", input_mapping={"wait_time": {"type": "direct", "value": 1}}
    )
    omitted_type = STEP_EXAMPLES["WaitStep"] | {
        "input_mapping": {"wait_time": {"value": 1}}
    }
    unknown = common("InventedStep")
    missing_output_type = STEP_EXAMPLES["PythonModuleStep"] | {
        "output_mapping": {"result": {"value": 1}}
    }
    assert {item.code for item in parse_recipe_text(recipe_for_step(lowercase)).errors} == {
        "noncanonical-step-type"
    }
    assert {item.code for item in parse_recipe_text(recipe_for_step(omitted_type)).errors} == {
        "missing-input-type"
    }
    assert {item.code for item in parse_recipe_text(recipe_for_step(unknown)).errors} == {
        "unknown-step-type"
    }
    assert {
        item.code for item in parse_recipe_text(recipe_for_step(missing_output_type)).errors
    } == {"missing-output-type"}


def test_v1_migration_errors_are_aggregated_across_documents():
    legacy = header(recipe_version="1.0.0")
    first = sequence(
        [common("waitstep", input_mapping={"wait_time": {"value": 1}})],
        serial_number=12,
    )
    second = sequence(
        [STEP_EXAMPLES["WaitStep"] | {
            "input_mapping": {"wait_time": {"value": 1}}
        }],
        sequence_name="Other",
        serial_number="old",
    )
    result = parse_recipe_text(source(legacy, first, second), "legacy.yml")
    codes = [item.code for item in result.errors]
    assert codes.count("removed-sequence-field") == 2
    assert {"unsupported-recipe-version", "noncanonical-step-type", "missing-input-type"} <= set(codes)
    assert all(item.source_name == "legacy.yml" and item.span is not None for item in result.errors)


def test_missing_recipe_version_has_a_clear_diagnostic():
    missing_version = header()
    del missing_version["recipe_version"]
    result = parse_recipe_text(source(missing_version, sequence()))
    finding = next(item for item in result.errors if item.path[-1:] == ("recipe_version",))
    assert finding.code == "missing-field"


def test_source_spans_point_to_fields_and_nearest_parent():
    text = source(header(main_sequence="Missing"), sequence())
    result = parse_recipe_text(text, "broken.yml")
    finding = next(item for item in result.errors if item.code == "unknown-main-sequence")
    expected = next(
        index for index, line in enumerate(text.splitlines(), start=1)
        if line.startswith("main_sequence:")
    )
    assert finding.source_name == "broken.yml"
    assert finding.span is not None and finding.span.start.line == expected

    missing = source(header(), sequence()).replace("description: Main sequence.\n", "")
    finding = next(
        item for item in parse_recipe_text(missing).errors
        if item.code == "missing-field" and item.path[-1] == "description"
    )
    assert finding.span is not None and finding.span.start.line > 1


def test_yaml_failures_duplicate_keys_and_recursive_aliases():
    malformed = parse_recipe_text("name: [unterminated")
    unsafe = parse_recipe_text("!!python/object:builtins.object {}")
    duplicate = parse_recipe_text(
        source(header(), sequence()).replace("name: Pydantic spike", "name: First\nname: Second")
    )
    recursive = parse_recipe_text("---\n&a {name: *a}\n")
    assert {item.code for item in malformed.errors} == {"yaml-syntax-error"}
    assert "unsafe-yaml" in {item.code for item in unsafe.errors}
    assert "duplicate-key" in {item.code for item in duplicate.errors}
    assert "recursive-alias" in {item.code for item in recursive.errors}


def test_file_api_empty_sources_and_require_recipe(tmp_path):
    path = tmp_path / "recipe.yml"
    path.write_text(source(header(), sequence()), encoding="utf-8")
    assert parse_recipe_file(path).is_valid
    assert parse_recipe_file(tmp_path / "missing.yml").errors[0].code == "file-read-error"
    assert parse_recipe_text(None).errors[0].code == "invalid-source"
    assert parse_recipe_text(" # comment only\n").errors[0].code == "empty-recipe"
    result = parse_recipe_text("")
    with pytest.raises(RecipeParseError) as error:
        result.require_recipe()
    assert error.value.diagnostics == result.diagnostics


def test_cross_document_semantic_rules_report_custom_codes():
    nested = common(
        "SequenceStep",
        sequence={"type": "internal", "name": "Missing"},
        input_mapping={
            "left": {"type": "direct", "value": [1], "indexed": True},
            "right": {"type": "direct", "value": [1, 2], "indexed": True},
        },
        output_mapping={
            "result": {"type": "passthrough"},
            "passed": {"type": "passfail"},
        },
    )
    duplicate = sequence(sequence_name="Main")
    result = parse_recipe_text(source(header(), sequence([nested]), duplicate))
    assert {
        "duplicate-sequence",
        "unknown-sequence-reference",
        "unequal-indexed-inputs",
        "mixed-passthrough",
    } <= {item.code for item in result.errors}


def test_ssh_context_and_ordering_are_semantic_rules():
    upload = STEP_EXAMPLES["SSHUploadStep"]
    unclosed = sequence([upload], setup_steps=[common("SSHConnectStep")])
    result = parse_recipe_text(source(header(), unclosed))
    codes = {item.code for item in result.errors}
    assert {"missing-ssh-global", "missing-ssh-credential", "missing-ssh-close"} <= codes

    before_connect = sequence([upload, common("SSHConnectStep")], teardown_steps=[common("SSHCloseStep")])
    assert "missing-ssh-connect" in {
        item.code for item in parse_recipe_text(source(header(), before_connect)).errors
    }


@pytest.mark.parametrize("path", MAINTAINED_RECIPES + MAINTAINED_TEMPLATES)
def test_every_maintained_recipe_and_setup_template_is_valid_v2(path):
    result = parse_recipe_file(path)
    assert result.is_valid, result.errors
    assert not result.diagnostics
    assert result.require_recipe().header.recipe_version == "2.0.0"


@pytest.mark.parametrize("path", MAINTAINED_RECIPES)
def test_every_maintained_recipe_is_semantically_stable_when_serialized(path):
    first = parse_recipe_file(path).require_recipe()
    serialized = recipe_to_yaml(first)
    second = parse_recipe_text(serialized, f"serialized:{path.name}")
    assert second.is_valid, second.errors
    assert second.require_recipe() == first


def test_generated_schema_and_reference_are_complete_and_current(tmp_path):
    schema_text = render_json_schema()
    schema = json.loads(schema_text)
    reference = render_reference(schema)
    schema_path = tmp_path / "recipe_language.schema.json"
    reference_path = tmp_path / "recipe_language_reference.rst"
    write_artifacts(schema_path, reference_path)
    assert schema_text == schema_path.read_text(encoding="utf-8")
    assert reference == reference_path.read_text(encoding="utf-8")
    definitions = schema["$defs"]
    for model in STEP_DEFINITION_MODELS + INPUT_MODELS + OUTPUT_MODELS:
        assert model.__name__ in definitions
        kind = model.model_fields.get("steptype") or model.model_fields["type"]
        anchor_kind = kind.examples[0].lower()
        group = (
            "step"
            if model in STEP_DEFINITION_MODELS
            else "input"
            if model in INPUT_MODELS
            else "output"
        )
        assert reference.count(f".. _recipe-v2-{group}-{anchor_kind}:") == 1

    report = STEP_DEFINITION_MODELS[0].model_fields["skip"]
    assert report.description in reference
    assert 'default ``false``' in reference
    assert 'Example: ``false``.' in reference


def test_spike_has_no_runtime_gui_yamview_or_sphinx_imports():
    imported = set()
    for path in Path(__file__).parent.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    forbidden = {"pypts.recipe", "pypts.steps", "pypts.YamVIEW", "sphinx"}
    assert not any(
        name == item or name.startswith(item + ".")
        for name in imported
        for item in forbidden
    )
