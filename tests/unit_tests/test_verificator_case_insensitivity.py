# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The verificator and the framework must agree about case.

The recipe language is case-insensitive: `recipe_parser.normalize_header` and
`normalize_sequence` lowercase every mapping key before anything is validated,
so `Step_Name:` loads and runs exactly as `step_name:` does. The Recipe
Creator's verificator used to be a second, independent implementation that
read raw keys - so a recipe the framework ran happily was reported broken. It
now validates with the framework's own models; these tests still pin the two.

These tests pin the two halves together at the only place that matters: the
verdict. A recipe the framework accepts must verify clean, and a recipe the
framework refuses must not.

Line numbers get their own test. Lowercasing the documents without lowercasing
the line map is a silent half-fix: every verdict comes out right and every
issue loses its line, which empties the Recipe Creator's error gutter.
"""

import pytest

from pypts.helper_applications.recipe_creator import verify_string
from pypts.recipe.recipe import Recipe, RecipeError


def errors(text: str) -> list[str]:
    """The error messages only - warnings are advice, not a verdict."""
    return [str(issue) for issue in verify_string(text) if issue.is_error]


def framework_accepts(text: str) -> bool:
    """Whether the real load path takes this recipe. The reference answer."""
    try:
        Recipe.from_yaml_text(text, file_name="test.yml")
    except RecipeError:
        return False
    return True


#: The same recipe twice: once in the canonical lower case, once with every
#: key of the recipe's own language in a different case. The framework reads
#: them identically, so the verificator must too.
LOWER_CASE = """\
name: Case demo
version: 0.2
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: First wait
    wait_time: '0.5'
"""

MIXED_CASE = """\
Name: Case demo
Version: 0.2
---
Sequence_Name: Main
Steps:
  - Steptype: Wait
    Step_Name: First wait
    Wait_Time: '0.5'
"""


def test_the_framework_accepts_both_spellings():
    """The premise. If this fails the rest of the file is measuring nothing."""
    assert framework_accepts(LOWER_CASE)
    assert framework_accepts(MIXED_CASE)


def test_lower_case_recipe_verifies_clean():
    assert errors(LOWER_CASE) == []


def test_mixed_case_recipe_verifies_clean():
    """A1/A2: raw-key reads reported missing fields that were plainly there."""
    assert errors(MIXED_CASE) == []


def test_mixed_case_keys_are_not_reported_as_unknown():
    """
    A1's second half: the unknown-key check tested raw keys against rules.py's
    lowercase sets, so one mixed-case key produced two wrong messages at once -
    a missing-field error and an unknown-key warning.
    """
    unknown = [
        str(issue)
        for issue in verify_string(MIXED_CASE)
        if "unknown key" in str(issue).lower()
    ]
    assert unknown == []


def test_mixed_case_header_is_identified_as_a_header():
    """
    A2: `"name" in header_doc` is a raw-key test, so a header written `Name:`
    was rejected as 'not a recipe header' before a single field was looked at.
    """
    complaints = [
        message
        for message in errors(MIXED_CASE)
        if "header" in message.lower() or "document" in message.lower()
    ]
    assert complaints == []


def test_line_numbers_survive_normalization():
    """
    The _LineMap trap. The map is built from the raw YAML node, whose keys keep
    their original case. Lowercase the documents but not the map and every
    verdict is right while every line number is None - the error gutter in the
    Recipe Creator goes blank and the fix reads as a regression.

    `wait_time` is missing here, which the framework refuses, so there is a
    genuine error to carry a line.
    """
    text = (
        "Name: Case demo\n"
        "Version: 0.2\n"
        "---\n"
        "Sequence_Name: Main\n"
        "Steps:\n"
        "  - Steptype: Wait\n"
        "    Step_Name: First wait\n"
    )
    assert not framework_accepts(text)
    reported = [issue for issue in verify_string(text) if issue.is_error]
    assert reported, "a recipe the framework refuses must not verify clean"
    assert any(issue.line is not None for issue in reported)


DUPLICATE_SEQUENCE_NAMES = """\
name: Case demo
version: 0.2
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: First wait
    wait_time: '0.5'
---
sequence_name: main
steps:
  - steptype: Wait
    step_name: Second wait
    wait_time: '0.5'
"""


def test_duplicate_sequence_names_differing_only_in_case_are_reported():
    """
    A3: the parser compares sequence names lowercased (recipe_parser.py:95), so
    `Main` and `main` are a duplicate and the recipe does not load. The
    verificator compared them exactly and stayed silent - a false clean.
    """
    assert not framework_accepts(DUPLICATE_SEQUENCE_NAMES)
    assert errors(DUPLICATE_SEQUENCE_NAMES) != []


MAIN_SEQUENCE_DIFFERENT_CASE = """\
name: Case demo
version: 0.2
main_sequence: main
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: First wait
    wait_time: '0.5'
"""


def test_main_sequence_is_matched_case_insensitively():
    """
    A4: the parser resolves main_sequence lowercased (recipe_parser.py:105), so
    this recipe runs. The verificator matched exactly and called it a broken
    reference - a false error.
    """
    assert framework_accepts(MAIN_SEQUENCE_DIFFERENT_CASE)
    assert errors(MAIN_SEQUENCE_DIFFERENT_CASE) == []


@pytest.mark.parametrize("text", [LOWER_CASE, MIXED_CASE, MAIN_SEQUENCE_DIFFERENT_CASE])
def test_accepted_recipes_verify_clean(text):
    """The property, stated directly: no false errors."""
    assert framework_accepts(text)
    assert errors(text) == []


@pytest.mark.parametrize("text", [DUPLICATE_SEQUENCE_NAMES])
def test_refused_recipes_do_not_verify_clean(text):
    """The other half: no false cleans."""
    assert not framework_accepts(text)
    assert errors(text) != []
