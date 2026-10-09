"""
The Recipe Creator's verificator checks a recipe with the framework's own rules.

Its errors come from the same Pydantic models the framework loads a recipe with
(pypts.recipe.recipe_schema), and once those pass from the framework's real
load, so a recipe verifies clean exactly when the framework would take it. What
the verificator adds is for the editor: a line for every issue, a hint on how to
fix it, and warnings about what loads but looks wrong.
"""

import logging
from pathlib import Path

import pytest

from pypts.helper_applications.recipe_creator import verify_string
from pypts.recipe.recipe import Recipe, RecipeError

ROOT = Path(__file__).parents[2]
SHIPPED_RECIPES = sorted(
    [
        *(ROOT / "resources" / "recipes" / "Development_recipes").glob("*.yml"),
        *(Path(__file__).parent / "data").glob("*.yml"),
    ]
)

VALID = """\
name: Demo
version: '0.2'
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Pause
    wait_time: 1
"""


def errors(text: str) -> list:
    return [issue for issue in verify_string(text) if issue.is_error]


def warnings(text: str) -> list:
    return [issue for issue in verify_string(text) if issue.is_warning]


def framework_refusal(text: str) -> str:
    """What the framework says when it refuses the recipe; "" when it loads it."""
    try:
        Recipe.from_yaml_text(text)
    except RecipeError as error:
        return str(error)
    return ""


def with_step(extra: str) -> str:
    """VALID with lines added to its one step."""
    return VALID + extra


# -- the verdict is the framework's ------------------------------------------------


@pytest.mark.parametrize("path", SHIPPED_RECIPES, ids=lambda path: path.name)
def test_a_recipe_the_framework_loads_verifies_without_errors(path):
    text = path.read_text(encoding="utf-8")
    if framework_refusal(text):
        pytest.skip("a deliberately broken fixture")
    assert errors(text) == []


#: Recipes the framework refuses, each for a different reason - at validation,
#: and at build time, where only the full load notices.
REFUSED = {
    "wait_time missing": VALID.replace("    wait_time: 1\n", ""),
    "typo in a step key": with_step("    skipp: true\n"),
    "a text field written as a YAML boolean": VALID.replace(
        "step_name: Pause", "step_name: Pause\n    description: yes"
    ),
    "an unknown output type": with_step("    outputs:\n      r: {type: local}\n"),
    "a range without max": with_step("    outputs:\n      r: {type: range, min: 1}\n"),
    "report_metadata naming a number": VALID.replace(
        "name: Demo", "name: Demo\nreport_metadata: [3]"
    ),
    "select is neither file nor folder": VALID
    + "  - steptype: UserLoading\n    step_name: pick\n    message: m\n    select: directory\n",
    "an empty method_name": VALID
    + "  - steptype: PythonModule\n    step_name: p\n    module: m.py\n    method_name: ''\n",
    "a call of a sequence that does not exist": VALID
    + "  - steptype: Sequence\n    sequence_name: Nope\n",
    "empty options": VALID
    + "  - steptype: UserInteraction\n    step_name: q\n    message: m\n    options: []\n",
    "a call of the main sequence": VALID + "  - steptype: Sequence\n    sequence_name: Main\n",
    "main_sequence names nothing": VALID.replace("name: Demo", "name: Demo\nmain_sequence: Nope"),
}


@pytest.mark.parametrize("text", REFUSED.values(), ids=list(REFUSED))
def test_a_recipe_the_framework_refuses_does_not_verify_clean(text):
    assert framework_refusal(text)
    assert errors(text) != []


# -- an error says what the framework says, where it is ----------------------------


def test_an_error_reads_as_the_framework_s_problem():
    text = REFUSED["wait_time missing"]
    (issue,) = errors(text)
    assert issue.field == "sequence 'Main', steps[1] 'Pause'"
    assert issue.message == "wait_time: Field required"
    assert f"{issue.field}: {issue.message}" in framework_refusal(text)


def test_a_missing_field_points_at_its_step():
    (issue,) = errors(REFUSED["wait_time missing"])
    assert issue.line == 6  # `  - steptype: Wait`


def test_a_wrong_key_points_at_itself():
    (issue,) = errors(REFUSED["typo in a step key"])
    assert issue.line == 9
    assert issue.message == "skipp: Extra inputs are not permitted"


def test_a_template_field_points_into_the_template():
    text = """\
name: Demo
version: '0.2'
---
sequence_name: Main
steps:
  - steptype: Indexed
    step_name: Add
    template:
      steptype: PythonModule
      module: m.py
      method_name: [add]
    parameter_sets:
      - inputs: {a: 1}
"""
    (issue,) = errors(text)
    assert issue.line == 11
    assert issue.message == "template -> method_name: Input should be a valid string"


def test_a_build_time_refusal_is_an_error_with_the_framework_s_words():
    text = REFUSED["select is neither file nor folder"]
    (issue,) = errors(text)
    assert "'select' must be 'file' or 'folder'" in issue.message
    assert issue.message in framework_refusal(text)


def test_every_validation_problem_is_reported_at_once():
    text = REFUSED["wait_time missing"].replace("version: '0.2'\n", "")
    messages = sorted(issue.message for issue in errors(text))
    assert messages == ["version: Field required", "wait_time: Field required"]


# -- hints stay ---------------------------------------------------------------------


def test_a_missing_step_field_keeps_its_hint():
    (issue,) = errors(REFUSED["wait_time missing"])
    assert "Example:  wait_time: 2" in issue.hint


def test_an_unknown_key_hint_lists_the_keys_the_step_takes():
    (issue,) = errors(REFUSED["typo in a step key"])
    assert "skip" in issue.hint
    assert "wait_time" in issue.hint


def test_an_unknown_steptype_keeps_its_rename_hint():
    (issue,) = errors(VALID.replace("steptype: Wait", "steptype: WaitStep"))
    assert "'waitstep' was renamed or removed" in issue.hint


def test_a_missing_output_key_keeps_its_hint():
    (issue,) = errors(REFUSED["a range without max"])
    assert "A 'range' output needs both 'min' and 'max'" in issue.hint


INDEXED = """\
name: Demo
version: '0.2'
---
sequence_name: Main
steps:
  - steptype: Indexed
    step_name: Add
    template:
      steptype: PythonModule
      module: m.py
      method_name: add
    parameter_sets:
      - inputs: {a: 1}
"""


def test_a_parameter_set_problem_gets_the_parameter_set_hint():
    """'Extra inputs are not permitted' names inputs, but it is not about them."""
    (issue,) = errors(INDEXED.replace("- inputs: {a: 1}", "- foo: 1"))
    assert "Each entry in 'parameter_sets'" in issue.hint


def test_a_missing_template_gets_the_template_hint():
    text = INDEXED.replace(
        "    template:\n      steptype: PythonModule\n      module: m.py\n      method_name: add\n",
        "",
    )
    (issue,) = errors(text)
    assert "An Indexed step needs 'template'" in issue.hint


def test_a_template_with_an_unknown_steptype_gets_the_steptype_hint():
    (issue,) = errors(INDEXED.replace("steptype: PythonModule", "steptype: Nope"))
    assert "Available step types" in issue.hint


def test_report_metadata_naming_a_number_is_not_told_to_quote_text():
    (issue,) = errors(REFUSED["report_metadata naming a number"])
    assert "report_metadata: [serial_number" in issue.hint
    assert "quote" not in issue.hint


def test_a_duplicate_sequence_name_points_at_the_duplicate():
    second = "---\nsequence_name: main\nsteps:\n  - {steptype: Wait, step_name: P, wait_time: 1}\n"
    (issue,) = errors(VALID + second)
    assert issue.message == "Duplicate sequence name 'main'."
    assert issue.line == 10


def test_a_main_sequence_naming_nothing_points_at_main_sequence():
    (issue,) = errors(REFUSED["main_sequence names nothing"])
    assert issue.line == 2


def test_a_numeric_output_name_is_a_name_not_a_position():
    (issue,) = errors(with_step("    outputs:\n      1: {type: equals}\n"))
    assert issue.message == "outputs -> 1 -> value: Field required"
    assert issue.line == 10


def test_a_first_document_that_is_not_a_mapping_is_the_header_s_problem():
    """The framework stops there; the next mapping is not taken for the header."""
    text = "- a\n- b\n---\n" + VALID.split("---\n")[1]
    (issue,) = errors(text)
    assert issue.field == "document 1"
    assert issue.line == 1


def test_a_document_label_counts_from_one():
    text = VALID + "---\n- a\n"
    (issue,) = errors(text)
    assert issue.field == "document 3"
    assert issue.message == "Document 3 is not a YAML mapping."


# -- warnings are for what loads -----------------------------------------------------


def test_a_removed_sequence_key_is_a_warning_and_the_recipe_loads():
    text = VALID.replace("steps:", "locals: {}\nsteps:")
    assert framework_refusal(text) == ""
    assert errors(text) == []
    assert [issue.field for issue in warnings(text)] == ["sequence 'Main'.locals"]


def test_a_version_written_as_a_number_is_a_warning():
    text = VALID.replace("version: '0.2'", "version: 0.2")
    assert errors(text) == []
    assert [issue.field for issue in warnings(text)] == ["header.version"]


# -- shapes the editor must survive ---------------------------------------------------


def test_a_self_referencing_anchor_does_not_crash_the_check():
    """YAML allows an alias inside its own anchor; the framework loads it, and
    the Creator verifies on every keystroke - it must answer, not recurse."""
    text = VALID.replace("version: '0.2'", "version: '0.2'\nglobals:\n  g: &a [*a]")
    assert framework_refusal(text) == ""
    assert errors(text) == []


def test_main_sequence_may_name_a_sequence_written_as_a_number():
    text = (
        VALID.replace("name: Demo", "name: Demo\nmain_sequence: '123'")
        + "---\nsequence_name: 123\nsteps:\n  - {steptype: Wait, step_name: P, wait_time: 1}\n"
    )
    assert framework_refusal(text) == ""
    assert errors(text) == []


# -- verifying is not loading --------------------------------------------------------


def test_verifying_logs_nothing_at_warning_or_above(caplog):
    """The Creator verifies on every keystroke; a version mismatch is the
    framework's to log when it really loads the recipe."""
    text = VALID.replace("version: '0.2'", "version: '0.1'")
    with caplog.at_level(logging.WARNING):
        verify_string(text)
    assert caplog.records == []
