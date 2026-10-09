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
    # A UserLoading asks for a path: `select` says whether a file or a folder,
    # and anything but those two words (case-insensitive) is refused by the
    # step's constructor when the recipe loads. The chosen path is the output.
    "userloading": {"select": "file", "image_path": None, "outputs": {}},
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
    Unknown keys are ignored unless a model says otherwise - a step does.
    """

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

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


class HeaderSchema(_RecipeModel):
    """Document 1 of a recipe."""

    name: str
    version: str
    description: str = ""
    main_sequence: str = ""
    globals: dict[Any, Any] = Field(default_factory=dict)
    # Strict: a column called `3` is a mistake, not a name to coerce.
    report_metadata: list[Annotated[StrictStr, AfterValidator(_report_name)]] = Field(
        default_factory=lambda: list(REPORT_METADATA_DEFAULT)
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
    if declared not in INPUT_TYPES:
        _refuse(f"unknown type '{declared}'. Available: {known}")
    for key in INPUT_TYPES[declared]:
        if value.get(key) is None:
            _refuse(f"a '{declared}' entry needs '{key}'")
    return value


InputEntry = Annotated[Any, AfterValidator(_input_entry)]


class PassOutput(_RecipeModel):
    type: Literal["pass"]


class PassfailOutput(_RecipeModel):
    type: Literal["passfail"]


class EqualsOutput(_RecipeModel):
    type: Literal["equals"]
    value: Any


class RangeOutput(_RecipeModel):
    type: Literal["range"]
    min: Any
    max: Any


class GlobalOutput(_RecipeModel):
    type: Literal["global"]
    global_name: Any


#: One `outputs` entry, picked by its `type` (OUTPUT_TYPES).
OutputEntry = Annotated[
    PassOutput | PassfailOutput | EqualsOutput | RangeOutput | GlobalOutput,
    Field(discriminator="type"),
]


# -- steps -------------------------------------------------------------------------


class _StepFields(_RecipeModel):
    """STEP_COMMON_DEFAULTS: what every steptype accepts. A step refuses unknown keys."""

    model_config = ConfigDict(extra="forbid")

    description: str = ""
    skip: bool = False
    continue_on_error: bool = True


class _OrdinaryStep(_StepFields):
    """The arguments of pypts.step.step.Step's constructor, which every built step takes."""

    step_name: str
    id: str = ""
    inputs: dict[Any, InputEntry] = Field(default_factory=dict)
    outputs: dict[Any, OutputEntry] = Field(default_factory=dict)


class PythonModuleStepSchema(_OrdinaryStep):
    steptype: Literal["pythonmodule"]
    module: str
    method_name: str


class UserInteractionStepSchema(_OrdinaryStep):
    steptype: Literal["userinteraction"]
    message: str
    options: Any
    image_path: str | None = None


class UserWriteStepSchema(_OrdinaryStep):
    steptype: Literal["userwrite"]
    message: str
    image_path: str | None = None


class UserLoadingStepSchema(_OrdinaryStep):
    steptype: Literal["userloading"]
    message: str
    select: str = "file"
    image_path: str | None = None


class WaitStepSchema(_OrdinaryStep):
    steptype: Literal["wait"]
    wait_time: Any


class SequenceStepSchema(_StepFields):
    """
    A call of another sequence. Named after it, so it takes no step_name.

    The keys in sequence_step.REFUSED_KEYS are declared only to be refused with
    their reason; a plain unknown key would say no more than 'Extra inputs'.
    """

    steptype: Literal["sequence"]
    sequence_name: str
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

    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, Any] = Field(default_factory=dict)
    expect: dict[str, Any] = Field(default_factory=dict)

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

    steptype: Literal["indexed"]
    step_name: str
    template: "AnyStepSchema"
    parameter_sets: list[ParameterSet] = Field(min_length=1)
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

    sequence_name: str
    description: str = ""
    # A sequence exists to run something; teardown_steps is an optional extra.
    steps: list[AnyStepSchema] = Field(min_length=1)
    teardown_steps: list[AnyStepSchema] = Field(default_factory=list)
