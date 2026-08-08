# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import ast
from pathlib import Path
import textwrap

import pytest

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
    RecipeParseError,
    dump_recipe,
    parse_recipe_file,
    parse_recipe_text,
)


RECIPES = Path(__file__).parents[2] / "src" / "pypts" / "recipes"
PARSER = Path(__file__).parents[2] / "src" / "pypts" / "recipe_parser.py"


def recipe_text(steps="[]", *, recipe_version="1.0.0"):
    raw_steps = textwrap.dedent(steps).strip()
    steps_value = f" {raw_steps}" if raw_steps == "[]" else "\n" + textwrap.indent(raw_steps, "  ")
    return f"""---
name: Parser test
version: "1"
recipe_version: {recipe_version}
description: Parser test recipe
main_sequence: Main
globals: {{}}
---
sequence_name: Main
description: Main sequence
parameters: {{}}
outputs: {{}}
locals: {{}}
setup_steps: []
steps:{steps_value}
teardown_steps: []
"""


def test_parse_builds_typed_mappings_and_defaults():
    steps = """
      - steptype: PythonModuleStep
        step_name: typed mappings
        description: Exercise all mapping models
        action_type: method
        module: tests.py
        method_name: run
        input_mapping:
          direct: {type: direct, value: [1, 2], indexed: true}
          local: {type: local, local_name: local_value}
          global: {type: global, global_name: global_value}
          method: {type: method, value: helper}
        output_mapping:
          passed: {type: passfail}
          exact: {type: equals, value: 3}
          bounded: {type: range, min: 1, max: 4}
          local: {type: local, local_name: saved}
          global: {type: global, global_name: saved}
          chart: {type: image}
      - steptype: SequenceStep
        step_name: passthrough
        description: Exercise passthrough
        sequence: {type: internal, name: Main}
        output_mapping:
          result: {type: passthrough}
    """
    result = parse_recipe_text(recipe_text(steps))
    recipe = result.require_recipe()
    first, second = recipe.sequences[0].steps

    assert first.skip is first.critical is first.continue_on_error is False
    assert isinstance(first.input_mapping["direct"], DirectInput)
    assert isinstance(first.input_mapping["local"], LocalInput)
    assert isinstance(first.input_mapping["global"], GlobalInput)
    assert isinstance(first.input_mapping["method"], MethodInput)
    assert isinstance(first.output_mapping["passed"], PassFailOutput)
    assert isinstance(first.output_mapping["exact"], EqualsOutput)
    assert isinstance(first.output_mapping["bounded"], RangeOutput)
    assert isinstance(first.output_mapping["local"], LocalOutput)
    assert isinstance(first.output_mapping["global"], GlobalOutput)
    assert isinstance(first.output_mapping["chart"], ImageOutput)
    assert isinstance(second.output_mapping["result"], PassthroughOutput)


def test_normalization_warnings_and_canonical_dump():
    steps = """
      - steptype: waitstep
        step_name: wait
        description: Legacy spelling
        input_mapping:
          wait_time: {value: 1}
    """
    result = parse_recipe_text(recipe_text(steps), "legacy.yml")
    assert {warning.code for warning in result.warnings} == {
        "noncanonical-step-type", "implicit-direct-input",
    }
    canonical = dump_recipe(result.require_recipe())
    assert "steptype: WaitStep" in canonical
    assert "type: direct" in canonical
    assert "skip: false" in canonical
    assert not parse_recipe_text(canonical).warnings


def test_contract_diagnostic_has_source_and_nearest_span():
    text = recipe_text("[]").replace("main_sequence: Main", "main_sequence: Missing")
    result = parse_recipe_text(text, "broken.yml")
    diagnostic = next(item for item in result.errors if item.code == "unknown-main-sequence")
    assert diagnostic.source_name == "broken.yml"
    assert diagnostic.span is not None
    expected_line = next(index for index, line in enumerate(text.splitlines(), start=1) if line.startswith("main_sequence:"))
    assert diagnostic.span.start.line == expected_line
    assert diagnostic.span.start.column > 1


def test_missing_field_uses_parent_span():
    text = recipe_text("[]").replace("description: Main sequence\n", "")
    result = parse_recipe_text(text, "missing.yml")
    diagnostic = next(item for item in result.errors if item.code == "missing-field")
    assert diagnostic.path[-1] == "description"
    assert diagnostic.span is not None
    assert diagnostic.span.start.line > 1


def test_duplicate_yaml_keys_are_rejected():
    text = recipe_text("[]").replace("name: Parser test", "name: First\nname: Second")
    result = parse_recipe_text(text)
    assert "duplicate-key" in {item.code for item in result.errors}
    assert result.recipe is None


def test_malformed_and_unsafe_yaml_are_rejected():
    malformed = parse_recipe_text("name: [unterminated")
    unsafe = parse_recipe_text("!!python/object:builtins.object {}")
    assert {item.code for item in malformed.errors} == {"yaml-syntax-error"}
    assert "unsafe-yaml" in {item.code for item in unsafe.errors}


def test_empty_and_non_text_sources_are_rejected():
    assert {item.code for item in parse_recipe_text("  \n").errors} == {"empty-recipe"}
    assert {item.code for item in parse_recipe_text(None).errors} == {"invalid-source"}


def test_file_entry_point_and_read_failure(tmp_path):
    path = tmp_path / "recipe.yml"
    path.write_text(recipe_text("[]"), encoding="utf-8")
    from_file = parse_recipe_file(path)
    from_text = parse_recipe_text(path.read_text(encoding="utf-8"), str(path))
    assert from_file.recipe == from_text.recipe
    assert parse_recipe_file(tmp_path / "missing.yml").errors[0].code == "file-read-error"


def test_require_recipe_raises_with_diagnostics():
    result = parse_recipe_text("")
    with pytest.raises(RecipeParseError) as error:
        result.require_recipe()
    assert error.value.diagnostics == result.diagnostics


def test_unsupported_recipe_version_is_rejected():
    result = parse_recipe_text(recipe_text("[]", recipe_version="2.0.0"))
    assert "unsupported-recipe-version" in {item.code for item in result.errors}


@pytest.mark.parametrize(
    "path",
    sorted(path for path in RECIPES.glob("*.yml") if path.name != "subsequence_executions_draft.yml"),
)
def test_bundled_recipe_parse_dump_reparse_is_model_stable(path):
    first = parse_recipe_file(path)
    assert first.is_valid, first.errors
    canonical = dump_recipe(first.require_recipe())
    second = parse_recipe_text(canonical, f"canonical:{path.name}")
    assert second.is_valid, second.errors
    assert second.recipe == first.recipe


def test_comment_only_draft_is_rejected_as_empty():
    result = parse_recipe_file(RECIPES / "subsequence_executions_draft.yml")
    assert {item.code for item in result.errors} == {"empty-recipe"}


def test_parser_has_no_runtime_gui_or_docs_imports():
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {"pypts.recipe", "pypts.steps", "pypts.YamVIEW", "sphinx"}
    assert not any(name == item or name.startswith(item + ".") for name in imported for item in forbidden)
