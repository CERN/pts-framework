# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Recipe schema: the format constants and Pydantic models for validating raw
recipe YAML dicts.

Constants keep the same names as the old rules.py so that consumer imports
are a one-line change. The models below them are what recipe_parser.py
validates every document with.
"""

from typing import Annotated, Any, Literal, NoReturn, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from pypts.step.sequence_step import REFUSED_KEYS as SEQUENCE_STEP_REFUSED_KEYS

################################ CONSTANTS ################################
# (moved verbatim from the old rules.py)

#: The header fields a recipe cannot exist without. `version` is the **pypts
#: version the recipe was written for**, not a version of the recipe itself:
#: the parser compares its major.minor with the running framework's and says
#: so when they differ (warn-only - recipe_parser._check_framework_version).
#: There is no `format_version`; one version field is enough, and the format
#: only ever changes with the framework that reads it.
HEADER_REQUIRED: tuple[str, ...] = ("name", "version")

#: Header fields that hold one value - a name, a version, a sentence - and so
#: may not be written as a list or a mapping. `globals` is the one header
#: field that must be a mapping; `report_metadata` is checked by the parser.
HEADER_SINGLE_VALUE: tuple[str, ...] = ("name", "version", "description", "main_sequence")

#: The globals the Report stamps on every row of report.csv and in the
#: header of report.html. Named by the recipe, so the framework carries a
#: convention rather than a policy: the default is the one PyPTS proposes
#: (a `get_serial_number` UserWrite step writing the `serial_number`
#: global - see recipe_guide.html at repo root), and a recipe testing
#: something without a serial number writes its own list, or `[]` for none.
#: A name that is never set stays an empty cell; nothing complains.
#: The first name's value also names the report files (report/report.md).
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
#:   `parameters` / `outputs`  a declared interface for a called sequence. A
#:                  Sequence step calls another sequence without one: the
#:                  group shares the run's globals (step.md 2.8);
#:   `locals`       a scope per sequence - global in reach, but only for as
#:                  long as one sequence ran, which is neither one thing nor
#:                  the other. There is **one** scope now: `globals`, for the
#:                  whole run. Anything narrower than that is a step's own
#:                  `inputs` and `outputs`.
SEQUENCE_DEFAULTS: dict[str, Any] = {
    "description": "",
    "image_path": None,
    "teardown_steps": [],
}

#: What every step must carry, whatever its type.
STEP_REQUIRED: tuple[str, ...] = ("steptype", "step_name")

#: Steptypes that take no `step_name`: they are named by something else. A
#: Sequence step is named after the sequence it calls (step/sequence_step.py).
UNNAMED_STEP_TYPES: tuple[str, ...] = ("sequence",)

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
    "userloading": ("message",),
    "wait": ("wait_time",),
    "sequence": ("sequence_name",),
    "indexed": ("template", "parameter_sets"),
}

#: Each steptype as it is written in a recipe and shown to an author, keyed as
#: STEP_TYPE_REQUIRED is. Case does not matter to the parser; this is the
#: spelling the documentation and the demo recipes use.
STEP_TYPE_NAMES: dict[str, str] = {
    "pythonmodule": "PythonModule",
    "userinteraction": "UserInteraction",
    "userwrite": "UserWrite",
    "userloading": "UserLoading",
    "wait": "Wait",
    "sequence": "Sequence",
    "indexed": "Indexed",
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
#: judge - the step is PASS when all of them pass, FAIL when any fails, DONE
#: when it has none; `pass` records a value that is not a measurement and
#: `global` stores it in the run's one variable scope - neither touches the
#: verdict.
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
#: `image_path` is the picture the GUI shows while the step runs; an absent one
#: means none of the step's own (the sequence's, if it has one, shows instead).
STEP_COMMON_DEFAULTS: dict[str, Any] = {
    "description": "",
    "image_path": None,
    "skip": False,
    "continue_on_error": True,
}

#: Optional step fields per steptype, on top of STEP_COMMON_DEFAULTS. An absent
#: `inputs` means the method takes no arguments; an absent `outputs` means there
#: is nothing to judge (the verdict is DONE). A Wait has neither: its one value
#: is `wait_time`, written directly on the step.
STEP_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "pythonmodule": {"inputs": {}, "outputs": {}},
    # A UserInteraction carries its question directly - message and options
    # are fields, not `inputs` entries - so only the answer goes through a
    # mapping.
    "userinteraction": {"outputs": {}},
    # A UserWrite carries only the question: what the operator types is the
    # output, so there is nothing to feed in. No `allow_empty` - the GUI
    # keeps OK disabled until something is typed.
    "userwrite": {"outputs": {}},
    # A UserLoading asks for a path: `select` says whether a file or a folder,
    # and anything but those two words (case-insensitive) is refused by the
    # step's constructor when the recipe loads. The chosen path is the output.
    "userloading": {"select": "file", "outputs": {}},
    "wait": {},
    # A Sequence step owns no mappings: a called sequence shares the run's
    # globals and takes its verdict from its own steps.
    "sequence": {},
    # An Indexed step owns no mappings of its own: what every generated step
    # shares goes on the `template`, what differs goes in a `parameter_sets`
    # entry. It is gone before anything is built.
    "indexed": {},
}


################################ PYDANTIC MODELS ################################
#
# The models check a recipe after recipe_parser has normalized it - keys and the
# steptype value lowercased - and before anything is built. What a model accepts
# is what the step constructors take: the parser hands them the validated mapping
# (model_dump(exclude_unset=True)), so a key a constructor would refuse is refused
# here instead, named alongside every other problem in the file.


class _RecipeModel(BaseModel):
    """
    What every recipe model shares.

    Numbers are read as text where text is expected: YAML reads `version: 0.2`
    as a float and `step_name: 7` as an int, and both load today. Mapping keys
    and global names are not text fields: they stay exactly as written, because
    a global is found by plain dict lookup and `7` and `'7'` are two globals.
    An unknown key is refused, everywhere: a misspelled `teardown_steps` or
    `max` that loaded and was ignored would quietly drop what it meant.
    """

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    @model_validator(mode="before")
    @classmethod
    def _bare_key_is_absent(cls, data: Any) -> Any:
        """
        YAML reads a bare `description:` line as None. Dropping it leaves an
        optional field unset, at its default, and makes a required field
        'Field required' - the same answer as not writing the line at all.
        """
        if not isinstance(data, dict):
            return data
        kept = {}
        for key, value in data.items():
            if value is None and key in cls.model_fields:
                continue
            kept[key] = value
        return kept


def _refuse(reason: str) -> NoReturn:
    """Refuse a value with a sentence of our own; Pydantic adds no prefix to it."""
    raise PydanticCustomError("recipe_refused", reason)


# -- header ----------------------------------------------------------------------


def _report_name(name: str) -> str:
    """One report_metadata entry: it becomes a CSV column, so it must name something."""
    name = name.strip()
    if not name:
        _refuse("a report_metadata entry must be the name of a global")
    return name


def _report_names(names: list[str]) -> list[str]:
    """The report_metadata list: each name is a CSV column, so none may come twice."""
    seen: set[str] = set()
    for name in names:
        if name in seen:
            _refuse(f"report_metadata names '{name}' twice; each global is one report column")
        seen.add(name)
    return names


class HeaderSchema(_RecipeModel):
    """Document 1 of a recipe."""

    name: str = Field(
        description=(
            "The recipe's name, so the operator and the report can tell what was run."
        ),
        examples=["Output Voltage Test"],
    )
    version: str = Field(
        description=(
            "The PyPTS version the recipe was written for. The framework warns "
            "when it differs from the one running it."
        ),
        examples=["0.2"],
    )
    description: str = Field(
        default="",
        description="What the recipe tests, in a sentence or two.",
    )
    main_sequence: str = Field(
        default="",
        description=(
            "The name of the sequence to run. If omitted, the first sequence in "
            "the file runs."
        ),
        examples=["Main"],
    )
    globals: dict[Any, Any] = Field(
        default_factory=dict,
        description=(
            "The run's variables and their starting values. A step reads one with "
            "{type: global, global_name: <name>} and writes one through an output "
            "of type 'global'."
        ),
        examples=[{"serial_number": "", "voltage": 0}],
    )
    # Strict: a column called `3` is a mistake, not a name to coerce.
    report_metadata: Annotated[
        list[Annotated[StrictStr, AfterValidator(_report_name)]],
        AfterValidator(_report_names),
    ] = Field(
        default_factory=lambda: list(REPORT_METADATA_DEFAULT),
        description=(
            "The names of globals stamped on every row of the report. Each entry is "
            "a name written as text, given once; a number is not a name."
        ),
        examples=[["serial_number", "lot_number"]],
    )


# -- inputs and outputs ------------------------------------------------------------


def _input_entry(value: Any) -> Any:
    """
    One `inputs` entry. A mapping reads the run's globals and names its type;
    anything else is the literal value itself (INPUT_TYPES).
    """
    if not isinstance(value, dict):
        return value
    known = ", ".join(sorted(INPUT_TYPES))
    declared = value.get("type")
    if declared is None:
        _refuse(f"a mapping names its 'type' ({known}); a literal value is written as itself")
    # A mapping or a list cannot be looked up in INPUT_TYPES; it is unknown too.
    if not isinstance(declared, str) or declared not in INPUT_TYPES:
        _refuse(f"unknown type '{declared}'. Available: {known}")
    for key in INPUT_TYPES[declared]:
        if value.get(key) is None:
            _refuse(f"a '{declared}' entry needs '{key}'")
    return value


InputEntry = Annotated[Any, AfterValidator(_input_entry)]


class PassOutput(_RecipeModel):
    type: Literal["pass"] = Field(
        description="Records the returned value without judging it; the step stays DONE."
    )


class PassfailOutput(_RecipeModel):
    type: Literal["passfail"] = Field(
        description=(
            "Passes if the returned value is True, fails if it is False; any other "
            "value is an ERROR."
        )
    )


class EqualsOutput(_RecipeModel):
    type: Literal["equals"] = Field(
        description="Passes if the returned value equals 'value' exactly."
    )
    value: Any = Field(description="The value the step must return to pass.", examples=[5])


class RangeOutput(_RecipeModel):
    type: Literal["range"] = Field(
        description="Passes if the returned value is between 'min' and 'max'."
    )
    min: Any = Field(description="The lowest value that passes.", examples=[4.9])
    max: Any = Field(description="The highest value that passes.", examples=[5.1])


class GlobalOutput(_RecipeModel):
    type: Literal["global"] = Field(
        description="Stores the returned value in a run variable, without judging it."
    )
    global_name: Any = Field(
        description="The run variable (a name in 'globals') to store the value in.",
        examples=["my_var"],
    )


#: One `outputs` entry, picked by its `type` (OUTPUT_TYPES).
OutputEntry = Annotated[
    PassOutput | PassfailOutput | EqualsOutput | RangeOutput | GlobalOutput,
    Field(discriminator="type"),
]

#: Each output type's model, keyed as OUTPUT_TYPES is - for a tool that asks an
#: output type what it means and which keys it takes (the Recipe Creator's hints).
OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "pass": PassOutput,
    "passfail": PassfailOutput,
    "equals": EqualsOutput,
    "range": RangeOutput,
    "global": GlobalOutput,
}


# -- steps -------------------------------------------------------------------------


class _StepFields(_RecipeModel):
    """STEP_COMMON_DEFAULTS: what every steptype accepts."""

    description: str = Field(default="", description="What the step does, for the operator.")
    image_path: str | None = Field(
        default=None,
        description=(
            "A picture shown on the right while this step runs: a path relative to "
            "the recipe's own folder, or an absolute one."
        ),
        examples=["probe_tp3.png"],
    )
    skip: bool = Field(
        default=False,
        description="true records the step as SKIP without running it.",
        examples=[True],
    )
    continue_on_error: bool = Field(
        default=True,
        description=(
            "false means an ERROR or FAIL on this step ends the run, and every "
            "step after it is recorded SKIP."
        ),
        examples=[False],
    )


class _OrdinaryStep(_StepFields):
    """The arguments of pypts.step.step.Step's constructor, which every built step takes."""

    step_name: str = Field(
        description="The step's name, shown in the step table and the report.",
        examples=["Measure output voltage"],
    )
    id: str = Field(
        default="",
        description="A stable id for the step. If omitted, the step gets a fresh one.",
        examples=["my-stable-id"],
    )
    inputs: dict[Any, InputEntry] = Field(
        default_factory=dict,
        description=(
            "The arguments passed to the step, by name. A value is written as itself; "
            "a mapping with type 'global' reads a run variable instead."
        ),
        examples=[{"channel": 1, "voltage": {"type": "global", "global_name": "v_set"}}],
    )
    outputs: dict[Any, OutputEntry] = Field(
        default_factory=dict,
        description=(
            "What to do with each value the step returns, by name: judge it "
            "(equals, range, passfail), record it (pass) or store it (global)."
        ),
        examples=[{"output": {"type": "range", "min": 4.9, "max": 5.1}}],
    )


class PythonModuleStepSchema(_OrdinaryStep):
    steptype: Literal["pythonmodule"] = Field(
        description="Calls one function of a Python module and judges what it returns."
    )
    module: str = Field(
        description=(
            "The Python file to call, relative to the recipe's own folder, or a "
            "dotted module name."
        ),
        examples=["my_tests.py"],
    )
    method_name: str = Field(
        description="The function inside the module to call.",
        examples=["measure_voltage"],
    )


def _refuse_passfail(outputs: dict[Any, Any], returns: str) -> dict[Any, Any]:
    """
    Refuse a `passfail` entry on a step whose output is always text.

    passfail judges a bool, and text is never one, so the step could only
    ever end in ERROR. Said at load, before any hardware has run.
    """
    for name, entry in outputs.items():
        if isinstance(entry, PassfailOutput):
            _refuse(
                f"output '{name}': passfail cannot judge this step, it returns {returns}. "
                "Use {type: equals, value: <expected text>} instead"
            )
    return outputs


class UserInteractionStepSchema(_OrdinaryStep):
    steptype: Literal["userinteraction"] = Field(
        description="Asks the operator a question with buttons; the chosen one is the output."
    )
    message: str = Field(
        description="The question shown to the operator.",
        examples=["Connect the unit to J1, then continue."],
    )
    options: Any = Field(
        description="The button labels the operator can press, at least one.",
        examples=[["Continue", "Abort"]],
    )

    @field_validator("outputs")
    @classmethod
    def _no_passfail(cls, outputs: dict[Any, Any]) -> dict[Any, Any]:
        return _refuse_passfail(outputs, "the text of the button pressed")


class UserWriteStepSchema(_OrdinaryStep):
    steptype: Literal["userwrite"] = Field(
        description="Asks the operator to type something; what they type is the output."
    )
    message: str = Field(
        description="The prompt shown before the operator types their answer.",
        examples=["Scan or type the serial number."],
    )

    @field_validator("outputs")
    @classmethod
    def _no_passfail(cls, outputs: dict[Any, Any]) -> dict[Any, Any]:
        return _refuse_passfail(outputs, "the text the operator typed")


class UserLoadingStepSchema(_OrdinaryStep):
    steptype: Literal["userloading"] = Field(
        description="Asks the operator to choose a file or a folder; the path is the output."
    )
    message: str = Field(
        description="The prompt shown while the operator chooses.",
        examples=["Select the calibration file for this unit."],
    )
    select: str = Field(
        default="file",
        description="What the operator chooses: 'file' (the default) or 'folder'.",
        examples=["folder"],
    )


class WaitStepSchema(_OrdinaryStep):
    steptype: Literal["wait"] = Field(description="Pauses the run for a fixed time.")
    wait_time: Any = Field(description="How long to wait, in seconds.", examples=[2])


class SequenceStepSchema(_StepFields):
    """
    A call of another sequence. Named after it, so it takes no step_name.

    The keys in sequence_step.REFUSED_KEYS are declared only to be refused with
    their reason; a plain unknown key would say no more than 'Extra inputs'.
    """

    steptype: Literal["sequence"] = Field(
        description=(
            "Runs another sequence of this recipe as a group of steps; it shares "
            "the run's globals."
        )
    )
    sequence_name: str = Field(
        description="The name of the sequence to run, written as in its 'sequence_name'.",
        examples=["Calibrate"],
    )
    step_name: None = None
    inputs: None = None
    outputs: None = None
    id: None = None

    @field_validator(*SEQUENCE_STEP_REFUSED_KEYS, mode="before")
    @classmethod
    def _refuse_key(cls, value: Any, info: ValidationInfo) -> NoReturn:
        _refuse(SEQUENCE_STEP_REFUSED_KEYS[str(info.field_name)])

    @field_validator("sequence_name")
    @classmethod
    def _names_something(cls, name: str) -> str:
        # Empty or only spaces can name no sequence; said here, with every
        # other problem in the file, rather than alone at build time.
        if not name.strip():
            _refuse("'sequence_name' must be the name of a sequence in this recipe")
        return name


#: What an Indexed step refuses on itself, with the sentence the author reads.
INDEXED_STEP_REFUSED_KEYS: dict[str, str] = {
    "id": "an indexed step becomes several steps and cannot carry an 'id'",
    "inputs": "'inputs' belongs on the 'template', not on the indexed step itself",
    "outputs": "'outputs' belongs on the 'template', not on the indexed step itself",
}


class ParameterSet(_RecipeModel):
    """One entry of an Indexed step's `parameter_sets`: what makes one case different."""

    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Values merged into the template's inputs for this case.",
        examples=[{"a": 1, "b": 2}],
    )
    expect: dict[str, Any] = Field(
        default_factory=dict,
        description="Shorthand 'equals' checks merged into the template's outputs.",
        examples=[{"sum": 3}],
    )

    @model_validator(mode="after")
    def _says_something(self) -> Self:
        if not self.inputs and not self.expect:
            _refuse("a parameter set must carry at least one of inputs, expect")
        return self


class IndexedStepSchema(_StepFields):
    """
    One step written once and run once per parameter set (pypts.step.indexed_step).

    The template is checked as the ordinary step it becomes; the parser expands
    it after validation.
    """

    steptype: Literal["indexed"] = Field(
        description="Writes one step once and runs it once per parameter set."
    )
    step_name: str = Field(
        description=(
            "The base name of the generated steps; each one adds its own parameters to it."
        ),
        examples=["Add"],
    )
    template: "AnyStepSchema" = Field(
        description=(
            "The step every case is built from: one ordinary step, carrying the "
            "inputs and outputs the cases share."
        ),
        examples=[{"steptype": "PythonModule", "module": "my_tests.py", "method_name": "add"}],
    )
    parameter_sets: list[ParameterSet] = Field(
        min_length=1,
        description=(
            "One entry per generated step; each carries 'inputs', 'expect', or both."
        ),
        examples=[[{"inputs": {"a": 1, "b": 2}, "expect": {"sum": 3}}]],
    )
    id: None = None
    inputs: None = None
    outputs: None = None

    @field_validator(*INDEXED_STEP_REFUSED_KEYS, mode="before")
    @classmethod
    def _refuse_key(cls, value: Any, info: ValidationInfo) -> NoReturn:
        _refuse(INDEXED_STEP_REFUSED_KEYS[str(info.field_name)])

    @field_validator("template", mode="before")
    @classmethod
    def _template_is_named_after_the_step(cls, value: Any, info: ValidationInfo) -> Any:
        """
        A template need not carry a step_name: every generated step is named
        after its own parameters. It is checked under the indexed step's name.
        """
        if not isinstance(value, dict) or value.get("steptype") in UNNAMED_STEP_TYPES:
            return value
        if value.get("step_name") is None:
            value = dict(value)
            value["step_name"] = info.data.get("step_name", "<the indexed step's>")
        return value

    @field_validator("template")
    @classmethod
    def _template_is_one_ordinary_step(cls, template: Any) -> Any:
        if isinstance(template, SequenceStepSchema):
            _refuse(
                "a Sequence step cannot be the 'template': a sequence is a group "
                "of steps and indexed parametrizes a single step"
            )
        if isinstance(template, IndexedStepSchema):
            _refuse("an indexed step cannot be the 'template'")
        if "id" in template.model_fields_set:
            _refuse("the 'template' cannot carry an 'id': it becomes N steps")
        return template


#: Any one step, picked by its (lowercased) `steptype`.
AnyStepSchema = Annotated[
    PythonModuleStepSchema
    | UserInteractionStepSchema
    | UserWriteStepSchema
    | UserLoadingStepSchema
    | WaitStepSchema
    | SequenceStepSchema
    | IndexedStepSchema,
    Field(discriminator="steptype"),
]

# The template's annotation names AnyStepSchema before it exists.
IndexedStepSchema.model_rebuild()

#: Each steptype's model, keyed as STEP_TYPE_REQUIRED is - for a tool that asks
#: a steptype which keys it takes (the Recipe Creator's hints).
STEP_SCHEMAS: dict[str, type[BaseModel]] = {
    "pythonmodule": PythonModuleStepSchema,
    "userinteraction": UserInteractionStepSchema,
    "userwrite": UserWriteStepSchema,
    "userloading": UserLoadingStepSchema,
    "wait": WaitStepSchema,
    "sequence": SequenceStepSchema,
    "indexed": IndexedStepSchema,
}


# -- sequence ----------------------------------------------------------------------


class SequenceSchema(_RecipeModel):
    """Documents 2 onwards of a recipe: one sequence each."""

    sequence_name: str = Field(
        description=(
            "The sequence's name, unique in the recipe regardless of case. Every "
            "document after the header is a sequence and starts with it."
        ),
        examples=["Main"],
    )
    description: str = Field(default="", description="What the sequence does.")
    image_path: str | None = Field(
        default=None,
        description=(
            "A picture shown while this sequence runs, for every step that has none "
            "of its own: a path relative to the recipe's own folder, or an absolute one."
        ),
        examples=["fixture.png"],
    )
    # A sequence exists to run something; teardown_steps is an optional extra.
    steps: list[AnyStepSchema] = Field(
        min_length=1,
        description="The steps, run in order. A sequence needs at least one.",
        examples=[[{"steptype": "Wait", "step_name": "Pause", "wait_time": 1}]],
    )
    teardown_steps: list[AnyStepSchema] = Field(
        default_factory=list,
        description=(
            "Steps run after 'steps' finish - after a pass, a failure or a stop. "
            "They are written like 'steps'."
        ),
    )


#: Sequence keys the format once had and removed on purpose, with what to do
#: instead. A sequence refuses them as it refuses any unknown key, and the
#: parser gives this sentence as the reason rather than 'Extra inputs'.
REMOVED_SEQUENCE_KEYS: dict[str, str] = {
    "setup_steps": (
        "'setup_steps' was removed. Steps that belonged in setup_steps go at "
        "the front of 'steps' instead."
    ),
    "parameters": (
        "'parameters' was removed. A sequence declares no call interface: a "
        "Sequence step calls it and it shares the run's globals. Remove this key."
    ),
    "outputs": (
        "'outputs' as a sequence-level key was removed (step-level 'outputs' "
        "mappings are still valid). Remove this key from the sequence header."
    ),
    "locals": (
        "'locals' was removed. There is now one scope for the whole run: "
        "'globals'. Declare variables there and read them from a step with "
        "{type: global, global_name: <name>}."
    ),
}

#: Steptype names the format once had, lowercased, with what replaced them -
#: for a tool that answers an unknown steptype with more than the list.
RENAMED_STEP_TYPES: dict[str, str] = {
    "userinteractionstep": "userinteraction",
    "waitstep": "wait",
    "pythonmodulestep": "pythonmodule",
    "userwritestep": "userwrite",
    "userloadingstep": "userloading",
    "sequencestep": "sequence",
    "indexedstep": "indexed",
    "sshconnectstep": "(SSH steps are not yet available in this version)",
    "sshclosestep": "(SSH steps are not yet available in this version)",
}
