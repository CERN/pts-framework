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
import yaml

from pypts.recipe import step_source
from pypts.recipe.recipe import Recipe, RecipeError, Sequence
from pypts.recipe.rules import RECIPE_FORMAT_VERSION
from pypts.step.python_module_step import PythonModuleStep
from pypts.step.wait_step import WaitStep

WAIT_RECIPE = Path(__file__).parent / "data" / "wait_recipe.yml"
DEMOS = Path(__file__).parents[2] / "resources" / "recipes" / "Development_recipes"
PYTHONMODULE_DEMO = DEMOS / "pythonmodulestep_demo.yml"
INDEXED_DEMO = DEMOS / "indexedstep_demo.yml"
USER_INTERACTION_DEMO = DEMOS / "userinteractionstep_demo.yml"
ALL_STEPTYPES_DEMO = DEMOS / "all_steptypes_demo.yml"

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


def test_the_pythonmodule_demo_recipe_parses_and_knows_its_folder():
    """resources/recipes/Development_recipes/pythonmodulestep_demo.yml is the PythonModule
    showcase and the reference for the simplified format; its `module:`
    entries resolve against base_dir, which from_file must set."""
    recipe = Recipe.from_file(str(PYTHONMODULE_DEMO))

    assert recipe.name == "PythonModule demo"
    # The demo omits main_sequence - the first sequence is the one.
    assert recipe.main_sequence == "Main"
    names = [step.name for step in recipe.sequences["Main"].steps]
    assert names == [
        "Add numbers",
        "Measure voltage",
        "Even check (fails on purpose)",
        "Greet the operator",
    ]
    assert recipe.base_dir == str(PYTHONMODULE_DEMO.resolve().parent)


def test_the_indexed_demo_recipe_expands_every_parameter_set():
    """resources/recipes/Development_recipes/indexedstep_demo.yml is the Indexed showcase: two
    authored steps, thirteen real ones, each named after its own parameters
    and none of them an Indexed step by the time the Sequencer sees it."""
    recipe = Recipe.from_file(str(INDEXED_DEMO))

    steps = recipe.sequences["Main"].steps
    assert [step.name for step in steps] == [
        "Add numbers [a=1, b=1]",
        "Add numbers [a=2, b=3]",
        "Add numbers [a=10, b=5]",
        "Add numbers [a=0, b=0]",
        "Add numbers [a=-4, b=4]",
        "Add numbers [a=100, b=250]",
        "Add numbers [a=7, b=8]",
        "Add numbers [a=-6, b=-9]",
        "Add numbers [a=1.5, b=2.5]",
        "Add numbers [a=6, b=7]",
        "Even check [number=2]",
        "Even check [number=4]",
        "Even check [number=7]",
    ]
    assert all(isinstance(step, PythonModuleStep) for step in steps)
    # The template's shared output_mapping reached every generated step.
    assert steps[-1].output_mapping == {"even": {"type": "passfail"}}


def test_the_user_interaction_demo_recipe_parses():
    """resources/recipes/Development_recipes/userinteractionstep_demo.yml is the UserInteraction
    showcase; the last step reads back the answer the third one stored."""
    recipe = Recipe.from_file(str(USER_INTERACTION_DEMO))

    steps = recipe.sequences["Main"].steps
    assert [step.name for step in steps] == [
        "Check the indicator",
        "Connect the DUT",
        "Which port",
        "Report the port",
    ]
    assert steps[2].output_mapping == {"output": {"type": "local", "local_name": "port"}}
    assert steps[3].input_mapping == {"name": {"type": "local", "local_name": "port"}}


def test_the_all_steptypes_demo_recipe_builds_one_of_everything():
    """resources/recipes/Development_recipes/all_steptypes_demo.yml is the single run that
    exercises every steptype - the one to reach for when testing the engine
    rather than one type."""
    recipe = Recipe.from_file(str(ALL_STEPTYPES_DEMO))

    sequence = recipe.sequences["Main"]
    built = {type(step).__name__ for step in sequence.steps}
    assert built == {"UserInteractionStep", "WaitStep", "PythonModuleStep"}
    # Indexed is gone by build time: five sets became five ordinary steps.
    assert sum(step.name.startswith("Add numbers [") for step in sequence.steps) == 5
    assert [step.name for step in sequence.teardown_steps] == ["Power down"]


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


# --------------------------------------------------------------------------
# Indexed steps - expanded while the recipe loads
# --------------------------------------------------------------------------

#: Two parameter sets, the terse spelling indexedstep_demo.yml uses.
INDEXED = """\
name: Indexed demo
---
sequence_name: Main
steps:
  - steptype: Indexed
    step_name: Add numbers
    description: Additions with their own expected sums.
    template:
      steptype: PythonModule
      module: example_tests.py
      method_name: add
    parameter_sets:
      - inputs: {a: 1, b: 1}
        expect: {sum: 2}
      - inputs: {a: 2, b: 3}
        expect: {sum: 5}
"""


def test_an_indexed_step_is_expanded_into_real_steps_at_load_time():
    """Nothing loops at run time: the recipe holds N ordinary steps, and the
    Indexed steptype is gone before anything is built."""
    recipe = Recipe.from_yaml_text(INDEXED)

    steps = recipe.sequences["Main"].steps
    assert [step.name for step in steps] == [
        "Add numbers [a=1, b=1]",
        "Add numbers [a=2, b=3]",
    ]
    assert [step.input_mapping["a"]["value"] for step in steps] == [1, 2]
    assert [step.output_mapping["sum"]["value"] for step in steps] == [2, 5]


def test_continue_on_error_on_the_wrapper_reaches_every_generated_step():
    """"Do not continue past this indexed step" can only be said on the wrapper,
    so it carries to every row - the same way `skip` does."""
    text = INDEXED.replace(
        "    step_name: Add numbers\n", "    step_name: Add numbers\n    continue_on_error: false\n"
    )
    steps = Recipe.from_yaml_text(text).sequences["Main"].steps

    assert len(steps) == 2
    assert [step.continue_on_error for step in steps] == [False, False]


def test_a_step_defaults_to_continuing_past_its_own_error():
    """Unstated in the recipe means True: one bad step does not decide for the
    other nineteen."""
    step = Recipe.from_yaml_text(VALID).sequences["Main"].steps[0]
    assert step.continue_on_error is True


def test_the_dropped_critical_field_is_refused_by_name():
    """`critical` was the old per-step override of a run-wide continue_on_error
    (recipe_guide 9.2). With the flag itself per-step it says the same thing
    twice, so it is gone - and a recipe still spelling it must be told, not
    silently ignored the way the old engine ignored header-level settings."""
    text = VALID.replace("    wait_time: '0.01'\n", "    wait_time: '0.01'\n    critical: true\n")

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "critical" in str(error.value)
    assert "Only wait" in str(error.value)


def test_generated_steps_have_ids_of_their_own():
    """The step table is keyed by step id, so N rows need N ids."""
    steps = Recipe.from_yaml_text(INDEXED).sequences["Main"].steps

    assert len({step.id for step in steps}) == len(steps)


def test_an_indexed_step_pre_fills_one_table_row_per_set():
    """What a frontend receives in RecipeLoaded - no frontend knows the
    steptype exists, it just gets more rows."""
    recipe = Recipe.from_yaml_text(INDEXED)

    rows = recipe.to_summary()[0].steps
    assert [row.step_name for row in rows] == [
        "Add numbers [a=1, b=1]",
        "Add numbers [a=2, b=3]",
    ]


def test_an_indexed_step_without_its_own_keys_is_refused_with_context():
    text = INDEXED.replace("    parameter_sets:\n", "    other_key:\n")

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "parameter_sets" in str(error.value)
    assert "Main" in str(error.value)


def test_a_broken_template_is_reported_before_anything_is_built():
    """The template is checked as the step it will become."""
    text = INDEXED.replace("      method_name: add\n", "")

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "template" in str(error.value)
    assert "method_name" in str(error.value)


def test_the_indexed_keys_are_case_insensitive_but_parameter_names_are_not():
    """The recipe's own language is case-insensitive; argument names are
    Python keyword arguments and must survive exactly as written."""
    text = INDEXED.replace("    template:", "    TEMPLATE:").replace(
        "      - inputs: {a: 1, b: 1}", "      - INPUTS: {a: 1, B: 1}"
    )
    recipe = Recipe.from_yaml_text(text)

    first = recipe.sequences["Main"].steps[0]
    assert set(first.input_mapping) == {"a", "B"}


# --- step_source.py: the YAML fragment behind each step table row -------------
#
# What the GUI's hover panel shows. The contract that matters is the *order*:
# one fragment per row of the step table, which is `steps + teardown_steps`
# with every Indexed step already expanded - exactly what to_summary() emits.


def test_one_yaml_fragment_per_step_table_row(tmp_path):
    """The fragments line up with to_summary(), teardown steps included."""
    text = (
        VALID
        + """\
teardown_steps:
  - steptype: Wait
    step_name: Cool down
    wait_time: '0'
"""
    )
    path = tmp_path / "recipe.yml"
    path.write_text(text, encoding="utf-8")

    fragments = step_source.step_yaml_by_sequence(str(path))
    rows = Recipe.from_yaml_text(text).to_summary()[0].steps

    assert list(fragments) == ["Main"]
    assert len(fragments["Main"]) == len(rows)
    assert "Only wait" in fragments["Main"][0]
    assert "Cool down" in fragments["Main"][1]


def test_setup_steps_come_before_the_authored_steps(tmp_path):
    """_build_sequence() runs setup_steps first; the fragments must agree."""
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
    path = tmp_path / "recipe.yml"
    path.write_text(text, encoding="utf-8")

    fragments = step_source.step_yaml_by_sequence(str(path))["Main"]
    rows = Recipe.from_yaml_text(text).to_summary()[0].steps

    assert [row.step_name for row in rows] == ["Warm up", "Only wait"]
    assert "Warm up" in fragments[0]
    assert "Only wait" in fragments[1]


def test_each_expanded_indexed_row_gets_its_own_fragment(tmp_path):
    """The whole reason the fragment is the effective mapping and not a slice
    of the file: the generated steps exist in no file, and the ten rows of an
    Indexed step must not all show the same block."""
    path = tmp_path / "recipe.yml"
    path.write_text(INDEXED, encoding="utf-8")

    fragments = step_source.step_yaml_by_sequence(str(path))["Main"]

    assert len(fragments) == 2
    assert fragments[0] != fragments[1]
    first = yaml.safe_load(fragments[0])
    second = yaml.safe_load(fragments[1])
    assert first["input_mapping"]["a"] == {"type": "direct", "value": 1}
    assert second["input_mapping"]["a"] == {"type": "direct", "value": 2}
    assert first["output_mapping"]["sum"] == {"type": "equals", "value": 2}
    assert second["output_mapping"]["sum"] == {"type": "equals", "value": 5}

    # `Indexed` itself never reaches a row: what is shown is what will run.
    # The steptype keeps the case the template wrote - only keys are lowercased.
    assert first["steptype"] == "PythonModule"


def test_a_fragment_is_valid_yaml_that_round_trips(tmp_path):
    path = tmp_path / "recipe.yml"
    path.write_text(VALID, encoding="utf-8")

    fragment = step_source.step_yaml_by_sequence(str(path))["Main"][0]

    assert yaml.safe_load(fragment) == {
        "steptype": "Wait",
        "step_name": "Only wait",
        "wait_time": "0.01",
    }


def test_a_recipe_that_cannot_be_read_costs_only_the_fragments(tmp_path):
    """A convenience view is never a reason a recipe fails to display."""
    missing = tmp_path / "not_here.yml"
    broken = tmp_path / "broken.yml"
    broken.write_text("name: Broken\n---\n  - this: is not a mapping\n", encoding="utf-8")

    assert step_source.step_yaml_by_sequence(str(missing)) == {}
    assert step_source.step_yaml_by_sequence(str(broken)) == {}


def test_the_all_steptypes_demo_recipe_has_a_fragment_for_every_row():
    """The everything recipe end to end - five of its rows come from one
    Indexed step and exist in no file, so this is the real test of the
    ordering contract."""
    fragments = step_source.step_yaml_by_sequence(str(ALL_STEPTYPES_DEMO))
    recipe = Recipe.from_file(str(ALL_STEPTYPES_DEMO))

    for summary in recipe.to_summary():
        rendered = fragments[summary.sequence_name]
        assert len(rendered) == len(summary.steps)
        for row, fragment in zip(summary.steps, rendered, strict=True):
            assert yaml.safe_load(fragment)["step_name"] == row.step_name
