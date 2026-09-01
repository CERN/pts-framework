# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe validator: parsed YAML in, a list of problems out.

The parser (recipe_parser.py) runs these checks before it builds anything, and
raises one RecipeError naming *every* problem at once - so the user fixes
the file in one round trip, not one error at a time. Each function returns
a plain list of human-readable problem strings; an empty list means the
piece is fine.

What is checked is exactly what rules.py declares: the mandatory fields of
the header, of every sequence document, and of every step - common fields
first, then the fields the step's own type requires. Optional fields are
never demanded; the parser fills their defaults in afterwards. Anything
beyond field presence (a duplicate sequence name, a main_sequence that
names no sequence, an unknown step key) stays with the parser, which has
the whole file in hand.
"""

from typing import Any

from pypts.recipe import rules
from pypts.step import indexed_step


def validate_header(header: dict[str, Any]) -> list[str]:
    """The mandatory header fields, per rules.HEADER_REQUIRED."""
    problems = []
    for field in rules.HEADER_REQUIRED:
        if header.get(field) is None:
            problems.append(f"header: missing the required field '{field}'")
    return problems


def validate_sequence(document: dict[str, Any]) -> list[str]:
    """One sequence document: its own mandatory fields, then every step's."""
    name = document.get("sequence_name", "<unnamed>")
    problems = []
    for field in rules.SEQUENCE_REQUIRED:
        if document.get(field) is None:
            problems.append(f"sequence '{name}': missing the required key '{field}'")

    # A sequence exists to run something: `steps` must hold at least one step.
    # setup_steps and teardown_steps may be empty - they are optional extras.
    if document.get("steps") == []:
        problems.append(f"sequence '{name}': 'steps' must contain at least one step")

    for list_name in ("setup_steps", "steps", "teardown_steps"):
        steps = document.get(list_name)
        if steps is None:
            continue
        if not isinstance(steps, list):
            problems.append(f"sequence '{name}': '{list_name}' is not a list of steps")
            continue
        for position, step_data in enumerate(steps, start=1):
            for problem in validate_step(step_data):
                problems.append(f"sequence '{name}', {list_name}[{position}]: {problem}")
    return problems


def validate_step(step_data: Any) -> list[str]:
    """One step mapping: the common mandatory fields, then its type's own."""
    if not isinstance(step_data, dict):
        return ["a step must be a mapping of keys to values"]

    problems = []
    for field in rules.STEP_REQUIRED:
        if step_data.get(field) is None:
            problems.append(f"missing the required key '{field}'")

    steptype = step_data.get("steptype")
    if steptype is None:
        return problems
    type_required = rules.STEP_TYPE_REQUIRED.get(str(steptype).lower())
    if type_required is None:
        known = ", ".join(sorted(rules.STEP_TYPE_REQUIRED))
        problems.append(f"unknown steptype '{steptype}'. Available: {known}")
        return problems
    for field in type_required:
        if step_data.get(field) is None:
            problems.append(f"a {steptype} step requires the key '{field}'")

    # An indexed step is checked twice over: its own shape here, and its
    # template as the ordinary step it will be expanded into. Both before
    # anything is built, so the author sees every problem in one error.
    if indexed_step.is_indexed_step(step_data):
        problems.extend(indexed_step.check_indexed_step(step_data))
        template = step_data.get(indexed_step.TEMPLATE_KEY)
        if isinstance(template, dict):
            # The template is checked as the step it will become, so it is
            # given the name expansion will give it: a template states what
            # every generated step shares, and the name is not shared - each
            # one is named after its own parameters.
            probe = dict(template)
            if probe.get("step_name") is None:
                probe["step_name"] = step_data.get("step_name") or "<the indexed step's>"
            for problem in validate_step(probe):
                problems.append(f"{indexed_step.TEMPLATE_KEY}: {problem}")
    return problems
