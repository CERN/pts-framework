# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The indexed step: one authored step, N parameter sets, N ordinary steps.

`steptype: Indexed` is the only steptype that never reaches the registry and
never runs. It is expanded **at load time**: the parser hands the mapping to
`expand_indexed_step()` and gets back one ordinary step mapping per parameter
set, which it builds through `build_step()` like any other step.

    - steptype: Indexed
      step_name: Add numbers
      template:
        steptype: PythonModule
        module: example_tests.py
        method_name: add
      parameter_sets:
        - inputs: {a: 1, b: 1}
          expect: {sum: 2}
        - inputs: {a: 2, b: 3}
          expect: {sum: 5}

`inputs` are direct values and `expect` are `equals` checks - the terse
spelling, because a parameter set is a test case and should read like a row of
a table. A set that needs `range`, `passfail`, `local` or `global` cannot say so;
put the shared part on the `template`, which is an ordinary step mapping and
takes the full `inputs` / `outputs` vocabulary. Set entries are merged
**over** the template's, key by key.

Why expansion and not a loop: every generated step is a real `Step` with its own
UUID, so the step table pre-fills with N rows, the report gets N rows and every
run event already carries it. Nothing in the message layer, the Sequencer or the
frontends knows this steptype exists. The cost is that N is fixed when the recipe
loads - a count that depends on what an earlier step measured is not expressible,
and would need a runtime construct instead.

This replaces `old_code/steps.py`'s `IndexedStep`, which wrapped a deep-copied
template at *run* time, iterated to the length of the shortest of several
parallel `indexed: true` lists (silently truncating), and then discarded its own
`outputs` mapping so the results it aggregated could never be stored (F25).
Row-wise sets have neither problem: one set is one coherent case.
"""

from typing import Any

#: The steptype, lowercase as the registry and the rules spell them.
INDEXED_STEPTYPE = "indexed"

#: The step mapping every generated step is built from.
TEMPLATE_KEY = "template"

#: The list of parameter sets, one per generated step.
SETS_KEY = "parameter_sets"

#: What one set may carry: direct input values, and expected output values.
SET_KEYS = ("inputs", "expect")


def is_indexed_step(step_data: Any) -> bool:
    """Whether this step mapping is an indexed step and needs expanding."""
    if not isinstance(step_data, dict):
        return False
    steptype = step_data.get("steptype")
    return isinstance(steptype, str) and steptype.lower() == INDEXED_STEPTYPE


def check_indexed_step(step_data: dict[str, Any]) -> list[str]:
    """
    Everything about an indexed step's own shape, as a list of problems.

    Called by the validator, so the recipe author gets every problem in the file
    at once. The *template* is validated by the validator itself - it is an
    ordinary step mapping and the validator already knows how to check one.

    Returns:
        Human-readable problems; an empty list means the shape is fine.
    """
    problems = []

    # One id would be handed to N steps, and the step table is keyed by id.
    if step_data.get("id") is not None:
        problems.append(
            f"an {INDEXED_STEPTYPE} step becomes several steps and cannot carry an 'id'"
        )

    # Silently ignoring these would be worse: an author who writes them expects
    # them to apply, and they would apply to nothing.
    for mapping_name in ("inputs", "outputs"):
        if step_data.get(mapping_name) is not None:
            problems.append(
                f"'{mapping_name}' belongs on the '{TEMPLATE_KEY}', not on the "
                f"{INDEXED_STEPTYPE} step itself"
            )

    template = step_data.get(TEMPLATE_KEY)
    if template is not None:
        if not isinstance(template, dict):
            problems.append(f"'{TEMPLATE_KEY}' must be a step mapping")
        elif is_indexed_step(template):
            problems.append(f"an {INDEXED_STEPTYPE} step cannot be the '{TEMPLATE_KEY}'")
        elif template.get("id") is not None:
            problems.append(f"the '{TEMPLATE_KEY}' cannot carry an 'id': it becomes N steps")

    problems.extend(_check_sets(step_data.get(SETS_KEY)))
    return problems


def _check_sets(sets: Any) -> list[str]:
    """The parameter_sets list and every set in it."""
    if sets is None:
        # Its absence is already reported by the required-field check.
        return []
    if not isinstance(sets, list):
        return [f"'{SETS_KEY}' must be a list of parameter sets"]
    if not sets:
        return [f"'{SETS_KEY}' must contain at least one set"]

    problems = []
    for position, one_set in enumerate(sets, start=1):
        where = f"{SETS_KEY}[{position}]"
        if not isinstance(one_set, dict):
            problems.append(f"{where}: a parameter set must be a mapping")
            continue

        unknown = [key for key in one_set if key not in SET_KEYS]
        if unknown:
            problems.append(
                f"{where}: unknown key(s) {', '.join(sorted(unknown))}. "
                f"A set may carry: {', '.join(SET_KEYS)}"
            )
        for key in SET_KEYS:
            value = one_set.get(key)
            if value is not None and not isinstance(value, dict):
                problems.append(f"{where}: '{key}' must be a mapping of names to values")
        if not any(isinstance(one_set.get(key), dict) and one_set[key] for key in SET_KEYS):
            problems.append(
                f"{where}: a set must carry at least one of {', '.join(SET_KEYS)}"
            )
    return problems


def expand_indexed_step(step_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    One indexed step mapping in, one ordinary step mapping per set out.

    The caller builds each of them through the registry exactly as if the author
    had written them all out by hand - which is what an indexed step is: a way
    of not writing them out by hand.

    Raises:
        ValueError: if the shape is wrong. The validator has normally reported
            it already and the parser never gets here; this is the guard for a
            caller that skipped validation.
    """
    problems = check_indexed_step(step_data)
    if problems:
        raise ValueError("; ".join(problems))

    template = step_data.get(TEMPLATE_KEY)
    sets = step_data.get(SETS_KEY)
    if not isinstance(template, dict) or not isinstance(sets, list):
        raise ValueError(
            f"an {INDEXED_STEPTYPE} step requires '{TEMPLATE_KEY}' and '{SETS_KEY}'"
        )

    base_name = str(step_data.get("step_name", "") or template.get("step_name", ""))
    expanded = []
    for position, one_set in enumerate(sets, start=1):
        expanded.append(
            _build_one(step_data, template, one_set, base_name, position, len(sets))
        )
    return expanded


def _build_one(
    step_data: dict[str, Any],
    template: dict[str, Any],
    one_set: dict[str, Any],
    base_name: str,
    position: int,
    total: int,
) -> dict[str, Any]:
    """The step mapping for one parameter set."""
    inputs = one_set.get("inputs") or {}
    expect = one_set.get("expect") or {}

    generated = dict(template)
    generated["step_name"] = _name_for(base_name, inputs, position, total)

    # The wrapper's description carries the intent of the whole group; a
    # template that states its own keeps it.
    if not generated.get("description"):
        generated["description"] = step_data.get("description", "")

    # `skip` on the wrapper skips every generated step - the obvious meaning of
    # skipping an indexed step, and the only way to say it. `continue_on_error`
    # carries the same way: "do not continue past this indexed step" can only be
    # said on the wrapper, and it means it of whichever row halts.
    for wrapper_field in ("skip", "continue_on_error"):
        if step_data.get(wrapper_field) is not None and generated.get(wrapper_field) is None:
            generated[wrapper_field] = step_data[wrapper_field]

    # Set entries are merged over the template's, so the template can hold what
    # every case shares and a set only says what makes it different.
    # A set's inputs are direct values, and a direct value is written as
    # itself, so a generated step reads exactly as a hand-written one would.
    step_inputs = dict(template.get("inputs") or {})
    for name, value in inputs.items():
        step_inputs[name] = value

    step_outputs = dict(template.get("outputs") or {})
    for name, value in expect.items():
        step_outputs[name] = {"type": "equals", "value": value}

    # Left out entirely when empty: a step type that takes no mappings (Wait)
    # should not be handed two empty ones.
    if step_inputs:
        generated["inputs"] = step_inputs
    else:
        generated.pop("inputs", None)
    if step_outputs:
        generated["outputs"] = step_outputs
    else:
        generated.pop("outputs", None)

    return generated


def _name_for(
    base_name: str, inputs: dict[str, Any], position: int, total: int
) -> str:
    """
    What the operator reads in the step table, and what lands in the CSV.

    The parameters that make the case distinct, so a failed row explains itself
    without opening the recipe: `Add numbers [a=2, b=3]`. A set that varies only
    its expectation has no parameters to show, so it falls back to the position.
    """
    if not inputs:
        return f"{base_name} {position}/{total}"
    shown = ", ".join(f"{name}={value}" for name, value in inputs.items())
    return f"{base_name} [{shown}]"
