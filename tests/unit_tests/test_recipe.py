# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Recipe module (src/pypts/recipe/).

The layer under test is pure data: parse a multi-document YAML file into
Recipe -> Sequence -> Step objects, refuse anything malformed, execute
nothing. The format rules live in rules.py (required fields, optional
fields and their defaults), the validator checks them, and the parser
raises one RecipeError naming every problem at once - so CORE has exactly
one type to catch, and every one of the old loader's silent mistakes
(skipped unnamed sequences, last-wins duplicates) is a loud error here.

The fixture is data/wait_recipe.yml - the smallest recipe that runs.
"""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from pypts.recipe.recipe import Recipe, RecipeError, Sequence
from pypts.recipe.rules import RECIPE_FORMAT_VERSION
from pypts.step.wait_step import WaitStep

WAIT_RECIPE = Path(__file__).parent / "data" / "wait_recipe.yml"

PLACEHOLDER = "placeholder - test not implemented yet"

#: A minimal, valid recipe as text, so a test can break one thing at a time.
#: Every optional field is left out - the parser assumes the defaults.
VALID = """\
name: Wait demo
main_sequence: Main
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Only wait
    wait_time: '0.01'
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
        "steps:\n",
        """\
setup_steps:
  - steptype: Wait
    step_name: Warm up
    wait_time: '0'
steps:
""",
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


def test_the_only_required_header_field_is_name():
    broken = "\n".join(line for line in VALID.splitlines() if not line.startswith("name:"))
    with pytest.raises(RecipeError, match="name"):
        Recipe.from_yaml_text(broken)


def test_optional_header_fields_get_their_defaults():
    """VALID carries no description, version or globals - the rules fill them in."""
    recipe = Recipe.from_yaml_text(VALID)
    assert recipe.description == ""
    assert recipe.version == ""
    assert recipe.globals == {}


def test_optional_sequence_fields_get_their_defaults():
    main = Recipe.from_yaml_text(VALID).sequences["Main"]
    assert main.description == ""
    assert main.parameters == {}
    assert main.locals == {}
    assert main.outputs == {}
    assert main.teardown_steps == []


def test_an_optional_key_written_without_a_value_counts_as_absent():
    """YAML reads a bare `locals:` line as None - that means the default, not None."""
    text = VALID.replace("sequence_name: Main", "sequence_name: Main\nlocals:")
    main = Recipe.from_yaml_text(text).sequences["Main"]
    assert main.locals == {}


def test_an_omitted_main_sequence_means_the_first_sequence_in_the_file():
    text = "\n".join(
        line for line in VALID.splitlines() if not line.startswith("main_sequence:")
    )
    recipe = Recipe.from_yaml_text(text)
    assert recipe.main_sequence == "Main"


def test_the_recipe_language_is_case_insensitive():
    """Keys and structural values may be spelled in any case."""
    text = """\
NAME: Wait demo
Main_Sequence: MAIN
---
Sequence_Name: Main
STEPS:
  - StepType: WAIT
    Step_Name: Only wait
    Wait_Time: '0.01'
"""
    recipe = Recipe.from_yaml_text(text)
    assert recipe.name == "Wait demo"
    assert recipe.main_sequence == "Main"
    assert [step.name for step in recipe.sequences["Main"].steps] == ["Only wait"]


def test_mapping_configs_are_case_insensitive_but_entry_names_keep_theirs():
    """`Type: EQUALS` is fine; entry names become keyword arguments and output
    keys, so they are the user's case-sensitive namespace."""
    text = """\
name: Demo
---
sequence_name: Main
steps:
  - steptype: PythonModule
    step_name: Add
    module: example_tests.py
    method_name: add
    Input_Mapping:
      a: {Value: 2}
      B: {value: 3}
    Output_Mapping:
      sum: {Type: EQUALS, value: 5}
"""
    step = Recipe.from_yaml_text(text).sequences["Main"].steps[0]
    assert step.input_mapping == {"a": {"value": 2}, "B": {"value": 3}}
    assert step.output_mapping == {"sum": {"type": "equals", "value": 5}}


def test_sequence_names_differing_only_by_case_are_duplicates():
    """main_sequence finds its sequence case-insensitively, so names that
    collide without case would make the lookup ambiguous."""
    header, sequence = VALID.split("---")
    doubled = (
        header
        + "---"
        + sequence
        + "---"
        + sequence.replace("sequence_name: Main", "sequence_name: MAIN")
    )
    with pytest.raises(RecipeError, match="duplicate"):
        Recipe.from_yaml_text(doubled)


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


def test_a_recipe_without_sequences_is_refused():
    header = VALID.split("---")[0]
    with pytest.raises(RecipeError, match="no sequence"):
        Recipe.from_yaml_text(header)


def test_a_missing_main_sequence_is_refused():
    broken = VALID.replace("main_sequence: Main", "main_sequence: Missing")
    with pytest.raises(RecipeError, match="Missing"):
        Recipe.from_yaml_text(broken)


def test_an_unknown_steptype_names_itself_and_the_sequence():
    broken = VALID.replace("steptype: Wait", "steptype: PythonModul")
    with pytest.raises(RecipeError, match="PythonModul") as excinfo:
        Recipe.from_yaml_text(broken)
    assert "Main" in str(excinfo.value)


def test_an_unknown_step_key_is_refused_with_context():
    """Every YAML key is a constructor argument, so a typo fails at load time."""
    broken = VALID.replace("step_name: Only wait", "step_name: Only wait\n    stepp_skip: true")
    with pytest.raises(RecipeError, match=r"Only wait|Main"):
        Recipe.from_yaml_text(broken)


def test_a_sequence_missing_its_steps_is_refused():
    broken = VALID.split("---")[0] + "---\nsequence_name: Main\n"
    with pytest.raises(RecipeError, match="steps"):
        Recipe.from_yaml_text(broken)


def test_a_sequence_with_an_empty_step_list_is_refused():
    """A sequence exists to run something - `steps: []` is not a sequence."""
    broken = VALID.split("---")[0] + "---\nsequence_name: Main\nsteps: []\n"
    with pytest.raises(RecipeError, match="at least one step"):
        Recipe.from_yaml_text(broken)


def test_steptype_specific_required_fields_are_enforced():
    """rules.STEP_TYPE_REQUIRED: a Wait needs wait_time, a PythonModule
    needs module and method_name."""
    broken = VALID.replace("    wait_time: '0.01'\n", "")
    with pytest.raises(RecipeError, match="wait_time"):
        Recipe.from_yaml_text(broken)

    broken = VALID.replace(
        "  - steptype: Wait\n    step_name: Only wait\n    wait_time: '0.01'\n",
        "  - steptype: PythonModule\n    step_name: No module\n",
    )
    with pytest.raises(RecipeError, match="module") as excinfo:
        Recipe.from_yaml_text(broken)
    assert "method_name" in str(excinfo.value)


def test_every_problem_is_reported_in_one_error():
    """The validator collects; the user fixes the file in one round trip."""
    broken = "\n".join(
        line
        for line in VALID.splitlines()
        if not line.startswith("name:") and "wait_time" not in line
    )
    with pytest.raises(RecipeError) as excinfo:
        Recipe.from_yaml_text(broken)
    message = str(excinfo.value)
    assert "name" in message
    assert "wait_time" in message


def test_to_summary_covers_every_step_that_will_emit_events():
    """The summary is what pre-fills a frontend's step table, and teardown
    steps emit StepStarted/StepFinished too - so they must have rows."""
    text = (
        VALID
        + """\
teardown_steps:
  - steptype: Wait
    step_name: Cool down
    wait_time: '0'
"""
    )
    recipe = Recipe.from_yaml_text(text)

    summaries = recipe.to_summary()
    assert [s.sequence_name for s in summaries] == ["Main"]
    steps = summaries[0].steps
    assert [s.step_name for s in steps] == ["Only wait", "Cool down"]
    real = recipe.sequences["Main"]
    assert [s.step_id for s in steps] == [step.id for step in real.steps + real.teardown_steps]


def test_the_python_demo_recipe_parses_and_knows_its_folder():
    """resources/recipes/python_demo.yml is the PythonModule showcase and the
    reference for the simplified format; its `module:` entries resolve
    against base_dir, which from_file must set."""
    demo = Path(__file__).parents[2] / "resources" / "recipes" / "python_demo.yml"
    recipe = Recipe.from_file(str(demo))

    assert recipe.name == "Python demo"
    # The demo omits main_sequence - the first sequence is the one.
    assert recipe.main_sequence == "Main"
    assert [step.name for step in recipe.sequences["Main"].steps] == [
        "Add numbers",
        "Measure voltage",
        "Settle",
        "Even check (fails on purpose)",
        "Greet the operator",
    ]
    assert recipe.base_dir == str(demo.resolve().parent)


def test_the_basic_scenario_recipe_parses():
    """resources/recipes/basic_scenario.yml is the all-green showcase: a setup
    step, a step-to-step local, a wait, and a teardown that always runs."""
    demo = Path(__file__).parents[2] / "resources" / "recipes" / "basic_scenario.yml"
    recipe = Recipe.from_file(str(demo))

    main = recipe.sequences["Main"]
    assert [step.name for step in main.steps] == [
        "Greet the operator",
        "Measure voltage",
        "Add numbers",
        "Settle",
        "Check the sum is even",
    ]
    assert [step.name for step in main.teardown_steps] == ["Cool down"]
    assert recipe.globals == {"operator_name": "operator"}


def test_unknown_header_keys_are_tolerated():
    """continue_on_error and recipe_version appear in old example recipes;
    nothing reads them (F1, F2). Tolerated so old files load; roadmap TODO."""
    text = VALID.replace(
        "name: Wait demo", "name: Wait demo\nrecipe_version: 1.0.0\ncontinue_on_error: true"
    )
    recipe = Recipe.from_yaml_text(text)
    assert recipe.name == "Wait demo"


def test_invalid_recipe_never_reaches_the_sequencer(tmp_path):
    """Validation gates execution: CORE refuses the file, reports the error to
    the operator, and sends the Sequencer nothing at all."""
    from test_core import build_core_that_spawns_nothing

    from pypts.messages.core_hmi_communication import LoadRecipe, ModuleErrorReported

    broken_file = tmp_path / "broken.yml"
    broken_file.write_text("description: a recipe with no name\n", encoding="utf-8")
    core = build_core_that_spawns_nothing()

    core.from_hmi.send(LoadRecipe(recipe_path=str(broken_file)))
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == []
    to_hmi = list(core.to_hmi.receive())
    assert len(to_hmi) == 1
    assert isinstance(to_hmi[0], ModuleErrorReported)
    assert "name" in to_hmi[0].error.message
    assert core.recipe is None


@pytest.mark.skip(
    reason="the example recipes use nine steptypes that are not ported yet - "
    "unskip as the registry grows (roadmap Phase 1)"
)
def test_every_example_recipe_in_resources_parses():
    ...


def test_a_format_version_mismatch_is_logged_but_the_recipe_still_loads(caplog):
    """Warn-only for the duration of the refactor: a recipe written for another
    format is an ERROR in the log, not a refusal. The hard refusal comes with
    the compatibility policy, ~v1.0 (roadmap)."""
    text = VALID.replace("name: Wait demo", "name: Wait demo\nformat_version: 9.9.9")
    with caplog.at_level(logging.ERROR):
        recipe = Recipe.from_yaml_text(text)

    assert recipe.name == "Wait demo"
    complaints = [r.getMessage() for r in caplog.records if "format_version" in r.getMessage()]
    assert len(complaints) == 1
    assert "9.9.9" in complaints[0]
    assert RECIPE_FORMAT_VERSION in complaints[0]


def test_a_matching_or_absent_format_version_is_silent(caplog):
    """Absent means "written for the current format" - nothing to say."""
    matching = VALID.replace(
        "name: Wait demo", f"name: Wait demo\nformat_version: {RECIPE_FORMAT_VERSION}"
    )
    with caplog.at_level(logging.ERROR):
        Recipe.from_yaml_text(VALID)
        Recipe.from_yaml_text(matching)

    assert not [r for r in caplog.records if "format_version" in r.getMessage()]
