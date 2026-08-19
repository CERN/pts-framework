# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Recipe module (src/pypts/recipe/).

The layer under test is pure data: parse a multi-document YAML file into
Recipe -> Sequence -> Step objects, refuse anything malformed, execute
nothing. Every refusal is a RecipeError so CORE has exactly one type to
catch, and every one of the old loader's silent mistakes (skipped unnamed
sequences, last-wins duplicates) is a loud error here.

The fixture is data/wait_recipe.yml - the smallest recipe that runs.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from pypts.recipe.recipe import Recipe, RecipeError, Sequence
from pypts.step.steps import WaitStep

WAIT_RECIPE = Path(__file__).parent / "data" / "wait_recipe.yml"

PLACEHOLDER = "placeholder - test not implemented yet"

#: A minimal, valid recipe as text, so a test can break one thing at a time.
VALID = """\
name: Wait demo
description: A demo.
version: 1.0.0
main_sequence: Main
globals: {}
---
sequence_name: Main
description: One wait.
parameters: {}
locals: {}
outputs: {}
setup_steps: []
steps:
  - steptype: WaitStep
    step_name: Only wait
    input_mapping:
      wait_time: {value: '0.01'}
    output_mapping: {}
teardown_steps: []
"""


def test_recipe_is_parsed_from_yaml():
    recipe = Recipe.from_file(str(WAIT_RECIPE))

    assert recipe.name == "Wait demo"
    assert recipe.version == "1.0.0"
    assert recipe.main_sequence == "Main"
    assert recipe.globals == {}
    assert recipe.file_name == "wait_recipe.yml"
    assert list(recipe.sequences) == ["Main"]

    main = recipe.sequences["Main"]
    assert isinstance(main, Sequence)
    assert [step.name for step in main.steps] == ["First wait", "Second wait"]
    assert all(isinstance(step, WaitStep) for step in main.steps)
    assert main.teardown_steps == []


def test_setup_steps_are_ordinary_steps_that_run_first():
    """Setup and steps are one flat list - only teardown genuinely differs."""
    text = VALID.replace(
        "setup_steps: []",
        """\
setup_steps:
  - steptype: WaitStep
    step_name: Warm up
    input_mapping:
      wait_time: {value: '0'}
    output_mapping: {}""",
    )
    recipe = Recipe.from_yaml_text(text)
    assert [step.name for step in recipe.sequences["Main"].steps] == ["Warm up", "Only wait"]


def test_recipe_is_data_only_and_carries_no_execution_logic():
    """The old Recipe mixed data, engine and events - the split is the point of the port."""
    assert not hasattr(Recipe, "run")
    assert not hasattr(Sequence, "run")
    # In a fresh interpreter (this suite has long since imported everything),
    # importing the recipe layer must not pull in the Sequencer.
    check = "import sys, pypts.recipe.recipe; sys.exit('pypts.sequencer' in sys.modules)"
    subprocess.run([sys.executable, "-c", check], check=True)


def test_a_missing_recipe_file_is_a_recipe_error():
    with pytest.raises(RecipeError, match="no_such_file"):
        Recipe.from_file("no_such_file.yml")


def test_unparseable_yaml_is_a_recipe_error():
    with pytest.raises(RecipeError):
        Recipe.from_yaml_text("name: [unclosed")


def test_an_empty_file_is_a_recipe_error():
    with pytest.raises(RecipeError):
        Recipe.from_yaml_text("")


def test_required_header_fields_are_enforced():
    for field in ("name", "description", "version", "main_sequence", "globals"):
        broken = "\n".join(
            line for line in VALID.splitlines() if not line.startswith(f"{field}:")
        )
        with pytest.raises(RecipeError, match=field):
            Recipe.from_yaml_text(broken)


def test_a_sequence_without_a_name_is_refused():
    """The old loader logged and silently skipped it."""
    broken = VALID.replace("sequence_name: Main", "description_only: oops")
    with pytest.raises(RecipeError, match="sequence_name"):
        Recipe.from_yaml_text(broken)


def test_a_duplicate_sequence_name_is_refused():
    """The old loader let the last one silently win."""
    header, sequence = VALID.split("---")
    doubled = header + "---" + sequence + "---" + sequence
    with pytest.raises(RecipeError, match="Main"):
        Recipe.from_yaml_text(doubled)


def test_a_missing_main_sequence_is_refused():
    broken = VALID.replace("main_sequence: Main", "main_sequence: Missing")
    with pytest.raises(RecipeError, match="Missing"):
        Recipe.from_yaml_text(broken)


def test_an_unknown_steptype_names_itself_and_the_sequence():
    broken = VALID.replace("steptype: WaitStep", "steptype: PythonModulStep")
    with pytest.raises(RecipeError, match="PythonModulStep") as excinfo:
        Recipe.from_yaml_text(broken)
    assert "Main" in str(excinfo.value)


def test_an_unknown_step_key_is_refused_with_context():
    """Every YAML key is a constructor argument, so a typo fails at load time."""
    broken = VALID.replace("step_name: Only wait", "step_name: Only wait\n    stepp_skip: true")
    with pytest.raises(RecipeError, match=r"Only wait|Main"):
        Recipe.from_yaml_text(broken)


def test_a_sequence_missing_a_required_key_is_refused():
    broken = VALID.replace("locals: {}\n", "")
    with pytest.raises(RecipeError, match="locals"):
        Recipe.from_yaml_text(broken)


def test_to_summary_covers_every_step_that_will_emit_events():
    """The summary is what pre-fills a frontend's step table, and teardown
    steps emit StepStarted/StepFinished too - so they must have rows."""
    text = VALID.replace(
        "teardown_steps: []",
        """\
teardown_steps:
  - steptype: WaitStep
    step_name: Cool down
    input_mapping:
      wait_time: {value: '0'}
    output_mapping: {}""",
    )
    recipe = Recipe.from_yaml_text(text)

    summaries = recipe.to_summary()
    assert [s.sequence_name for s in summaries] == ["Main"]
    steps = summaries[0].steps
    assert [s.step_name for s in steps] == ["Only wait", "Cool down"]
    real = recipe.sequences["Main"]
    assert [s.step_id for s in steps] == [step.id for step in real.steps + real.teardown_steps]


def test_the_python_demo_recipe_parses_and_knows_its_folder():
    """resources/recipes/python_demo.yml is the PythonModuleStep showcase; its
    `module:` entries resolve against base_dir, which from_file must set."""
    demo = Path(__file__).parents[2] / "resources" / "recipes" / "python_demo.yml"
    recipe = Recipe.from_file(str(demo))

    assert recipe.name == "Python demo"
    assert [step.name for step in recipe.sequences["Main"].steps] == [
        "Add numbers",
        "Measure voltage",
        "Settle",
        "Even check (fails on purpose)",
        "Greet the operator",
    ]
    assert recipe.base_dir == str(demo.resolve().parent)


def test_ignored_legacy_header_keys_are_tolerated():
    """continue_on_error and recipe_version appear in 4 of 5 example recipes;
    nothing reads them (F1, F2). Tolerated so old files load; roadmap TODO."""
    text = VALID.replace(
        "version: 1.0.0", "version: 1.0.0\nrecipe_version: 1.0.0\ncontinue_on_error: true"
    )
    recipe = Recipe.from_yaml_text(text)
    assert recipe.name == "Wait demo"


def test_invalid_recipe_never_reaches_the_sequencer(tmp_path):
    """Validation gates execution: CORE refuses the file, reports the error to
    the operator, and sends the Sequencer nothing at all."""
    from test_core import build_core_that_spawns_nothing

    from pypts.messages.core_hmi_communication import LoadRecipe, ModuleErrorReported

    broken_file = tmp_path / "broken.yml"
    broken_file.write_text("name: No header fields\n", encoding="utf-8")
    core = build_core_that_spawns_nothing()

    core.from_hmi.send(LoadRecipe(recipe_path=str(broken_file)))
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == []
    to_hmi = list(core.to_hmi.receive())
    assert len(to_hmi) == 1
    assert isinstance(to_hmi[0], ModuleErrorReported)
    assert "description" in to_hmi[0].error.message
    assert core.recipe is None


@pytest.mark.skip(
    reason="the example recipes use nine steptypes that are not ported yet - "
    "unskip as the registry grows (roadmap Phase 1)"
)
def test_every_example_recipe_in_resources_parses():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_recipe_format_version_is_checked():
    """Open roadmap item: add format_version to the header before third party plugins ship."""
