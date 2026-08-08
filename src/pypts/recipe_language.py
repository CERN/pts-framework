# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""The framework-independent contract for the recipe YAML language.

This module deliberately accepts already-loaded Python dictionaries.  Loading
YAML, retaining source locations, and constructing runtime steps are separate
concerns which will be introduced by the parser and integration work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


CANONICAL_RECIPE_VERSION = "1.0.0"


@dataclass(frozen=True)
class SourcePosition:
    """A one-based source position with a zero-based character offset."""

    line: int
    column: int
    offset: int


@dataclass(frozen=True)
class SourceSpan:
    """Half-open source range."""

    start: SourcePosition
    end: SourcePosition


@dataclass(frozen=True)
class Diagnostic:
    """A language-contract finding for an already-loaded recipe document."""

    code: str
    message: str
    path: tuple[str | int, ...] = ()
    severity: str = "error"
    source_name: str | None = None
    span: SourceSpan | None = None


@dataclass(frozen=True)
class ValidationResult:
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class FieldSpec:
    name: str
    value_type: type | tuple[type, ...] | None = None
    required: bool = False
    description: str = ""


@dataclass(frozen=True)
class StepSpec:
    """Declarative contract for one registered recipe step type."""

    name: str
    fields: tuple[FieldSpec, ...] = ()
    required_inputs: tuple[str, ...] = ()
    example: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""
    source_allowed: bool = True

    @property
    def fields_by_name(self) -> dict[str, FieldSpec]:
        return {field.name: field for field in self.fields}


COMMON_STEP_FIELDS = (
    FieldSpec("steptype", str, required=True, description="Registered step type."),
    FieldSpec("step_name", str, required=True, description="Human-readable step name."),
    FieldSpec("description", str, required=True, description="Purpose of the step."),
    FieldSpec("id", str, description="Optional stable step identifier."),
    FieldSpec("skip", bool, description="Skip execution; defaults to false."),
    FieldSpec("critical", bool, description="Stop on error when policy permits continuation."),
    FieldSpec("continue_on_error", bool, description="Per-step error policy."),
    FieldSpec("input_mapping", dict, description="Named input sources."),
    FieldSpec("output_mapping", dict, description="Named verdicts and destinations."),
)


def _step_spec(
    name: str,
    *fields: FieldSpec,
    required_inputs: tuple[str, ...] = (),
    example: Mapping[str, Any],
    description: str,
    source_allowed: bool = True,
) -> StepSpec:
    return StepSpec(name, COMMON_STEP_FIELDS + fields, required_inputs, example, description, source_allowed)


STEP_SPECS = (
    _step_spec(
        "PythonModuleStep",
        FieldSpec("action_type", str, required=True),
        FieldSpec("module", str, required=True),
        FieldSpec("method_name", str),
        example={"steptype": "PythonModuleStep", "step_name": "Run test", "description": "Run a Python test method.", "action_type": "method", "module": "tests.py", "method_name": "run", "input_mapping": {}, "output_mapping": {}},
        description="Calls a method or reads/writes an attribute in a Python module.",
    ),
    _step_spec(
        "SequenceStep",
        FieldSpec("sequence", dict, required=True),
        example={"steptype": "SequenceStep", "step_name": "Run calibration", "description": "Run an internal sequence.", "sequence": {"type": "internal", "name": "Calibration"}, "input_mapping": {}, "output_mapping": {}},
        description="Runs another sequence as a step.",
    ),
    _step_spec(
        "UserInteractionStep",
        example={"steptype": "UserInteractionStep", "step_name": "Confirm", "description": "Ask the operator to confirm.", "input_mapping": {"message": {"type": "direct", "value": "Continue?"}}, "output_mapping": {"output": {"type": "passfail"}}},
        description="Displays an operator interaction prompt.",
    ),
    _step_spec(
        "WaitStep",
        required_inputs=("wait_time",),
        example={"steptype": "WaitStep", "step_name": "Stabilize", "description": "Wait for hardware stabilization.", "input_mapping": {"wait_time": {"type": "direct", "value": 1}}, "output_mapping": {}},
        description="Waits for a non-negative duration in seconds.",
    ),
    _step_spec(
        "UserLoadingStep",
        FieldSpec("file_save_location", dict),
        example={"steptype": "UserLoadingStep", "step_name": "Load configuration", "description": "Ask the operator for a file.", "input_mapping": {"message": {"type": "direct", "value": "Choose a file"}}, "output_mapping": {"output": {"type": "passfail"}}},
        description="Prompts the operator to select a file.",
    ),
    _step_spec(
        "UserRunMethodStep",
        FieldSpec("trigger_response", (str, list, dict)),
        FieldSpec("action_type", str),
        FieldSpec("module", str),
        FieldSpec("method_name", str),
        example={"steptype": "UserRunMethodStep", "step_name": "Run calibration", "description": "Run on operator confirmation.", "trigger_response": "run", "action_type": "method", "module": "tests.py", "method_name": "calibrate", "input_mapping": {}, "output_mapping": {"output": {"type": "passfail"}}},
        description="Optionally runs a Python method after an operator response.",
    ),
    _step_spec(
        "UserWriteStep",
        example={"steptype": "UserWriteStep", "step_name": "Enter value", "description": "Ask the operator for a value.", "input_mapping": {"message": {"type": "direct", "value": "Enter value"}}, "output_mapping": {"output": {"type": "local", "local_name": "value"}}},
        description="Writes an operator-provided value to a configured destination.",
    ),
    _step_spec(
        "SerialNumberStep",
        example={"steptype": "SerialNumberStep", "step_name": "Scan serial number", "description": "Capture the device serial number.", "input_mapping": {}, "output_mapping": {}},
        description="Captures the device serial number.",
    ),
    _step_spec(
        "SSHConnectStep",
        example={"steptype": "SSHConnectStep", "step_name": "Connect", "description": "Open the SSH connection."},
        description="Opens the SSH client stored in recipe globals.",
    ),
    _step_spec(
        "SSHCloseStep",
        example={"steptype": "SSHCloseStep", "step_name": "Disconnect", "description": "Close the SSH connection."},
        description="Closes the SSH client stored in recipe globals.",
    ),
    _step_spec(
        "SSHUploadStep",
        FieldSpec("files", list, required=True),
        FieldSpec("permissions", (int, str)),
        FieldSpec("skip_if_sha256_match", bool),
        FieldSpec("local_package", str),
        example={"steptype": "SSHUploadStep", "step_name": "Deploy", "description": "Upload a file to the target.", "files": [{"local": "bin/tool", "remote": "/tmp/tool"}], "output_mapping": {"passed": {"type": "passfail"}}},
        description="Uploads files through an SSH connection.",
    ),
    _step_spec(
        "IndexedStep",
        example={"steptype": "IndexedStep", "step_name": "Indexed operation", "description": "Reserved runtime wrapper step.", "input_mapping": {}, "output_mapping": {}},
        description="Reserved for the runtime's automatic indexed-step wrapper.",
        source_allowed=False,
    ),
)

STEP_SPECS_BY_NAME = {spec.name.casefold(): spec for spec in STEP_SPECS}

HEADER_FIELDS = (
    FieldSpec("name", str, required=True), FieldSpec("version", str, required=True),
    FieldSpec("recipe_version", str, required=True), FieldSpec("description", str, required=True),
    FieldSpec("main_sequence", str, required=True), FieldSpec("globals", dict, required=True),
    FieldSpec("continue_on_error", bool), FieldSpec("report", str),
    FieldSpec("report_name_include_serial", bool), FieldSpec("test_package", str),
)
SEQUENCE_FIELDS = (
    FieldSpec("sequence_name", str, required=True), FieldSpec("description", str, required=True),
    FieldSpec("parameters", dict, required=True), FieldSpec("outputs", dict, required=True),
    FieldSpec("locals", dict, required=True), FieldSpec("setup_steps", list, required=True),
    FieldSpec("steps", list, required=True), FieldSpec("teardown_steps", list, required=True),
    FieldSpec("serial_number", (str, int), description="Legacy runtime-ignored sequence metadata."),
)


def canonical_step_type(step_type: str) -> str | None:
    spec = STEP_SPECS_BY_NAME.get(step_type.casefold()) if isinstance(step_type, str) else None
    return spec.name if spec else None


def _type_name(value_type: type | tuple[type, ...]) -> str:
    values = value_type if isinstance(value_type, tuple) else (value_type,)
    return " or ".join(value.__name__ for value in values)


def _check_fields(value: Mapping[str, Any], fields: Iterable[FieldSpec], path: tuple[str | int, ...], diagnostics: list[Diagnostic]) -> None:
    specs = {spec.name: spec for spec in fields}
    for name, spec in specs.items():
        if spec.required and name not in value:
            diagnostics.append(Diagnostic("missing-field", f"Missing required field '{name}'.", path + (name,)))
        elif name in value and spec.value_type is not None and (type(value[name]) is not bool if spec.value_type is bool else not isinstance(value[name], spec.value_type)):
            diagnostics.append(Diagnostic("invalid-field-type", f"Field '{name}' must be {_type_name(spec.value_type)}.", path + (name,)))
    for name in value:
        if name not in specs:
            diagnostics.append(Diagnostic("unknown-field", f"Unknown field '{name}'.", path + (name,)))


def _validate_input_mappings(mapping: Mapping[str, Any], path: tuple[str | int, ...], diagnostics: list[Diagnostic]) -> None:
    indexed_lengths: list[int] = []
    for name, config in mapping.items():
        item_path = path + (name,)
        if not isinstance(config, Mapping):
            diagnostics.append(Diagnostic("invalid-input-mapping", "Input mapping must be a dictionary.", item_path))
            continue
        source = config.get("type", "direct")
        if source not in {"direct", "local", "global", "method"}:
            diagnostics.append(Diagnostic("unknown-input-source", f"Unknown input source '{source}'.", item_path + ("type",)))
            continue
        allowed = {
            "direct": {"type", "value", "indexed"},
            "local": {"type", "local_name", "indexed"},
            "global": {"type", "global_name", "indexed"},
            "method": {"type", "value", "indexed"},
        }[source]
        for field_name in config:
            if field_name not in allowed:
                diagnostics.append(Diagnostic("unknown-input-field", f"Unknown field '{field_name}' for input source '{source}'.", item_path + (field_name,)))
        required_key = {"direct": "value", "local": "local_name", "global": "global_name", "method": "value"}[source]
        if required_key not in config:
            diagnostics.append(Diagnostic("missing-input-source-value", f"Input source '{source}' requires '{required_key}'.", item_path))
        if "indexed" in config and type(config["indexed"]) is not bool:
            diagnostics.append(Diagnostic("invalid-indexed-flag", "'indexed' must be boolean.", item_path + ("indexed",)))
        if config.get("indexed"):
            if source != "direct" or not isinstance(config.get("value"), list):
                diagnostics.append(Diagnostic("invalid-indexed-input", "Indexed inputs must be direct lists.", item_path))
            else:
                indexed_lengths.append(len(config["value"]))
    if len(set(indexed_lengths)) > 1:
        diagnostics.append(Diagnostic("unequal-indexed-inputs", "Indexed input lists must have equal lengths.", path))


def _validate_output_mappings(mapping: Mapping[str, Any], path: tuple[str | int, ...], diagnostics: list[Diagnostic]) -> None:
    verdicts: list[str] = []
    requirements = {"equals": "value", "range": ("min", "max"), "local": "local_name", "global": "global_name"}
    for name, config in mapping.items():
        item_path = path + (name,)
        if not isinstance(config, Mapping) or not isinstance(config.get("type"), str):
            diagnostics.append(Diagnostic("invalid-output-mapping", "Output mapping requires a string 'type'.", item_path))
            continue
        kind = config["type"]
        if kind not in {"passfail", "equals", "range", "passthrough", "local", "global", "image"}:
            diagnostics.append(Diagnostic("unknown-output-type", f"Unknown output type '{kind}'.", item_path + ("type",)))
            continue
        allowed = {
            "passfail": {"type"}, "equals": {"type", "value"},
            "range": {"type", "min", "max"}, "passthrough": {"type"},
            "local": {"type", "local_name"}, "global": {"type", "global_name"},
            "image": {"type"},
        }[kind]
        for field_name in config:
            if field_name not in allowed:
                diagnostics.append(Diagnostic("unknown-output-field", f"Unknown field '{field_name}' for output type '{kind}'.", item_path + (field_name,)))
        if kind in {"passfail", "equals", "range", "passthrough"}:
            verdicts.append(kind)
        required = requirements.get(kind, ())
        required = (required,) if isinstance(required, str) else required
        for field_name in required:
            if field_name not in config:
                diagnostics.append(Diagnostic("missing-output-field", f"Output type '{kind}' requires '{field_name}'.", item_path))
    if "passthrough" in verdicts and len(verdicts) != 1:
        diagnostics.append(Diagnostic("mixed-passthrough", "'passthrough' must be the sole verdict mapping.", path))


def _validate_step(step: Any, path: tuple[str | int, ...], diagnostics: list[Diagnostic]) -> str | None:
    if not isinstance(step, Mapping):
        diagnostics.append(Diagnostic("invalid-step", "Step must be a dictionary.", path))
        return None
    step_type = step.get("steptype")
    canonical_name = canonical_step_type(step_type)
    if canonical_name is None:
        diagnostics.append(Diagnostic("unknown-step-type", f"Unknown step type '{step_type}'.", path + ("steptype",)))
        return None
    spec = STEP_SPECS_BY_NAME[canonical_name.casefold()]
    if not spec.source_allowed:
        diagnostics.append(Diagnostic("internal-step-type", f"{canonical_name} is created by the runtime and cannot be written in a recipe.", path + ("steptype",)))
        return canonical_name
    _check_fields(step, spec.fields, path, diagnostics)
    if "input_mapping" in step and isinstance(step["input_mapping"], Mapping):
        _validate_input_mappings(step["input_mapping"], path + ("input_mapping",), diagnostics)
        for required in spec.required_inputs:
            if required not in step["input_mapping"]:
                diagnostics.append(Diagnostic("missing-required-input", f"{canonical_name} requires input '{required}'.", path + ("input_mapping", required)))
    elif spec.required_inputs:
        diagnostics.append(Diagnostic("missing-input-mapping", f"{canonical_name} requires an input_mapping.", path + ("input_mapping",)))
    if "output_mapping" in step and isinstance(step["output_mapping"], Mapping):
        _validate_output_mappings(step["output_mapping"], path + ("output_mapping",), diagnostics)
    if canonical_name == "PythonModuleStep":
        if step.get("action_type") not in {"method", "read_attribute", "write_attribute"}:
            diagnostics.append(Diagnostic("invalid-action-type", "PythonModuleStep action_type must be method, read_attribute, or write_attribute.", path + ("action_type",)))
        if step.get("action_type") == "method" and not step.get("method_name"):
            diagnostics.append(Diagnostic("missing-method-name", "PythonModuleStep method action requires method_name.", path + ("method_name",)))
    if canonical_name == "SequenceStep":
        sequence = step.get("sequence")
        if not isinstance(sequence, Mapping) or sequence.get("type") != "internal" or not isinstance(sequence.get("name"), str):
            diagnostics.append(Diagnostic("invalid-sequence-reference", "SequenceStep requires sequence.type 'internal' and string sequence.name.", path + ("sequence",)))
    if canonical_name == "UserLoadingStep" and "file_save_location" in step:
        location = step["file_save_location"]
        if not isinstance(location, Mapping) or location.get("type") not in {"local", "global"} or not isinstance(location.get("variable"), str):
            diagnostics.append(Diagnostic("invalid-file-save-location", "file_save_location requires type local/global and string variable.", path + ("file_save_location",)))
    return canonical_name


def validate_recipe_documents(documents: Iterable[Any]) -> ValidationResult:
    """Validate already-loaded documents against the canonical language model.

    The function has no YAML dependency and intentionally performs no runtime
    imports or execution.  A future parser will supply source spans and YAML
    loading before calling this contract validator.
    """
    docs = list(documents)
    diagnostics: list[Diagnostic] = []
    if not docs:
        return ValidationResult((Diagnostic("empty-recipe", "A recipe requires a header and at least one sequence."),))
    header = docs[0]
    if not isinstance(header, Mapping):
        return ValidationResult((Diagnostic("invalid-header", "The first document must be the recipe header.", (0,)),))
    _check_fields(header, HEADER_FIELDS, (0,), diagnostics)
    if header.get("recipe_version") != CANONICAL_RECIPE_VERSION:
        diagnostics.append(Diagnostic("unsupported-recipe-version", f"recipe_version must be '{CANONICAL_RECIPE_VERSION}'.", (0, "recipe_version")))
    if "report" in header and header.get("report") not in {"overwrite", "append"}:
        diagnostics.append(Diagnostic("invalid-report-mode", "report must be 'overwrite' or 'append'.", (0, "report")))
    sequences: dict[str, Mapping[str, Any]] = {}
    sequence_step_types: dict[str, dict[str, list[str]]] = {}
    for doc_index, sequence in enumerate(docs[1:], start=1):
        path = (doc_index,)
        if not isinstance(sequence, Mapping):
            diagnostics.append(Diagnostic("invalid-sequence", "Sequence document must be a dictionary.", path))
            continue
        _check_fields(sequence, SEQUENCE_FIELDS, path, diagnostics)
        name = sequence.get("sequence_name")
        if isinstance(name, str):
            if name in sequences:
                diagnostics.append(Diagnostic("duplicate-sequence", f"Duplicate sequence '{name}'.", path + ("sequence_name",)))
            sequences[name] = sequence
        if "serial_number" in sequence:
            diagnostics.append(Diagnostic("legacy-sequence-field", "'serial_number' is runtime-ignored legacy metadata.", path + ("serial_number",), "warning"))
        sections: dict[str, list[str]] = {}
        for section in ("setup_steps", "steps", "teardown_steps"):
            values = sequence.get(section, [])
            section_types: list[str] = []
            if isinstance(values, list):
                for index, step in enumerate(values):
                    step_type = _validate_step(step, path + (section, index), diagnostics)
                    if step_type:
                        section_types.append(step_type)
            sections[section] = section_types
        if isinstance(name, str):
            sequence_step_types[name] = sections
    if isinstance(header, Mapping) and isinstance(header.get("main_sequence"), str) and header["main_sequence"] not in sequences:
        diagnostics.append(Diagnostic("unknown-main-sequence", f"Main sequence '{header['main_sequence']}' does not exist.", (0, "main_sequence")))
    for sequence_name, sequence in sequences.items():
        for section in ("setup_steps", "steps", "teardown_steps"):
            for index, step in enumerate(sequence.get(section, [])):
                if isinstance(step, Mapping) and canonical_step_type(step.get("steptype")) == "SequenceStep":
                    target = step.get("sequence", {}).get("name") if isinstance(step.get("sequence"), Mapping) else None
                    if isinstance(target, str) and target not in sequences:
                        diagnostics.append(Diagnostic("unknown-sequence-reference", f"Sequence '{sequence_name}' references unknown sequence '{target}'.", (sequence_name, section, index, "sequence", "name")))
        kinds = sequence_step_types.get(sequence_name, {})
        all_types = [kind for values in kinds.values() for kind in values]
        if any(kind.startswith("SSH") for kind in all_types):
            globals_data = header.get("globals", {}) if isinstance(header, Mapping) else {}
            for required in ("ssh_client", "host", "user", "port"):
                if required not in globals_data:
                    diagnostics.append(Diagnostic("missing-ssh-global", f"SSH step requires global '{required}'.", (0, "globals", required)))
            if "password" not in globals_data and "private_key" not in globals_data:
                diagnostics.append(Diagnostic("missing-ssh-credential", "SSH steps require password or private_key global.", (0, "globals")))
        if "SSHUploadStep" in kinds.get("steps", []) and "SSHConnectStep" not in kinds.get("setup_steps", []):
            diagnostics.append(Diagnostic("missing-ssh-connect", f"Sequence '{sequence_name}' uses SSHUploadStep without setup SSHConnectStep.", (sequence_name, "steps")))
        if "SSHConnectStep" in kinds.get("setup_steps", []) and "SSHCloseStep" not in kinds.get("teardown_steps", []):
            diagnostics.append(Diagnostic("missing-ssh-close", f"Sequence '{sequence_name}' setup SSHConnectStep requires teardown SSHCloseStep.", (sequence_name, "teardown_steps")))
    return ValidationResult(tuple(diagnostics))
