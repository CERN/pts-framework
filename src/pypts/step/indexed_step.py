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
a table. A set that needs `range`, `passfail` or `global` cannot say so;
put the shared part on the `template`, which is an ordinary step mapping and
takes the full `inputs` / `outputs` vocabulary. Set entries are merged
**over** the template's, key by key.

Why expansion and not a loop: every generated step is a real `Step` with its own
UUID, so the step table pre-fills with N rows, the report gets N rows and every
run event already carries it. Nothing in the message layer, the Sequencer or the
frontends knows this steptype exists. The cost is that N is fixed when the recipe
loads - a count that depends on what an earlier step measured is not expressible,
and would need a runtime construct instead.

This replaces the old engine's `IndexedStep`, which wrapped a deep-copied
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


def is_indexed_step(step_data: Any) -> bool:
    """Whether this step mapping is an indexed step and needs expanding."""
    if not isinstance(step_data, dict):
        return False
    steptype = step_data.get("steptype")
    return isinstance(steptype, str) and steptype.lower() == INDEXED_STEPTYPE


def expand_indexed_step(step_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    One indexed step mapping in, one ordinary step mapping per set out.

    The caller builds each of them through the registry exactly as if the author
    had written them all out by hand - which is what an indexed step is: a way
    of not writing them out by hand.

    The shape rules live in recipe_schema.IndexedStepSchema, which the parser
    runs before it expands anything.

    Raises:
        ValueError: if there is no template mapping or no parameter set - the
            guard for a caller that skipped validation, so it cannot silently
            expand to nothing.
    """
    template = step_data.get(TEMPLATE_KEY)
    sets = step_data.get(SETS_KEY)
    if not isinstance(template, dict) or not isinstance(sets, list) or not sets:
        raise ValueError(
            f"an {INDEXED_STEPTYPE} step requires a '{TEMPLATE_KEY}' mapping and "
            f"a non-empty '{SETS_KEY}' list"
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

    # The picture follows the description: the wrapper's shows on every
    # generated step, unless the template names its own.
    if not generated.get("image_path") and step_data.get("image_path"):
        generated["image_path"] = step_data["image_path"]

    # The graph follows the picture: the wrapper's shows on every generated
    # step, unless the template names its own.
    if not generated.get("graph") and step_data.get("graph"):
        generated["graph"] = step_data["graph"]

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
