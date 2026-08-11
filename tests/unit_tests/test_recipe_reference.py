# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import ast
from pathlib import Path

import pytest
import yaml

from pypts.recipe_language import (
    COMMON_STEP_SPEC,
    CONSTRAINT_SPECS,
    DOCUMENTED_DIAGNOSTIC_CODES,
    FILE_SAVE_LOCATION_SPEC,
    HEADER_SPEC,
    INPUT_MAPPING_SPECS,
    OUTPUT_MAPPING_SPECS,
    SEQUENCE_REFERENCE_SPEC,
    SEQUENCE_SPEC,
    STEP_SPECS,
)
from pypts.recipe_parser import (
    DirectInput,
    EqualsOutput,
    GlobalInput,
    GlobalOutput,
    ImageOutput,
    LocalInput,
    LocalOutput,
    MethodInput,
    PassFailOutput,
    PassthroughOutput,
    RangeOutput,
    parse_recipe_text,
)
from pypts.recipe_reference import (
    _fixture_text,
    check_recipe_reference,
    main,
    render_recipe_reference,
)


ROOT = Path(__file__).parents[2]
REFERENCE = ROOT / "docs" / "generated" / "recipe_language_reference.rst"


def _all_structures():
    return (
        HEADER_SPEC,
        SEQUENCE_SPEC,
        COMMON_STEP_SPEC,
        SEQUENCE_REFERENCE_SPEC,
        FILE_SAVE_LOCATION_SPEC,
    )


def test_registry_metadata_is_complete_and_unambiguous():
    step_names = [spec.name.casefold() for spec in STEP_SPECS]
    assert len(step_names) == len(set(step_names))

    for structure in _all_structures():
        assert structure.name and structure.description
        field_names = [field.name for field in structure.fields]
        assert len(field_names) == len(set(field_names))
        assert all(field.description for field in structure.fields)

    for specs in (INPUT_MAPPING_SPECS, OUTPUT_MAPPING_SPECS):
        names = [spec.name for spec in specs]
        assert len(names) == len(set(names))
        for spec in specs:
            assert spec.description and spec.example
            assert spec.example["type"] == spec.name
            assert all(field.description for field in spec.fields)

    for spec in STEP_SPECS:
        assert spec.name and spec.description and spec.example
        assert all(field.description for field in spec.fields)


def test_constraint_diagnostic_registry_is_complete_and_unique():
    constraint_codes = [spec.code for spec in CONSTRAINT_SPECS]
    diagnostic_codes = [code for spec in CONSTRAINT_SPECS for code in spec.diagnostic_codes]
    assert len(constraint_codes) == len(set(constraint_codes))
    assert len(diagnostic_codes) == len(set(diagnostic_codes))
    assert set(diagnostic_codes) == DOCUMENTED_DIAGNOSTIC_CODES
    assert all(spec.scope and spec.description and spec.diagnostic_codes for spec in CONSTRAINT_SPECS)

    discovered = set()
    for relative in ("src/pypts/recipe_language.py", "src/pypts/recipe_parser.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func.id if isinstance(node.func, ast.Name) else None
            if function not in {"Diagnostic", "_source_diagnostic"}:
                continue
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                discovered.add(node.args[0].value)
    assert discovered <= DOCUMENTED_DIAGNOSTIC_CODES


def test_reference_generator_has_no_runtime_gui_or_sphinx_imports():
    tree = ast.parse((ROOT / "src/pypts/recipe_reference.py").read_text(encoding="utf-8"))
    imported = set()
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


@pytest.mark.parametrize(
    "spec",
    [spec for spec in STEP_SPECS if spec.source_allowed],
    ids=lambda spec: spec.name,
)
def test_every_public_step_example_is_an_executable_parser_fixture(spec):
    result = parse_recipe_text(_fixture_text(spec.example), f"fixture:{spec.name}")
    assert result.is_valid, result.errors
    assert not result.warnings
    assert result.require_recipe().sequences[0].steps[0].steptype == spec.name


INPUT_TYPES = {
    "direct": DirectInput,
    "local": LocalInput,
    "global": GlobalInput,
    "method": MethodInput,
}


@pytest.mark.parametrize("spec", INPUT_MAPPING_SPECS, ids=lambda spec: spec.name)
def test_every_input_mapping_example_builds_its_typed_model(spec):
    step = {
        "steptype": "PythonModuleStep",
        "step_name": "Input fixture",
        "description": "Input mapping fixture.",
        "action_type": "method",
        "module": "tests.py",
        "method_name": "run",
        "input_mapping": {"example": dict(spec.example)},
        "output_mapping": {},
    }
    result = parse_recipe_text(_fixture_text(step))
    assert result.is_valid, result.errors
    value = result.require_recipe().sequences[0].steps[0].input_mapping["example"]
    assert isinstance(value, INPUT_TYPES[spec.name])


OUTPUT_TYPES = {
    "passfail": PassFailOutput,
    "equals": EqualsOutput,
    "range": RangeOutput,
    "passthrough": PassthroughOutput,
    "local": LocalOutput,
    "global": GlobalOutput,
    "image": ImageOutput,
}


@pytest.mark.parametrize("spec", OUTPUT_MAPPING_SPECS, ids=lambda spec: spec.name)
def test_every_output_mapping_example_builds_its_typed_model(spec):
    step = {
        "steptype": "PythonModuleStep",
        "step_name": "Output fixture",
        "description": "Output mapping fixture.",
        "action_type": "method",
        "module": "tests.py",
        "method_name": "run",
        "input_mapping": {},
        "output_mapping": {"example": dict(spec.example)},
    }
    result = parse_recipe_text(_fixture_text(step))
    assert result.is_valid, result.errors
    value = result.require_recipe().sequences[0].steps[0].output_mapping["example"]
    assert isinstance(value, OUTPUT_TYPES[spec.name])


def test_mapping_field_types_are_enforced_from_the_registry():
    step = {
        "steptype": "PythonModuleStep",
        "step_name": "Invalid mapping fields",
        "description": "Mapping field type fixture.",
        "action_type": "method",
        "module": "tests.py",
        "method_name": "run",
        "input_mapping": {"source": {"type": "local", "local_name": 1}},
        "output_mapping": {"destination": {"type": "global", "global_name": 2}},
    }
    result = parse_recipe_text(_fixture_text(step))
    assert {item.code for item in result.errors} == {
        "invalid-input-field-type",
        "invalid-output-field-type",
    }


@pytest.mark.parametrize("report", ("overwrite", "append"))
def test_every_report_mode_from_the_registry_parses(report):
    step = {
        "steptype": "WaitStep",
        "step_name": "Wait",
        "description": "Report mode fixture.",
        "input_mapping": {"wait_time": {"type": "direct", "value": 0}},
        "output_mapping": {},
    }
    documents = list(yaml.safe_load_all(_fixture_text(step)))
    documents[0]["report"] = report
    source = yaml.safe_dump_all(documents, explicit_start=True, sort_keys=False)
    assert parse_recipe_text(source).is_valid


@pytest.mark.parametrize("action_type", ("method", "read_attribute", "write_attribute"))
def test_every_python_action_type_from_the_registry_parses(action_type):
    step = {
        "steptype": "PythonModuleStep",
        "step_name": "Action fixture",
        "description": "Action choice fixture.",
        "action_type": action_type,
        "module": "tests.py",
        "input_mapping": {},
        "output_mapping": {},
    }
    if action_type == "method":
        step["method_name"] = "run"
    assert parse_recipe_text(_fixture_text(step)).is_valid


def test_generated_reference_is_complete_and_current():
    rendered = render_recipe_reference()
    assert rendered == REFERENCE.read_text(encoding="utf-8")
    for spec in STEP_SPECS:
        anchor = f".. _recipe-step-{spec.name.lower()}:"
        assert rendered.count(anchor) == int(spec.source_allowed)
    for spec in INPUT_MAPPING_SPECS:
        assert rendered.count(f".. _recipe-input-{spec.name}:") == 1
    for spec in OUTPUT_MAPPING_SPECS:
        assert rendered.count(f".. _recipe-output-{spec.name}:") == 1


def test_reference_cli_writes_checks_and_detects_stale_files(tmp_path, capsys):
    path = tmp_path / "nested" / "reference.rst"
    assert main([str(path)]) == 0
    assert check_recipe_reference(path)
    assert main(["--check", str(path)]) == 0

    path.write_text("stale\n", encoding="utf-8")
    assert main(["--check", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == "stale\n"
    assert "missing or stale" in capsys.readouterr().err

    missing = tmp_path / "missing.rst"
    assert main(["--check", str(missing)]) == 1
    assert not missing.exists()
