# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
steptype name -> step class, and the one function that builds a step.

This is the replacement for the old factory's eval() over the steptype
string (old_code/recipe.py) - arbitrary code execution driven by a recipe
file, with a NameError as its only diagnostic. Here a recipe can only ever
select from this dict, and an unknown name gets an error that lists what
would have worked.

The dict is the whole mechanism on purpose: roadmap Phase 2 swaps it for
entry-point discovery (pip-installed step plugins) without changing
build_step()'s signature, and built-in types keep registering through the
same table.
"""

from typing import Any

from pypts.step.step import Step
from pypts.step.steps import PythonModuleStep, WaitStep

#: Every steptype a recipe may name, keyed lowercase - the YAML spelling is
#: case-insensitive (the old factory lower-cased eight of ten types and
#: forgot the SSH two, which therefore only worked in exact case). The YAML
#: names drop the class names' Step suffix: `PythonModule`, `Wait`. The keys
#: must match pypts.recipe.rules.STEP_TYPE_REQUIRED - a unit test pins that.
STEP_TYPES: dict[str, type[Step]] = {
    "pythonmodule": PythonModuleStep,
    "wait": WaitStep,
}


def build_step(step_data: dict[str, Any]) -> Step:
    """
    Build one step from its YAML mapping.

    Every key except `steptype` becomes a constructor argument, so an
    unknown key is a TypeError at load time (the recipe layer wraps it with
    the sequence and step context). The caller's dict is not touched.
    """
    remaining = dict(step_data)
    step_type = remaining.pop("steptype")
    step_class = STEP_TYPES.get(step_type.lower())
    if step_class is None:
        raise ValueError(
            f"Unknown steptype {step_type!r}. Available: {', '.join(sorted(STEP_TYPES))}"
        )
    return step_class(**remaining)
