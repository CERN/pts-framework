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

#: Steptypes that are expanded when the recipe loads and never run as a step of
#: their own, so they exist in the rules below but not in the step registry.
#: `indexed` becomes one ordinary step per parameter set - see
#: pypts.step.indexed_step.
EXPANDED_STEP_TYPES: tuple[str, ...] = ("indexed",)

#: What each steptype additionally requires, keyed by lowercased steptype.
#: These are the only steptypes a recipe may name.
STEP_TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "pythonmodule": ("module", "method_name"),
    "userinteraction": ("message", "options"),
    "wait": ("wait_time",),
    "indexed": ("template", "parameter_sets"),
}

#: Optional fields every step accepts whatever its type, and what an absent one
#: means. They are the common arguments of pypts.step.step.Step, so a new step
#: type gets them for free and must not repeat them below.
#: `continue_on_error: false` means an ERROR or a FAIL on that step ends the
#: run and every step after it is recorded SKIP; the default carries on to the
#: next step. It is written on a step and nowhere else - a recipe-level or
#: `globals` form is exactly what F1 and F8 were.
STEP_COMMON_DEFAULTS: dict[str, Any] = {
    "description": "",
    "skip": False,
    "continue_on_error": True,
}

#: Optional step fields per steptype, on top of STEP_COMMON_DEFAULTS. An absent
#: `input_mapping` means the method takes no arguments; an absent
#: `output_mapping` means there is nothing to judge (the verdict is DONE). A
#: Wait has neither: its one value is `wait_time`, written directly on the step.
STEP_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "pythonmodule": {"input_mapping": {}, "output_mapping": {}},
    # A UserInteraction carries its question directly - message/options/
    # image_path are fields, not input_mapping entries - so only the answer
    # goes through a mapping. An absent image_path means no picture.
    "userinteraction": {"image_path": None, "output_mapping": {}},
    "wait": {},
    # An Indexed step owns no mappings of its own: what every generated step
    # shares goes on the `template`, what differs goes in a `parameter_sets`
    # entry. It is gone before anything is built.
    "indexed": {},
}
