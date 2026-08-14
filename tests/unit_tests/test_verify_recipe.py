# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest

from pypts.recipe_parser import parse_recipe_file, recipe_to_yaml
from pypts.YamVIEW.verify_recipe import (
    RecipeValidationError,
    validate_recipe_file,
    validate_recipe_filepath,
    validate_recipe_string_variable,
)

VALID = """---
name: Valid
version: '1'
recipe_version: 2.0.0
description: valid
main_sequence: Main
globals: {}
---
sequence_name: Main
description: main
parameters: {}
outputs: {}
locals: {}
setup_steps: []
steps:
- steptype: WaitStep
  step_name: wait
  description: wait
  input_mapping:
    wait_time: {type: direct, value: 0}
teardown_steps: []
"""


def test_file_and_filepath_wrappers_accept_v2(tmp_path):
    path = tmp_path / "recipe.yml"
    path.write_text(VALID, encoding="utf-8")
    assert validate_recipe_file(path) is None
    assert validate_recipe_filepath(path)


def test_file_wrapper_formats_structured_diagnostics(tmp_path):
    path = tmp_path / "legacy.yml"
    path.write_text(VALID.replace("2.0.0", "1.0.0"), encoding="utf-8")
    with pytest.raises(RecipeValidationError) as caught:
        validate_recipe_file(path)
    assert caught.value.diagnostics
    assert "unsupported-recipe-version" in caught.value.faults[0]
    assert ":4:" in caught.value.faults[0]
    assert not validate_recipe_filepath(path)


def test_string_wrapper_returns_diagnostic_message():
    valid, message = validate_recipe_string_variable(
        VALID.replace("WaitStep", "waitstep")
    )
    assert not valid
    assert "noncanonical-step-type" in message
    assert "WaitStep" in message


def test_wrapper_canonical_output_round_trips(tmp_path):
    path = tmp_path / "recipe.yml"
    path.write_text(VALID, encoding="utf-8")
    definition = parse_recipe_file(path).require_recipe()
    canonical = recipe_to_yaml(definition)
    valid, _ = validate_recipe_string_variable(canonical)
    assert valid
