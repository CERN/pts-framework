# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Authoritative Pydantic model for the candidate recipe language.

Field declarations intentionally own types, defaults, descriptions, examples,
serialization behavior, and JSON Schema.  There is no parallel field registry.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError


def described(description: str, *, example: Any = None, **kwargs: Any) -> Any:
    """Small spelling helper; returned metadata still lives on each Field."""
    examples = None if example is None else [example]
    return Field(description=description, examples=examples, **kwargs)


class RecipeModel(BaseModel):
    """Strict, immutable base for all authorable structures."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
        validate_default=True,
    )


class DirectInput(RecipeModel):
    """Provides a literal value."""

    type: Literal["direct"] = described("Input source type.", example="direct")
    value: Any = described("Literal input value.", example=1)
    indexed: bool = described(
        "Expand a list into indexed steps.", example=False, default=False,
        exclude_if=lambda value: not value,
    )

    # docs:indexed-direct-start
    @model_validator(mode="after")
    def indexed_values_are_lists(self) -> DirectInput:
        if self.indexed and not isinstance(self.value, list):
            raise PydanticCustomError(
                "invalid_indexed_input", "Indexed direct input value must be a list."
            )
        return self
    # docs:indexed-direct-end


class LocalInput(RecipeModel):
    """Reads a sequence-local variable."""

    type: Literal["local"] = described("Input source type.", example="local")
    local_name: str = described("Local variable name.", example="local_value")


class GlobalInput(RecipeModel):
    """Reads a recipe-global variable."""

    type: Literal["global"] = described("Input source type.", example="global")
    global_name: str = described("Global variable name.", example="global_value")


class MethodInput(RecipeModel):
    """Resolves a method reference for the step."""

    type: Literal["method"] = described("Input source type.", example="method")
    value: Any = described("Method reference.", example="helper")


type InputMapping = Annotated[
    DirectInput | LocalInput | GlobalInput | MethodInput,
    Field(discriminator="type"),
]


class PassFailOutput(RecipeModel):
    """Interprets the output as a pass/fail verdict."""

    type: Literal["passfail"] = described("Output mapping type.", example="passfail")


class EqualsOutput(RecipeModel):
    """Passes when the output equals the configured value."""

    type: Literal["equals"] = described("Output mapping type.", example="equals")
    value: Any = described("Expected value.", example=3)


class RangeOutput(RecipeModel):
    """Passes when the output is within an inclusive range."""

    type: Literal["range"] = described("Output mapping type.", example="range")
    minimum: Any = described("Minimum accepted value.", example=1, alias="min")
    maximum: Any = described("Maximum accepted value.", example=4, alias="max")


class PassthroughOutput(RecipeModel):
    """Uses the nested result without adding a verdict."""

    type: Literal["passthrough"] = described("Output mapping type.", example="passthrough")


class LocalOutput(RecipeModel):
    """Stores the output in a sequence-local variable."""

    type: Literal["local"] = described("Output mapping type.", example="local")
    local_name: str = described("Local destination variable.", example="saved")


class GlobalOutput(RecipeModel):
    """Stores the output in a recipe-global variable."""

    type: Literal["global"] = described("Output mapping type.", example="global")
    global_name: str = described("Global destination variable.", example="saved")


class ImageOutput(RecipeModel):
    """Publishes an image output for presentation."""

    type: Literal["image"] = described("Output mapping type.", example="image")


type OutputMapping = Annotated[
    PassFailOutput
    | EqualsOutput
    | RangeOutput
    | PassthroughOutput
    | LocalOutput
    | GlobalOutput
    | ImageOutput,
    Field(discriminator="type"),
]


class InternalSequenceReference(RecipeModel):
    """Reference to another sequence in this recipe."""

    type: Literal["internal"] = described("Reference kind.", example="internal")
    name: str = described("Target sequence name.", example="Calibration")


class FileDestination(RecipeModel):
    """Destination used by a file-loading step."""

    type: Literal["local", "global"] = described("Variable scope.", example="local")
    variable: str = described("Destination variable name.", example="selected_file")


class UploadFile(RecipeModel):
    """One local-to-remote SSH upload pair."""

    local: str = described("Local file or package resource.", example="bin/tool")
    remote: str = described("Remote destination path.", example="/tmp/tool")


class CommonStep(RecipeModel):
    """Fields shared by every authorable step."""

    step_name: str = described("Human-readable step name.", example="Run test")
    description: str = described("Purpose of the step.", example="Run a test operation.")
    id: str | None = described("Optional stable step identifier.", example="test-1", default=None)
    skip: bool = described("Skip execution.", example=False, default=False)
    critical: bool = described(
        "Stop on error when policy permits continuation.", example=False, default=False
    )
    continue_on_error: bool = described("Per-step error policy.", example=False, default=False)
    input_mapping: dict[str, InputMapping] = described(
        "Named input sources.", example={}, default_factory=dict
    )
    output_mapping: dict[str, OutputMapping] = described(
        "Named verdicts and destinations.", example={}, default_factory=dict
    )


class PythonModuleStep(CommonStep):
    """Calls a method or reads/writes an attribute in a Python module."""

    steptype: Literal["PythonModuleStep"] = described(
        "Canonical registered step type.", example="PythonModuleStep"
    )
    action_type: Literal["method", "read_attribute", "write_attribute"] = described(
        "Operation performed on the Python module.", example="method"
    )
    module: str = described("Python module path.", example="tests.py")
    method_name: str | None = described("Method name for method actions.", example="run", default=None)

    # docs:method-name-start
    @model_validator(mode="after")
    def method_actions_have_names(self) -> PythonModuleStep:
        if self.action_type == "method" and not self.method_name:
            raise PydanticCustomError(
                "missing_method_name", "Method actions require method_name."
            )
        return self
    # docs:method-name-end


class SequenceStep(CommonStep):
    """Runs another sequence as a step."""

    steptype: Literal["SequenceStep"] = described(
        "Canonical registered step type.", example="SequenceStep"
    )
    sequence: InternalSequenceReference = described(
        "Internal sequence reference.", example={"type": "internal", "name": "Calibration"}
    )


class UserInteractionStep(CommonStep):
    """Displays an operator interaction prompt."""

    steptype: Literal["UserInteractionStep"] = described(
        "Canonical registered step type.", example="UserInteractionStep"
    )


class WaitStep(CommonStep):
    """Waits for a non-negative duration in seconds."""

    steptype: Literal["WaitStep"] = described("Canonical registered step type.", example="WaitStep")

    # docs:wait-time-start
    @model_validator(mode="after")
    def has_wait_time(self) -> WaitStep:
        if "wait_time" not in self.input_mapping:
            raise PydanticCustomError("missing_required_input", "WaitStep requires input 'wait_time'.")
        return self
    # docs:wait-time-end


class UserLoadingStep(CommonStep):
    """Prompts the operator to select a file."""

    steptype: Literal["UserLoadingStep"] = described(
        "Canonical registered step type.", example="UserLoadingStep"
    )
    file_save_location: FileDestination | None = described(
        "Local or global destination for the selected file.",
        example={"type": "local", "variable": "selected_file"},
        default=None,
    )


class UserRunMethodStep(CommonStep):
    """Optionally runs a Python method after an operator response."""

    steptype: Literal["UserRunMethodStep"] = described(
        "Canonical registered step type.", example="UserRunMethodStep"
    )
    trigger_response: str | list[Any] | dict[str, Any] | None = described(
        "Operator response that triggers execution.", example="run", default=None
    )
    action_type: str | None = described("Optional Python action type.", example="method", default=None)
    module: str | None = described("Optional Python module path.", example="tests.py", default=None)
    method_name: str | None = described("Optional Python method name.", example="run", default=None)


class UserWriteStep(CommonStep):
    """Writes an operator-provided value to a configured destination."""

    steptype: Literal["UserWriteStep"] = described(
        "Canonical registered step type.", example="UserWriteStep"
    )


class SerialNumberStep(CommonStep):
    """Captures the device serial number."""

    steptype: Literal["SerialNumberStep"] = described(
        "Canonical registered step type.", example="SerialNumberStep"
    )


class SSHConnectStep(CommonStep):
    """Opens the SSH client stored in recipe globals."""

    steptype: Literal["SSHConnectStep"] = described(
        "Canonical registered step type.", example="SSHConnectStep"
    )


class SSHCloseStep(CommonStep):
    """Closes the SSH client stored in recipe globals."""

    steptype: Literal["SSHCloseStep"] = described(
        "Canonical registered step type.", example="SSHCloseStep"
    )


class SSHUploadStep(CommonStep):
    """Uploads files through an SSH connection."""

    steptype: Literal["SSHUploadStep"] = described(
        "Canonical registered step type.", example="SSHUploadStep"
    )
    files: list[UploadFile] = described(
        "Local and remote file pairs to upload.",
        example=[{"local": "bin/tool", "remote": "/tmp/tool"}],
    )
    permissions: int | str | None = described(
        "Optional remote permissions.", example="0755", default=None
    )
    skip_if_sha256_match: bool = described(
        "Skip files whose remote checksum matches.", example=False, default=False
    )
    local_package: str | None = described(
        "Optional package containing local resources.", example="my_package", default=None
    )


type Step = Annotated[
    PythonModuleStep
    | SequenceStep
    | UserInteractionStep
    | WaitStep
    | UserLoadingStep
    | UserRunMethodStep
    | UserWriteStep
    | SerialNumberStep
    | SSHConnectStep
    | SSHCloseStep
    | SSHUploadStep,
    Field(discriminator="steptype"),
]


class RecipeHeader(RecipeModel):
    """The first YAML document, identifying a recipe and its entry sequence."""

    name: str = described("Human-readable recipe name.", example="Hardware acceptance")
    version: str = described("Version of this recipe.", example="1.0")
    recipe_version: Literal["2.0.0"] = described(
        "Version of the recipe language contract.", example="2.0.0"
    )
    description: str = described("Purpose of the recipe.", example="Acceptance tests.")
    main_sequence: str = described("Sequence where execution begins.", example="Main")
    globals: dict[str, Any] = described("Recipe-wide variables.", example={})
    continue_on_error: bool | None = described(
        "Recipe-wide error policy.", example=False, default=None
    )
    report: Literal["overwrite", "append"] = described(
        "Report file mode.", example="overwrite", default="overwrite"
    )
    report_name_include_serial: bool = described(
        "Include the serial number in the report name.", example=False, default=False
    )
    test_package: str | None = described(
        "Package containing recipe test modules.", example="acceptance", default=None
    )


class Sequence(RecipeModel):
    """One named executable sequence document."""

    sequence_name: str = described("Unique sequence name.", example="Main")
    description: str = described("Purpose of the sequence.", example="Main sequence.")
    parameters: dict[str, Any] = described("Reserved sequence input metadata.", example={})
    outputs: dict[str, Any] = described("Reserved sequence output metadata.", example={})
    locals: dict[str, Any] = described("Variables local to the sequence.", example={})
    setup_steps: list[Step] = described("Steps run before the main steps.", example=[])
    steps: list[Step] = described("Ordered main steps.", example=[])
    teardown_steps: list[Step] = described("Steps run during teardown.", example=[])


class Recipe(RecipeModel):
    """Aggregate typed recipe used by tooling and JSON Schema consumers."""

    header: RecipeHeader = described("Recipe header document.")
    sequences: list[Sequence] = described("Sequence documents.", min_length=1)


def _union_models(annotation: Any) -> tuple[type[RecipeModel], ...]:
    """Expose union members for generators without a second registry."""
    annotation = getattr(annotation, "__value__", annotation)
    annotated_union = get_args(annotation)[0]
    return get_args(annotated_union)


STEP_MODELS = _union_models(Step)
INPUT_MODELS = _union_models(InputMapping)
OUTPUT_MODELS = _union_models(OutputMapping)
