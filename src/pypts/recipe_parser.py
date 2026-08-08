# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Safe, source-aware parsing for the pypts recipe language.

The parser is intentionally isolated from recipe execution and GUI code.  It
turns YAML into immutable definitions after validation by
``pypts.recipe_language``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TypeAlias

import yaml

from pypts.recipe_language import (
    Diagnostic,
    SourcePosition,
    SourceSpan,
    STEP_SPECS_BY_NAME,
    canonical_step_type,
    validate_recipe_documents,
)


RecipePath: TypeAlias = tuple[str | int, ...]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenMap((str(key), _freeze(item)) for key, item in value.items())
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, FrozenMap):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return set(_thaw(item) for item in value)
    return value


@dataclass(frozen=True, eq=False)
class FrozenMap(Mapping[str, Any]):
    """Small insertion-ordered immutable mapping used by parsed models."""

    entries: tuple[tuple[str, Any], ...] = ()

    def __init__(self, entries=()):
        object.__setattr__(self, "entries", tuple(entries))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "FrozenMap":
        return cls((str(key), _freeze(item)) for key, item in (value or {}).items())

    def __getitem__(self, key: str) -> Any:
        for candidate, value in self.entries:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping) or len(self) != len(other):
            return False
        return all(key in other and value == other[key] for key, value in self.items())

    def __hash__(self) -> int:
        return hash(frozenset(self.entries))


@dataclass(frozen=True)
class DirectInput:
    value: Any
    indexed: bool = False
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class LocalInput:
    local_name: str
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class GlobalInput:
    global_name: str
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class MethodInput:
    value: Any
    span: SourceSpan | None = field(default=None, compare=False)


InputDefinition: TypeAlias = DirectInput | LocalInput | GlobalInput | MethodInput


@dataclass(frozen=True)
class PassFailOutput:
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class EqualsOutput:
    value: Any
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class RangeOutput:
    minimum: Any
    maximum: Any
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class PassthroughOutput:
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class LocalOutput:
    local_name: str
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class GlobalOutput:
    global_name: str
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class ImageOutput:
    span: SourceSpan | None = field(default=None, compare=False)


OutputDefinition: TypeAlias = (
    PassFailOutput | EqualsOutput | RangeOutput | PassthroughOutput |
    LocalOutput | GlobalOutput | ImageOutput
)


@dataclass(frozen=True)
class StepDefinition:
    steptype: str
    step_name: str
    description: str
    id: str | None
    skip: bool
    critical: bool
    continue_on_error: bool
    input_mapping: FrozenMap
    output_mapping: FrozenMap
    configuration: FrozenMap
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class SequenceDefinition:
    sequence_name: str
    description: str
    parameters: FrozenMap
    outputs: FrozenMap
    locals: FrozenMap
    setup_steps: tuple[StepDefinition, ...]
    steps: tuple[StepDefinition, ...]
    teardown_steps: tuple[StepDefinition, ...]
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class RecipeHeader:
    name: str
    version: str
    recipe_version: str
    description: str
    main_sequence: str
    globals: FrozenMap
    continue_on_error: bool | None
    report: str
    report_name_include_serial: bool
    test_package: str | None
    span: SourceSpan | None = field(default=None, compare=False)


@dataclass(frozen=True)
class RecipeDefinition:
    header: RecipeHeader
    sequences: tuple[SequenceDefinition, ...]
    source_name: str = field(default="<memory>", compare=False)
    span: SourceSpan | None = field(default=None, compare=False)


class RecipeParseError(ValueError):
    """Raised when a caller requires a recipe from an unsuccessful parse."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]):
        self.diagnostics = diagnostics
        errors = sum(item.severity == "error" for item in diagnostics)
        super().__init__(f"Recipe parsing failed with {errors} error(s).")


@dataclass(frozen=True)
class ParseResult:
    recipe: RecipeDefinition | None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return self.recipe is not None and not self.errors

    def require_recipe(self) -> RecipeDefinition:
        if self.recipe is None or self.errors:
            raise RecipeParseError(self.diagnostics)
        return self.recipe


def _position(mark: yaml.error.Mark) -> SourcePosition:
    return SourcePosition(mark.line + 1, mark.column + 1, mark.index)


def _span(node: yaml.Node) -> SourceSpan:
    return SourceSpan(_position(node.start_mark), _position(node.end_mark))


def _mark_span(mark: yaml.error.Mark | None) -> SourceSpan | None:
    if mark is None:
        return None
    position = _position(mark)
    return SourceSpan(position, position)


def _index_nodes(
    node: yaml.Node,
    path: RecipePath,
    spans: dict[RecipePath, SourceSpan],
    diagnostics: list[Diagnostic],
    source_name: str,
    active: set[int],
) -> None:
    spans[path] = _span(node)
    node_id = id(node)
    if node_id in active:
        diagnostics.append(Diagnostic(
            "recursive-alias", "Recursive YAML aliases are not supported.", path,
            source_name=source_name, span=_span(node),
        ))
        return
    active.add(node_id)
    try:
        if isinstance(node, yaml.MappingNode):
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode):
                    identity = (key_node.tag, key_node.value)
                    key: str | int = key_node.value
                else:
                    identity = (key_node.tag, repr(key_node.value))
                    key = repr(key_node.value)
                child_path = path + (key,)
                if identity in seen:
                    diagnostics.append(Diagnostic(
                        "duplicate-key", f"Duplicate YAML key '{key}'.", child_path,
                        source_name=source_name, span=_span(key_node),
                    ))
                seen.add(identity)
                spans[child_path] = _span(value_node)
                _index_nodes(value_node, child_path, spans, diagnostics, source_name, active)
        elif isinstance(node, yaml.SequenceNode):
            for index, child in enumerate(node.value):
                _index_nodes(child, path + (index,), spans, diagnostics, source_name, active)
    finally:
        active.remove(node_id)


def _nearest_span(path: RecipePath, spans: Mapping[RecipePath, SourceSpan]) -> SourceSpan | None:
    candidate = path
    while candidate:
        if candidate in spans:
            return spans[candidate]
        candidate = candidate[:-1]
    return spans.get(())


def _source_diagnostic(code: str, message: str, source_name: str, mark=None) -> Diagnostic:
    return Diagnostic(code, message, source_name=source_name, span=_mark_span(mark))


def _enrich_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
    source_name: str,
    spans: Mapping[RecipePath, SourceSpan],
    sequence_documents: Mapping[str, int],
) -> list[Diagnostic]:
    enriched: list[Diagnostic] = []
    for item in diagnostics:
        path = item.path
        if path and isinstance(path[0], str) and path[0] in sequence_documents:
            path = (sequence_documents[path[0]],) + path[1:]
        enriched.append(replace(
            item,
            source_name=item.source_name or source_name,
            span=item.span or _nearest_span(path, spans),
        ))
    return enriched


def _normalization_warnings(
    documents: list[Any],
    source_name: str,
    spans: Mapping[RecipePath, SourceSpan],
) -> list[Diagnostic]:
    warnings: list[Diagnostic] = []
    for doc_index, document in enumerate(documents[1:], start=1):
        if not isinstance(document, Mapping):
            continue
        for section in ("setup_steps", "steps", "teardown_steps"):
            values = document.get(section, [])
            if not isinstance(values, list):
                continue
            for step_index, step in enumerate(values):
                if not isinstance(step, Mapping):
                    continue
                step_path = (doc_index, section, step_index)
                raw_type = step.get("steptype")
                canonical = canonical_step_type(raw_type)
                if canonical and raw_type != canonical:
                    path = step_path + ("steptype",)
                    warnings.append(Diagnostic(
                        "noncanonical-step-type",
                        f"Use canonical step type '{canonical}' instead of '{raw_type}'.",
                        path, "warning", source_name, _nearest_span(path, spans),
                    ))
                mapping = step.get("input_mapping", {})
                if isinstance(mapping, Mapping):
                    for input_name, config in mapping.items():
                        if isinstance(config, Mapping) and "type" not in config:
                            path = step_path + ("input_mapping", input_name)
                            warnings.append(Diagnostic(
                                "implicit-direct-input",
                                f"Input '{input_name}' omits type; it is normalized to 'direct'.",
                                path, "warning", source_name, _nearest_span(path, spans),
                            ))
    return warnings


def _mapping_span(path: RecipePath, spans: Mapping[RecipePath, SourceSpan]) -> SourceSpan | None:
    return _nearest_span(path, spans)


def _build_input(config: Mapping[str, Any], path: RecipePath, spans) -> InputDefinition:
    kind = config.get("type", "direct")
    item_span = _mapping_span(path, spans)
    if kind == "direct":
        return DirectInput(_freeze(config["value"]), bool(config.get("indexed", False)), item_span)
    if kind == "local":
        return LocalInput(config["local_name"], item_span)
    if kind == "global":
        return GlobalInput(config["global_name"], item_span)
    return MethodInput(_freeze(config["value"]), item_span)


def _build_output(config: Mapping[str, Any], path: RecipePath, spans) -> OutputDefinition:
    kind = config["type"]
    item_span = _mapping_span(path, spans)
    if kind == "passfail":
        return PassFailOutput(item_span)
    if kind == "equals":
        return EqualsOutput(_freeze(config["value"]), item_span)
    if kind == "range":
        return RangeOutput(_freeze(config["min"]), _freeze(config["max"]), item_span)
    if kind == "passthrough":
        return PassthroughOutput(item_span)
    if kind == "local":
        return LocalOutput(config["local_name"], item_span)
    if kind == "global":
        return GlobalOutput(config["global_name"], item_span)
    return ImageOutput(item_span)


_COMMON_STEP_KEYS = {
    "steptype", "step_name", "description", "id", "skip", "critical",
    "continue_on_error", "input_mapping", "output_mapping",
}


def _build_step(step: Mapping[str, Any], path: RecipePath, spans) -> StepDefinition:
    canonical = canonical_step_type(step["steptype"])
    assert canonical is not None
    inputs = FrozenMap(
        (str(name), _build_input(config, path + ("input_mapping", name), spans))
        for name, config in step.get("input_mapping", {}).items()
    )
    outputs = FrozenMap(
        (str(name), _build_output(config, path + ("output_mapping", name), spans))
        for name, config in step.get("output_mapping", {}).items()
    )
    configuration = FrozenMap(
        (name, _freeze(value)) for name, value in step.items()
        if name not in _COMMON_STEP_KEYS
    )
    return StepDefinition(
        canonical, step["step_name"], step["description"], step.get("id"),
        bool(step.get("skip", False)), bool(step.get("critical", False)),
        bool(step.get("continue_on_error", False)), inputs, outputs,
        configuration, _mapping_span(path, spans),
    )


def _build_sequence(sequence: Mapping[str, Any], doc_index: int, spans) -> SequenceDefinition:
    def build_section(name: str) -> tuple[StepDefinition, ...]:
        return tuple(
            _build_step(step, (doc_index, name, index), spans)
            for index, step in enumerate(sequence.get(name, []))
        )
    return SequenceDefinition(
        sequence["sequence_name"], sequence["description"],
        FrozenMap.from_mapping(sequence["parameters"]),
        FrozenMap.from_mapping(sequence["outputs"]),
        FrozenMap.from_mapping(sequence["locals"]),
        build_section("setup_steps"), build_section("steps"),
        build_section("teardown_steps"), _mapping_span((doc_index,), spans),
    )


def _build_recipe(documents: list[Mapping[str, Any]], source_name: str, spans) -> RecipeDefinition:
    raw = documents[0]
    header = RecipeHeader(
        raw["name"], raw["version"], raw["recipe_version"], raw["description"],
        raw["main_sequence"], FrozenMap.from_mapping(raw["globals"]),
        raw.get("continue_on_error"), raw.get("report", "overwrite"),
        bool(raw.get("report_name_include_serial", False)), raw.get("test_package"),
        _mapping_span((0,), spans),
    )
    sequences = tuple(
        _build_sequence(sequence, index, spans)
        for index, sequence in enumerate(documents[1:], start=1)
    )
    recipe_span = None
    if documents:
        first = spans.get((0,))
        last = spans.get((len(documents) - 1,))
        if first and last:
            recipe_span = SourceSpan(first.start, last.end)
    return RecipeDefinition(header, sequences, source_name, recipe_span)


def parse_recipe_text(text: str, source_name: str = "<memory>") -> ParseResult:
    """Parse recipe YAML text without importing or invoking the runtime."""
    if not isinstance(text, str):
        diagnostic = Diagnostic("invalid-source", "Recipe source must be text.", source_name=source_name)
        return ParseResult(None, (diagnostic,))
    if not text.strip():
        diagnostic = Diagnostic("empty-recipe", "A recipe requires a header and at least one sequence.", source_name=source_name)
        return ParseResult(None, (diagnostic,))

    try:
        nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return ParseResult(None, (_source_diagnostic("yaml-syntax-error", str(error), source_name, mark),))

    spans: dict[RecipePath, SourceSpan] = {}
    diagnostics: list[Diagnostic] = []
    for index, node in enumerate(nodes):
        if node is not None:
            _index_nodes(node, (index,), spans, diagnostics, source_name, set())

    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        code = "unsafe-yaml" if isinstance(error, yaml.constructor.ConstructorError) else "yaml-construction-error"
        diagnostics.append(_source_diagnostic(code, str(error), source_name, mark))
        return ParseResult(None, tuple(diagnostics))

    sequence_documents = {
        document["sequence_name"]: index
        for index, document in enumerate(documents)
        if isinstance(document, Mapping) and isinstance(document.get("sequence_name"), str)
    }
    contract = validate_recipe_documents(documents)
    diagnostics.extend(_enrich_diagnostics(contract.diagnostics, source_name, spans, sequence_documents))
    diagnostics.extend(_normalization_warnings(documents, source_name, spans))
    if any(item.severity == "error" for item in diagnostics):
        return ParseResult(None, tuple(diagnostics))
    return ParseResult(_build_recipe(documents, source_name, spans), tuple(diagnostics))


def parse_recipe_file(path: str | Path, encoding: str = "utf-8") -> ParseResult:
    """Read and parse a recipe file, reporting read failures as diagnostics."""
    source_path = Path(path)
    source_name = str(source_path)
    try:
        text = source_path.read_text(encoding=encoding)
    except (OSError, UnicodeError) as error:
        return ParseResult(None, (Diagnostic(
            "file-read-error", f"Could not read recipe: {error}",
            source_name=source_name,
        ),))
    return parse_recipe_text(text, source_name)


def _input_to_mapping(value: InputDefinition) -> dict[str, Any]:
    if isinstance(value, DirectInput):
        result = {"type": "direct", "value": _thaw(value.value)}
        if value.indexed:
            result["indexed"] = True
        return result
    if isinstance(value, LocalInput):
        return {"type": "local", "local_name": value.local_name}
    if isinstance(value, GlobalInput):
        return {"type": "global", "global_name": value.global_name}
    return {"type": "method", "value": _thaw(value.value)}


def _output_to_mapping(value: OutputDefinition) -> dict[str, Any]:
    if isinstance(value, PassFailOutput):
        return {"type": "passfail"}
    if isinstance(value, EqualsOutput):
        return {"type": "equals", "value": _thaw(value.value)}
    if isinstance(value, RangeOutput):
        return {"type": "range", "min": _thaw(value.minimum), "max": _thaw(value.maximum)}
    if isinstance(value, PassthroughOutput):
        return {"type": "passthrough"}
    if isinstance(value, LocalOutput):
        return {"type": "local", "local_name": value.local_name}
    if isinstance(value, GlobalOutput):
        return {"type": "global", "global_name": value.global_name}
    return {"type": "image"}


def _step_to_mapping(step: StepDefinition) -> dict[str, Any]:
    result: dict[str, Any] = {"steptype": step.steptype, "step_name": step.step_name}
    if step.id is not None:
        result["id"] = step.id
    result["description"] = step.description
    result["skip"] = step.skip
    result["critical"] = step.critical
    result["continue_on_error"] = step.continue_on_error
    spec = STEP_SPECS_BY_NAME[step.steptype.casefold()]
    for field_spec in spec.fields:
        if field_spec.name in _COMMON_STEP_KEYS or field_spec.name not in step.configuration:
            continue
        result[field_spec.name] = _thaw(step.configuration[field_spec.name])
    result["input_mapping"] = {
        name: _input_to_mapping(value) for name, value in step.input_mapping.items()
    }
    result["output_mapping"] = {
        name: _output_to_mapping(value) for name, value in step.output_mapping.items()
    }
    return result


def _sequence_to_mapping(sequence: SequenceDefinition) -> dict[str, Any]:
    return {
        "sequence_name": sequence.sequence_name,
        "description": sequence.description,
        "parameters": _thaw(sequence.parameters),
        "outputs": _thaw(sequence.outputs),
        "locals": _thaw(sequence.locals),
        "setup_steps": [_step_to_mapping(step) for step in sequence.setup_steps],
        "steps": [_step_to_mapping(step) for step in sequence.steps],
        "teardown_steps": [_step_to_mapping(step) for step in sequence.teardown_steps],
    }


def dump_recipe(recipe: RecipeDefinition) -> str:
    """Serialize a typed recipe to stable canonical multi-document YAML."""
    if not isinstance(recipe, RecipeDefinition):
        raise TypeError("dump_recipe expects a RecipeDefinition")
    header = recipe.header
    header_document: dict[str, Any] = {
        "name": header.name,
        "version": header.version,
        "recipe_version": header.recipe_version,
        "description": header.description,
        "main_sequence": header.main_sequence,
    }
    if header.test_package is not None:
        header_document["test_package"] = header.test_package
    if header.continue_on_error is not None:
        header_document["continue_on_error"] = header.continue_on_error
    header_document["report"] = header.report
    header_document["report_name_include_serial"] = header.report_name_include_serial
    header_document["globals"] = _thaw(header.globals)
    documents = [header_document] + [_sequence_to_mapping(sequence) for sequence in recipe.sequences]
    return yaml.safe_dump_all(
        documents, explicit_start=True, sort_keys=False,
        default_flow_style=False, allow_unicode=True,
    )
