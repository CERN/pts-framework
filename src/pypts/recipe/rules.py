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

################################ RECIPE FORMAT RULES ################################

#: The header fields a recipe cannot exist without. `version` is the **pypts
#: version the recipe was written for**, not a version of the recipe itself:
#: the parser compares its major.minor with the running framework's and says
#: so when they differ (warn-only - recipe_parser._check_framework_version).
#: There is no `format_version`; one version field is enough, and the format
#: only ever changes with the framework that reads it.
HEADER_REQUIRED: tuple[str, ...] = ("name", "version")

#: The globals the Report stamps on every row of report.csv and in the
#: header of report.html. Named by the recipe, so the framework carries a
#: convention rather than a policy: the default is the one PyPTS proposes
#: (a `get_serial_number` UserWrite step writing the `serial_number`
#: global - see resources/roadmap/best_practices.md), and a recipe testing
#: something without a serial number writes its own list, or `[]` for none.
#: A name that is never set stays an empty cell; nothing complains.
REPORT_METADATA_DEFAULT: tuple[str, ...] = ("serial_number",)

#: Optional header fields and what an absent one means. An empty
#: `main_sequence` means "the first sequence in the file".
HEADER_DEFAULTS: dict[str, Any] = {
    "description": "",
    "main_sequence": "",
    "globals": {},
    "report_metadata": REPORT_METADATA_DEFAULT,
}

#: What a sequence document must carry: its name, and something to run.
SEQUENCE_REQUIRED: tuple[str, ...] = ("sequence_name", "steps")

#: Optional sequence fields and their defaults - a sequence declares almost
#: nothing. Three keys were removed rather than kept:
#:   `setup_steps`  ran in front of `steps` and meant nothing else, so those
#:                  steps belong at the front of `steps`;
#:   `parameters` / `outputs`  the declared interface of a subsequence, and
#:                  `SequenceStep` is dropped (step.md 2.8);
#:   `locals`       a scope per sequence - global in reach, but only for as
#:                  long as one sequence ran, which is neither one thing nor
#:                  the other. There is **one** scope now: `globals`, for the
#:                  whole run. Anything narrower than that is a step's own
#:                  `inputs` and `outputs`.
SEQUENCE_DEFAULTS: dict[str, Any] = {
    "description": "",
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
    "userwrite": ("message",),
    "wait": ("wait_time",),
    "indexed": ("template", "parameter_sets"),
}

#: The `type` an `inputs` entry may name, and the key it needs beside it.
#: There is exactly one, because there are exactly two places a value can
#: come from: an entry that is **not** a mapping is the literal itself
#: (`a: 2`), and a mapping reads the run's globals. The old `direct` type
#: with its `value` key was a second spelling of the literal and is gone.
INPUT_TYPES: dict[str, tuple[str, ...]] = {
    "global": ("global_name",),
}

#: The `type` an `outputs` entry may name. `passfail`, `equals` and `range`
#: judge - they set the step's verdict; `pass` says this output is not a
#: measurement and the verdict is DONE whatever came back; `global` stores
#: the value in the run's one variable scope and leaves the verdict alone.
#: An outputs entry is always a mapping and always names its type: there is
#: no sensible default for "what to do with this value".
OUTPUT_TYPES: dict[str, tuple[str, ...]] = {
    "pass": (),
    "passfail": (),
    "equals": ("value",),
    "range": ("min", "max"),
    "global": ("global_name",),
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
#: `inputs` means the method takes no arguments; an absent `outputs` means there
#: is nothing to judge (the verdict is DONE). A Wait has neither: its one value
#: is `wait_time`, written directly on the step.
STEP_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "pythonmodule": {"inputs": {}, "outputs": {}},
    # A UserInteraction carries its question directly - message/options/
    # image_path are fields, not `inputs` entries - so only the answer
    # goes through a mapping. An absent image_path means no picture.
    "userinteraction": {"image_path": None, "outputs": {}},
    # A UserWrite carries only the question: what the operator types is the
    # output, so there is nothing to feed in. No `allow_empty` - the GUI
    # keeps OK disabled until something is typed.
    "userwrite": {"image_path": None, "outputs": {}},
    "wait": {},
    # An Indexed step owns no mappings of its own: what every generated step
    # shares goes on the `template`, what differs goes in a `parameter_sets`
    # entry. It is gone before anything is built.
    "indexed": {},
}
