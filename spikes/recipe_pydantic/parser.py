"""Safe YAML adapter and semantic validation for the Pydantic v2 spike."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import (
    DirectInput,
    EqualsOutput,
    PassFailOutput,
    PassthroughOutput,
    RangeOutput,
    Recipe,
    RecipeHeader,
    Sequence,
    SequenceStep,
)

type RecipePath = tuple[str | int, ...]


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
    """Source-aware recipe finding, compatible with the PyPTS envelope."""

    code: str
    message: str
    path: RecipePath = ()
    severity: str = "error"
    source_name: str | None = None
    span: SourceSpan | None = None


class RecipeParseError(ValueError):
    """Raised when a caller requires a recipe from an unsuccessful parse."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]):
        self.diagnostics = diagnostics
        errors = sum(item.severity == "error" for item in diagnostics)
        super().__init__(f"Recipe parsing failed with {errors} error(s).")


@dataclass(frozen=True)
class ParseResult:
    recipe: Recipe | None
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

    def require_recipe(self) -> Recipe:
        if not self.is_valid:
            raise RecipeParseError(self.diagnostics)
        assert self.recipe is not None
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


def _nearest_span(path: RecipePath, spans: Mapping[RecipePath, SourceSpan]) -> SourceSpan | None:
    candidate = path
    while candidate:
        if candidate in spans:
            return spans[candidate]
        candidate = candidate[:-1]
    return spans.get(())


def _diagnostic(
    code: str,
    message: str,
    path: RecipePath,
    source_name: str,
    spans: Mapping[RecipePath, SourceSpan],
) -> Diagnostic:
    return Diagnostic(code, message, path, source_name=source_name, span=_nearest_span(path, spans))


def _index_nodes(
    node: yaml.Node,
    path: RecipePath,
    spans: dict[RecipePath, SourceSpan],
    diagnostics: list[Diagnostic],
    source_name: str,
    active: set[int],
) -> None:
    spans[path] = _span(node)
    identity = id(node)
    if identity in active:
        diagnostics.append(Diagnostic(
            "recursive-alias",
            "Recursive YAML aliases are not supported.",
            path,
            source_name=source_name,
            span=_span(node),
        ))
        return
    active.add(identity)
    try:
        if isinstance(node, yaml.MappingNode):
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                key_identity = (key_node.tag, repr(key_node.value))
                key: str | int = key_node.value if isinstance(key_node, yaml.ScalarNode) else repr(key_node.value)
                child = path + (key,)
                if key_identity in seen:
                    diagnostics.append(Diagnostic(
                        "duplicate-key",
                        f"Duplicate YAML key '{key}'.",
                        child,
                        source_name=source_name,
                        span=_span(key_node),
                    ))
                seen.add(key_identity)
                _index_nodes(value_node, child, spans, diagnostics, source_name, active)
        elif isinstance(node, yaml.SequenceNode):
            for index, child_node in enumerate(node.value):
                _index_nodes(
                    child_node, path + (index,), spans, diagnostics, source_name, active
                )
    finally:
        active.remove(identity)


_MODEL_TAGS = {
    "direct", "local", "global", "method", "passfail", "equals", "range",
    "passthrough", "image", "PythonModuleStep", "SequenceStep",
    "UserInteractionStep", "WaitStep", "UserLoadingStep", "UserRunMethodStep",
    "UserWriteStep", "SerialNumberStep", "SSHConnectStep", "SSHCloseStep",
    "SSHUploadStep",
}
_CANONICAL_STEPS = {tag for tag in _MODEL_TAGS if tag.endswith("Step")}


def _clean_location(location: tuple[Any, ...]) -> RecipePath:
    cleaned: list[str | int] = []
    for index, item in enumerate(location):
        is_step_tag = (
            item in _CANONICAL_STEPS
            and index >= 2
            and location[index - 2] in {"setup_steps", "steps", "teardown_steps"}
            and isinstance(location[index - 1], int)
        )
        is_mapping_tag = (
            item in _MODEL_TAGS
            and index >= 2
            and location[index - 2] in {"input_mapping", "output_mapping"}
        )
        if not is_step_tag and not is_mapping_tag:
            cleaned.append(item)
    return tuple(cleaned)


def _pydantic_diagnostic(
    error: dict[str, Any],
    prefix: RecipePath,
    source_name: str,
    spans: Mapping[RecipePath, SourceSpan],
) -> Diagnostic:
    location = prefix + _clean_location(tuple(error.get("loc", ())))
    kind = error["type"]
    context = error.get("ctx") or {}
    input_value = error.get("input")
    code = "invalid-field"
    message = error["msg"]

    if kind == "missing":
        code = "missing-field"
    elif kind == "extra_forbidden":
        field = location[-1] if location else "field"
        if field == "serial_number":
            code = "removed-sequence-field"
            message = "Sequence field 'serial_number' was removed in recipe language 2.0.0."
        else:
            code = "unknown-field"
            message = f"Unknown field '{field}'."
    elif kind == "union_tag_not_found":
        discriminator = str(context.get("discriminator", ""))
        if "steptype" in discriminator:
            code = "missing-step-type"
            location += ("steptype",)
            message = "Step requires canonical 'steptype'."
        elif "output_mapping" in location:
            code = "missing-output-type"
            location += ("type",)
            message = "Output mapping requires an explicit 'type'."
        else:
            code = "missing-input-type"
            location += ("type",)
            message = "Mapping requires an explicit 'type' in recipe language 2.0.0."
    elif kind == "union_tag_invalid":
        discriminator = str(context.get("discriminator", ""))
        tag = context.get("tag")
        if "steptype" in discriminator:
            location += ("steptype",)
            canonical = next(
                (candidate for candidate in _CANONICAL_STEPS if candidate.casefold() == str(tag).casefold()),
                None,
            )
            if canonical:
                code = "noncanonical-step-type"
                message = f"Use canonical step type '{canonical}' instead of '{tag}'."
            else:
                code = "unknown-step-type"
                message = f"Unknown step type '{tag}'."
        else:
            location += ("type",)
            if "output_mapping" in location:
                code = "unknown-output-type"
                message = f"Unknown output mapping type '{tag}'."
            else:
                code = "unknown-input-type"
                message = f"Unknown input mapping type '{tag}'."
    elif kind == "literal_error" and location[-1:] == ("recipe_version",):
        code = "unsupported-recipe-version"
        message = f"Recipe language version {input_value!r} is unsupported; expected '2.0.0'."
    elif kind == "literal_error":
        code = "invalid-field-value"
    elif kind in {"bool_type", "string_type", "int_type", "list_type", "dict_type", "model_type"}:
        code = "invalid-field-type"
    elif kind == "invalid_indexed_input":
        code = "invalid-indexed-input"
    elif kind == "missing_method_name":
        code = "missing-method-name"
        location += ("method_name",)
    elif kind == "missing_required_input":
        code = "missing-required-input"
        location += ("input_mapping", "wait_time")
    elif kind == "too_short" and prefix == () and location[-1:] == ("sequences",):
        code = "missing-sequence"

    return _diagnostic(code, message, location, source_name, spans)


def _validation_diagnostics(
    error: ValidationError,
    prefix: RecipePath,
    source_name: str,
    spans: Mapping[RecipePath, SourceSpan],
) -> list[Diagnostic]:
    return [
        _pydantic_diagnostic(item, prefix, source_name, spans)
        for item in error.errors(include_url=False)
    ]


def _all_steps(sequence: Sequence):
    for section_name in ("setup_steps", "steps", "teardown_steps"):
        for index, step in enumerate(getattr(sequence, section_name)):
            yield section_name, index, step


def _semantic_diagnostics(
    header: RecipeHeader | None,
    sequences: list[tuple[int, Sequence]],
    source_name: str,
    spans: Mapping[RecipePath, SourceSpan],
    *,
    complete_sequences: bool = True,
) -> list[Diagnostic]:
    """Rules that cannot be expressed by one structural Pydantic model."""
    diagnostics: list[Diagnostic] = []
    by_name: dict[str, tuple[int, Sequence]] = {}
    for document_index, sequence in sequences:
        path = (document_index, "sequence_name")
        if sequence.sequence_name in by_name:
            diagnostics.append(_diagnostic(
                "duplicate-sequence",
                f"Duplicate sequence '{sequence.sequence_name}'.",
                path,
                source_name,
                spans,
            ))
        else:
            by_name[sequence.sequence_name] = (document_index, sequence)

    if complete_sequences and header is not None and header.main_sequence not in by_name:
        diagnostics.append(_diagnostic(
            "unknown-main-sequence",
            f"Main sequence '{header.main_sequence}' does not exist.",
            (0, "main_sequence"),
            source_name,
            spans,
        ))

    verdict_types = (PassFailOutput, EqualsOutput, RangeOutput, PassthroughOutput)
    for document_index, sequence in sequences:
        flattened = list(_all_steps(sequence))
        for section, index, step in flattened:
            step_path = (document_index, section, index)
            if isinstance(step, SequenceStep) and step.sequence.name not in by_name:
                diagnostics.append(_diagnostic(
                    "unknown-sequence-reference",
                    f"Sequence '{sequence.sequence_name}' references unknown sequence "
                    f"'{step.sequence.name}'.",
                    step_path + ("sequence", "name"),
                    source_name,
                    spans,
                ))

            indexed_lengths = [
                len(value.value)
                for value in step.input_mapping.values()
                if isinstance(value, DirectInput) and value.indexed
            ]
            if len(set(indexed_lengths)) > 1:
                diagnostics.append(_diagnostic(
                    "unequal-indexed-inputs",
                    "Indexed input lists must have equal lengths.",
                    step_path + ("input_mapping",),
                    source_name,
                    spans,
                ))

            verdicts = [
                value for value in step.output_mapping.values() if isinstance(value, verdict_types)
            ]
            if any(isinstance(value, PassthroughOutput) for value in verdicts) and len(verdicts) != 1:
                diagnostics.append(_diagnostic(
                    "mixed-passthrough",
                    "'passthrough' must be the sole verdict mapping.",
                    step_path + ("output_mapping",),
                    source_name,
                    spans,
                ))

        ssh_steps = [item for item in flattened if item[2].steptype.startswith("SSH")]
        if ssh_steps and header is not None:
            for required in ("ssh_client", "host", "user", "port"):
                if required not in header.globals:
                    diagnostics.append(_diagnostic(
                        "missing-ssh-global",
                        f"SSH step requires global '{required}'.",
                        (0, "globals", required),
                        source_name,
                        spans,
                    ))
            if "password" not in header.globals and "private_key" not in header.globals:
                diagnostics.append(_diagnostic(
                    "missing-ssh-credential",
                    "SSH steps require password or private_key global.",
                    (0, "globals"),
                    source_name,
                    spans,
                ))

        connected = False
        unclosed_connect: tuple[str, int] | None = None
        for section, index, step in flattened:
            if step.steptype == "SSHConnectStep":
                connected = True
                unclosed_connect = (section, index)
            elif step.steptype == "SSHUploadStep" and not connected:
                diagnostics.append(_diagnostic(
                    "missing-ssh-connect",
                    f"Sequence '{sequence.sequence_name}' uploads before an SSH connection.",
                    (document_index, section, index),
                    source_name,
                    spans,
                ))
            elif step.steptype == "SSHCloseStep":
                connected = False
                unclosed_connect = None
        if unclosed_connect is not None:
            diagnostics.append(_diagnostic(
                "missing-ssh-close",
                f"Sequence '{sequence.sequence_name}' opens SSH without a later close.",
                (document_index, "teardown_steps"),
                source_name,
                spans,
            ))
    return diagnostics


def parse_recipe_text(text: str, source_name: str = "<memory>") -> ParseResult:
    """Parse candidate recipe-language 2 YAML without runtime or GUI imports."""
    if not isinstance(text, str):
        return ParseResult(None, (Diagnostic(
            "invalid-source", "Recipe source must be text.", source_name=source_name
        ),))
    if not text.strip():
        return ParseResult(None, (Diagnostic(
            "empty-recipe", "A recipe requires a header and at least one sequence.",
            source_name=source_name,
        ),))

    try:
        nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return ParseResult(None, (Diagnostic(
            "yaml-syntax-error", str(error), source_name=source_name, span=_mark_span(mark)
        ),))

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
        diagnostics.append(Diagnostic(code, str(error), source_name=source_name, span=_mark_span(mark)))
        return ParseResult(None, tuple(diagnostics))

    if not documents or all(document is None for document in documents):
        diagnostics.append(Diagnostic(
            "empty-recipe", "A recipe requires a header and at least one sequence.",
            source_name=source_name,
        ))
        return ParseResult(None, tuple(diagnostics))

    header: RecipeHeader | None = None
    semantic_header: RecipeHeader | None = None
    raw_header = documents[0]
    try:
        header = RecipeHeader.model_validate(raw_header)
        semantic_header = header
    except ValidationError as error:
        diagnostics.extend(_validation_diagnostics(error, (0,), source_name, spans))
        if isinstance(raw_header, dict) and raw_header.get("recipe_version") != "2.0.0":
            candidate = dict(raw_header)
            candidate["recipe_version"] = "2.0.0"
            try:
                semantic_header = RecipeHeader.model_validate(candidate)
            except ValidationError:
                pass

    sequences: list[tuple[int, Sequence]] = []
    complete_sequences = True
    for index, document in enumerate(documents[1:], start=1):
        try:
            sequences.append((index, Sequence.model_validate(document)))
        except ValidationError as error:
            complete_sequences = False
            diagnostics.extend(_validation_diagnostics(error, (index,), source_name, spans))

    if len(documents) == 1:
        diagnostics.append(_diagnostic(
            "missing-sequence", "A recipe requires at least one sequence.", (0,), source_name, spans
        ))

    diagnostics.extend(_semantic_diagnostics(
        semantic_header,
        sequences,
        source_name,
        spans,
        complete_sequences=complete_sequences,
    ))
    if diagnostics:
        return ParseResult(None, tuple(diagnostics))
    assert header is not None
    recipe = Recipe(header=header, sequences=[sequence for _, sequence in sequences])
    return ParseResult(recipe)


def parse_recipe_file(path: str | Path, encoding: str = "utf-8") -> ParseResult:
    """Read and parse a candidate recipe file."""
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding=encoding)
    except (OSError, UnicodeError) as error:
        return ParseResult(None, (Diagnostic(
            "file-read-error", f"Could not read recipe: {error}", source_name=str(source_path)
        ),))
    return parse_recipe_text(text, str(source_path))


def dump_recipe(recipe: Recipe) -> str:
    """Serialize a typed recipe as canonical multi-document YAML."""
    if not isinstance(recipe, Recipe):
        raise TypeError("dump_recipe expects a Recipe")
    documents = [
        recipe.header.model_dump(mode="python", by_alias=True, exclude_none=True),
        *[
            sequence.model_dump(mode="python", by_alias=True, exclude_none=True)
            for sequence in recipe.sequences
        ],
    ]
    return yaml.safe_dump_all(
        documents,
        explicit_start=True,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
