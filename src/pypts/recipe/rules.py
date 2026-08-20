# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe format rules, as code - the one importable source of truth.

Everything that decides whether a recipe file is acceptable lives here and
nowhere else. Definitions only: the code that acts on them - normalization,
defaults, parsing - lives in recipe.py, the checks in validator.py.
"""

from typing import Any

#: The version of the recipe - independent of the pypts version
#: Bump it in the same change that alters a rule, and note what changed:
#:   0.1.0  the minimalistic format
RECIPE_FORMAT_VERSION = "0.1.0"


################################ RECIPE FORMAT RULES ################################

#: The one header field a recipe cannot exist without.
HEADER_REQUIRED: tuple[str, ...] = ("name",)

#: Optional header fields and what an absent one means. An empty
#: `main_sequence` means "the first sequence in the file". An empty
#: `format_version` means "written for the current format" - the parser
#: logs a mismatch against RECIPE_FORMAT_VERSION (warn-only for now).
HEADER_DEFAULTS: dict[str, Any] = {
    "description": "",
    "version": "",
    "format_version": "",
    "main_sequence": "",
    "globals": {},
}

#: What a sequence document must carry: its name, and something to run.
SEQUENCE_REQUIRED: tuple[str, ...] = ("sequence_name", "steps")

#: Optional sequence fields and their defaults.
SEQUENCE_DEFAULTS: dict[str, Any] = {
    "description": "",
    "parameters": {},
    "locals": {},
    "outputs": {},
    "setup_steps": [],
    "teardown_steps": [],
}

#: What every step must carry, whatever its type.
STEP_REQUIRED: tuple[str, ...] = ("steptype", "step_name")

#: What each steptype additionally requires, keyed by lowercased steptype.
#: These are the only steptypes a recipe may name.
STEP_TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "pythonmodule": ("module", "method_name"),
    "wait": ("wait_time",),
}

#: Optional step fields per steptype. An absent `input_mapping` means the
#: method takes no arguments; an absent `output_mapping` means there is
#: nothing to judge (the verdict is DONE). A Wait has neither: its one
#: value is `wait_time`, written directly on the step.
STEP_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "pythonmodule": {"description": "", "input_mapping": {}, "output_mapping": {}},
    "wait": {"description": ""},
}
