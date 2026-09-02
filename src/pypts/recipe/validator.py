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
    # teardown_steps may be empty - it is an optional extra.
    if document.get("steps") == []:
        problems.append(f"sequence '{name}': 'steps' must contain at least one step")

    for list_name in ("steps", "teardown_steps"):
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

    problems.extend(_check_mappings(step_data))

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


def _check_mappings(step_data: dict[str, Any]) -> list[str]:
    """
    The `inputs` and `outputs` entries of one step against the vocabulary.

    Without this a typo'd `type` - or one that used to exist, like the dropped
    `local` - loads without complaint and fails on the bench, because
    `Step.process_inputs` only meets it while the step runs. The vocabulary
    itself is rules.INPUT_TYPES / rules.OUTPUT_TYPES.
    """
    problems = []
    for mapping_name, legal, bare_value_is_a_literal in (
        ("inputs", rules.INPUT_TYPES, True),
        ("outputs", rules.OUTPUT_TYPES, False),
    ):
        mapping = step_data.get(mapping_name)
        if mapping is None:
            continue
        if not isinstance(mapping, dict):
            problems.append(f"'{mapping_name}' must be a mapping of names to values")
            continue
        for entry_name, config in mapping.items():
            problems.extend(
                _check_entry(mapping_name, entry_name, config, legal, bare_value_is_a_literal)
            )
    return problems


def _check_entry(
    mapping_name: str,
    entry_name: str,
    config: Any,
    legal: dict[str, tuple[str, ...]],
    bare_value_is_a_literal: bool,
) -> list[str]:
    """One `inputs`/`outputs` entry: its type, and the keys that type needs."""
    where = f"{mapping_name} '{entry_name}'"
    if not isinstance(config, dict):
        if bare_value_is_a_literal:
            return []
        return [f"{where}: must be a mapping naming a 'type'"]

    known = ", ".join(sorted(legal))
    declared = config.get("type")
    if declared is None:
        if bare_value_is_a_literal:
            return [
                f"{where}: a mapping names a 'type' ({known}). A literal value "
                f"is written as itself: `{entry_name}: <the value>`."
            ]
        return [f"{where}: needs a 'type' - one of {known}"]

    required = legal.get(str(declared).lower())
    if required is None:
        return [f"{where}: unknown type '{declared}'. Available: {known}"]

    problems = []
    for key in required:
        if config.get(key) is None:
            problems.append(f"{where}: a '{declared}' entry needs '{key}'")
    return problems
