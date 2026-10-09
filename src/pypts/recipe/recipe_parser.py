# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe parser: a file or a text in, a validated Recipe object out.

This module owns the whole loading pipeline, in order:

    read the file              (load_recipe only)
    parse the YAML             document 1 is the header, the rest are sequences
    normalize                  the recipe language is case-insensitive
    validate                   every document against the Pydantic models in
                               recipe_schema.py - all problems in one RecipeError;
                               the header comes back with its defaults filled in,
                               each sequence with exactly the keys it wrote
    check version              warn-only: a recipe written for another pypts is
                               an ERROR in the log and a notice to the operator,
                               and still loads (hard refusal ~v1.0)
    expand                     an Indexed step becomes one ordinary step mapping
                               per parameter set (pypts.step.indexed_step)
    build                      Recipe -> Sequences -> Steps (via the step registry);
                               a Sequence step gets a fresh copy of the sequence
                               it calls, built the same way

recipe.py holds the data classes this returns, plus the `Recipe.from_file` /
`Recipe.from_yaml_text` facades that delegate here - callers may use either
entry. The split keeps the object the Sequencer executes free of any parsing
machinery.
"""

import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from pypts.logger.log import log
from pypts.recipe.recipe import Recipe, RecipeError, Sequence
from pypts.recipe.recipe_schema import (
    OUTPUT_TYPES,
    SEQUENCE_DEFAULTS,
    STEP_TYPE_REQUIRED,
    HeaderSchema,
    SequenceSchema,
)
from pypts.step import indexed_step, sequence_step
from pypts.step.registry import build_step
from pypts.step.step import Step


def load_recipe(path: str) -> Recipe:
    """Load and validate a recipe file; every failure is a RecipeError."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise RecipeError(f"Cannot read recipe file '{path}': {error}") from error
    recipe = parse_recipe(text, file_name=Path(path).name)
    recipe.base_dir = str(Path(path).resolve().parent)
    return recipe


def parse_recipe(text: str, file_name: str = "", check_version: bool = True) -> Recipe:
    """
    Parse recipe YAML: document 1 is the header, the rest are sequences.

    `check_version=False` is for a tool that only asks whether a recipe would
    load - the Recipe Creator's verificator, on every edit. The version check
    is part of really loading one: it logs for the technician and sets the
    operator's notice, so it is skipped and `version_notice` stays empty.
    """
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as error:
        raise RecipeError(f"Recipe '{file_name}' is not valid YAML: {error}") from error
    if not documents or documents[0] is None:
        raise RecipeError(f"Recipe '{file_name}' is empty")

    header = documents[0]
    if not isinstance(header, dict):
        raise RecipeError(f"Recipe '{file_name}': the first document is not a mapping")

    # The recipe language is case-insensitive: keys and structural values
    # are lowercased here, once, so everything downstream stays strict.
    header = normalize_header(header)

    # Every problem in the whole file, reported at once.
    header_problems, header_schema = validate_document(header, HeaderSchema, "header")
    problems = [str(problem) for problem in header_problems]
    sequence_schemas = []
    for number, document in enumerate(documents[1:], start=2):
        if not isinstance(document, dict):
            problems.append(f"document {number} is not a mapping")
            continue
        document = normalize_sequence(document)
        sequence_problems, sequence_schema = validate_document(
            document, SequenceSchema, sequence_context(document, number)
        )
        problems.extend(str(problem) for problem in sequence_problems)
        sequence_schemas.append(sequence_schema)
    if problems or header_schema is None:
        listed = "; ".join(problems)
        raise RecipeError(f"Recipe '{file_name}' is invalid: {listed}")

    # The header with every default filled in. A sequence keeps only what the
    # recipe wrote - the step constructors own their defaults, and an Indexed
    # step must still see that its wrapper said nothing about `skip`.
    header = header_schema.model_dump()
    sequence_documents = []
    for sequence_schema in sequence_schemas:
        if sequence_schema is not None:
            sequence_documents.append(sequence_schema.model_dump(exclude_unset=True))

    version_notice = ""
    if check_version:
        version_notice = _check_framework_version(header, file_name)

    # Sequence names keep their case but must be unique without it, so a
    # case-insensitive lookup - main_sequence, or a Sequence step's
    # sequence_name - can never be ambiguous.
    documents: dict[str, dict[str, Any]] = {}
    for document in sequence_documents:
        name = str(document["sequence_name"])
        if name.lower() in documents:
            raise RecipeError(f"Recipe '{file_name}': duplicate sequence name '{name}'")
        documents[name.lower()] = document
    if not documents:
        raise RecipeError(f"Recipe '{file_name}' contains no sequence documents")

    # An omitted main_sequence means the first sequence in the file.
    names = [str(document["sequence_name"]) for document in sequence_documents]
    requested = str(header["main_sequence"] or names[0])
    main_document = documents.get(requested.lower())
    if main_document is None:
        raise RecipeError(
            f"Recipe '{file_name}': main_sequence '{requested}' does not exist. "
            f"Sequences: {', '.join(names)}"
        )
    main_sequence = str(main_document["sequence_name"])

    # Every document is built, each as the root of its own call tree. Only
    # main will be runnable (stage 2); until then the others stay selectable.
    sequences: dict[str, Sequence] = {}
    for document in sequence_documents:
        sequence = _build_sequence(document, documents, main_sequence, ())
        sequences[sequence.name] = sequence

    return Recipe(
        name=header["name"],
        description=header["description"],
        version=str(header["version"]),
        globals=header["globals"],
        main_sequence=main_sequence,
        report_metadata=tuple(header["report_metadata"]),
        version_notice=version_notice,
        sequences=sequences,
        file_name=file_name,
    )


_Schema = TypeVar("_Schema", bound=BaseModel)


@dataclass(frozen=True)
class SchemaProblem:
    """
    One problem validation found in a recipe document.

    `where` and `message` are the two halves of the sentence a RecipeError
    carries. `path` and `kind` are for a tool that points into the file: the
    Recipe Creator's verificator turns them into a line number and a hint.
    """

    #: "header", or "sequence 'Main', steps[1] 'Pause'".
    where: str
    #: The field and Pydantic's message: "wait_time: Field required".
    message: str
    #: Where in the document, nested as the YAML is, without union tags:
    #: ("steps", 0, "wait_time"). Positions count from 0.
    path: tuple[int | str, ...]
    #: Pydantic's error type: "missing", "extra_forbidden", "union_tag_invalid"...
    kind: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def validate_document(
    raw: dict[str, Any], schema_cls: type[_Schema], context: str
) -> tuple[list[SchemaProblem], _Schema | None]:
    """
    One normalized document against its model: ([], the model) or (every
    problem, None). `context` names the document, as sequence_context() does.
    """
    try:
        return [], schema_cls.model_validate(raw)
    except ValidationError as error:
        return [_describe_problem(context, raw, detail) for detail in error.errors()], None


def sequence_context(document: dict[str, Any], number: int) -> str:
    """How a problem names sequence document `number` (counted from 1, header included)."""
    name = document.get("sequence_name")
    if isinstance(name, str) and name:
        return f"sequence '{name}'"
    return f"document {number}"


def _describe_problem(
    context: str, document: dict[str, Any], detail: ErrorDetails
) -> SchemaProblem:
    """
    Pydantic's message, at a location an author can find in the file.

    Steps are counted from 1, as the step table counts them, and named; the
    union tag Pydantic puts in the path (`steps -> 0 -> wait -> wait_time`)
    is the steptype the author already wrote, so it is left out.
    """
    location = list(detail["loc"])
    message = detail["msg"]
    context_values = detail.get("ctx") or {}
    kind = detail["type"]
    if kind == "union_tag_invalid":
        field = str(context_values["discriminator"]).strip("'")
        # Pydantic picks the model by the tag before any model sees the data,
        # so a bare `steptype:` arrives here as a tag of None. A bare key is
        # an absent one everywhere else, and reads the same here.
        tagged = _value_at(document, _document_path(location))
        if isinstance(tagged, dict) and tagged.get(field) is None:
            kind = "union_tag_not_found"
        else:
            message = (
                f"{field} '{context_values['tag']}' is not one of: "
                f"{context_values['expected_tags']}"
            )
    if kind == "union_tag_not_found":
        location.append(str(context_values["discriminator"]).strip("'"))
        message = "Field required"
    elif kind == "model_type":
        # "...or instance of ParameterSet" names a Python class, not a recipe word.
        message = "Input should be a valid dictionary"

    path = _document_path(location)
    parts = _readable_parts(path, document)
    where = context
    if len(path) >= 2 and path[0] in _STEP_LISTS and isinstance(path[1], int):
        where = f"{context}, {parts.pop(0)}"
        steps = document.get(str(path[0]))
        if isinstance(steps, list) and path[1] < len(steps):
            label = _step_label(steps[path[1]])
            if label:
                where = f"{where} '{label}'"

    if parts:
        message = f"{' -> '.join(parts)}: {message}"
    return SchemaProblem(where=where, message=message, path=path, kind=kind)


#: The lists that hold steps, in a sequence document.
_STEP_LISTS = ("steps", "teardown_steps")


def _document_path(location: list[int | str]) -> tuple[int | str, ...]:
    """
    Pydantic's location without its union tags. A tag can only follow a step
    (a list position or `template`) or an outputs entry - whatever its name,
    `1:` included - and is dropped there.
    """
    path: list[int | str] = []
    position = 0
    while position < len(location):
        part = location[position]
        previous = location[position - 1] if position > 0 else None
        path.append(part)

        following = location[position + 1] if position + 1 < len(location) else None
        is_step = part == "template" or (isinstance(part, int) and previous in _STEP_LISTS)
        is_output = previous == "outputs"
        if (is_step and following in STEP_TYPE_REQUIRED) or (
            is_output and following in OUTPUT_TYPES
        ):
            position += 1
        position += 1
    return tuple(path)


def _readable_parts(path: tuple[int | str, ...], document: dict[str, Any]) -> list[str]:
    """
    The path as an author reads it: a list position joins its list as `[n]`,
    counted from 1. Pydantic writes a position and a number key (`outputs:
    {1: ...}`) alike, so the document says which one it is.
    """
    parts: list[str] = []
    container: Any = document
    for part in path:
        if isinstance(part, int) and parts and not isinstance(container, dict):
            parts[-1] = f"{parts[-1]}[{part + 1}]"
        else:
            parts.append(str(part))
        container = _child(container, part)
    return parts


def _value_at(document: dict[str, Any], path: tuple[int | str, ...]) -> Any:
    """What the document holds at `path`, or None when there is nothing there."""
    value: Any = document
    for part in path:
        value = _child(value, part)
    return value


def _child(container: Any, part: int | str) -> Any:
    """The value at `part` in a mapping or a list, or None when there is none."""
    if isinstance(container, dict):
        return container.get(part)
    if isinstance(container, list) and isinstance(part, int) and 0 <= part < len(container):
        return container[part]
    return None


def _step_label(step_data: Any) -> str:
    """The name the operator knows a step by: a Sequence step is named after its call."""
    if not isinstance(step_data, dict):
        return ""
    if sequence_step.is_sequence_step(step_data):
        name = step_data.get("sequence_name")
    else:
        name = step_data.get("step_name")
    if name is None:
        return ""
    return str(name)


def _check_framework_version(header: dict[str, Any], file_name: str) -> str:
    """
    The header's `version` against the running pypts; the notice, or "".

    `version` is the pypts a recipe was written for, and it is required - a
    recipe says which framework it expects, and the framework says so when it
    is not that one. **Major.minor only**, because the running version carries
    a setuptools-scm suffix (`0.2.2.dev25+g27956b5f9`) no recipe could match.

    Warn-only for the duration of the refactor: an ERROR in the log, a notice
    for the operator, and the recipe loads unchanged. Nothing here edits the
    file - the version is the author's statement, not ours. The hard refusal
    comes with the compatibility policy, ~v1.0 (roadmap).

    Returns:
        The sentence for the operator, or "" when there is nothing to say.
    """
    declared = str(header.get("version") or "")
    declared_pair = _major_minor(declared)
    if not declared_pair:
        log.error(
            "Recipe '%s' gives its version as '%s', which is not a version this "
            "software recognises, so it could not be checked. It was loaded anyway.",
            file_name,
            declared,
        )
        return (
            f"Recipe '{file_name}' declares version {declared!r}, which is not a "
            f"pypts version like '0.2'. It was loaded without a compatibility check."
        )

    running_pair = _major_minor(_framework_version())
    # Nothing to compare against in a tree with no distribution metadata: say
    # nothing rather than cry wolf on every run.
    if not running_pair or declared_pair == running_pair:
        return ""

    log.error(
        "Recipe '%s' was written for PyPTS %s but this is PyPTS %s. It was loaded "
        "anyway - check that it still does what you expect.",
        file_name,
        declared_pair,
        running_pair,
    )
    return (
        f"Recipe '{file_name}' was written for pypts {declared_pair}, but this is "
        f"pypts {running_pair}. It was loaded unchanged - check that it still does "
        f"what you expect."
    )


def current_recipe_version() -> str:
    """
    The `version` a recipe should declare to match the running pypts.

    The major.minor the check below compares against, so a template, a recipe
    generator or a test asks here rather than reconstructing the rule. Empty
    when the running version cannot be determined - which is also when the
    check says nothing.
    """
    return _major_minor(_framework_version())


def _framework_version() -> str:
    """The running pypts version, or "" when there is no package metadata."""
    try:
        return metadata.version("pts-framework")
    except metadata.PackageNotFoundError:
        return ""


def _major_minor(version: str) -> str:
    """The leading `major.minor` of a version string, "" if it has none."""
    match = re.match(r"(\d+)\.(\d+)", str(version).strip())
    if match is None:
        return ""
    return f"{match.group(1)}.{match.group(2)}"


# --- normalization and defaults - what the parser does with the rules --------


def normalize_header(header: dict[str, Any]) -> dict[str, Any]:
    """Lowercase the header's keys - the recipe language is case-insensitive."""
    return _lowercase_keys(header)


def normalize_sequence(document: dict[str, Any]) -> dict[str, Any]:
    """
    Lowercase everything that is the recipe's own language
    """
    document = _lowercase_keys(document)
    for list_name in ("steps", "teardown_steps"):
        steps = document.get(list_name)
        if isinstance(steps, list):
            document[list_name] = [_normalize_step(step_data) for step_data in steps]
    return document


def _normalize_step(step_data: Any) -> Any:
    """One step mapping; anything malformed is left for validation to name."""
    if not isinstance(step_data, dict):
        return step_data
    step_data = _lowercase_keys(step_data)
    # The models pick a step's schema by its lowercase steptype.
    if isinstance(step_data.get("steptype"), str):
        step_data["steptype"] = step_data["steptype"].lower()
    for mapping_name in ("inputs", "outputs"):
        mapping = step_data.get(mapping_name)
        if isinstance(mapping, dict):
            step_data[mapping_name] = {
                entry_name: _normalize_entry(config) for entry_name, config in mapping.items()
            }
    if indexed_step.is_indexed_step(step_data):
        step_data = _normalize_indexed_step(step_data)
    return step_data


def _normalize_indexed_step(step_data: dict[str, Any]) -> dict[str, Any]:
    """
    The two keys only an Indexed step has.

    The template is an ordinary step mapping, so it is normalized as one. In a
    parameter set only `inputs` and `expect` are the recipe's own language -
    what is inside them are argument and output names, which keep their case
    exactly as mapping entry names do.
    """
    template = step_data.get(indexed_step.TEMPLATE_KEY)
    if isinstance(template, dict):
        step_data[indexed_step.TEMPLATE_KEY] = _normalize_step(template)

    sets = step_data.get(indexed_step.SETS_KEY)
    if isinstance(sets, list):
        normalized_sets = []
        for one_set in sets:
            if isinstance(one_set, dict):
                normalized_sets.append(_lowercase_keys(one_set))
            else:
                normalized_sets.append(one_set)
        step_data[indexed_step.SETS_KEY] = normalized_sets
    return step_data


def _normalize_entry(config: Any) -> Any:
    """One input/output mapping entry: lowercase its config keys and its type."""
    if not isinstance(config, dict):
        return config
    config = _lowercase_keys(config)
    if isinstance(config.get("type"), str):
        config["type"] = config["type"].lower()
    return config


def _lowercase_keys(mapping: dict[str, Any]) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in mapping.items()}


def apply_defaults(document: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of `document` with every absent optional key filled in.

    A key that is missing, or present with no value (YAML reads a bare
    `teardown_steps:` line as None), gets its default. Mutable defaults are
    copied, so no two recipes ever share a dict or a list.
    """
    filled = dict(document)
    for key, default in defaults.items():
        if filled.get(key) is None:
            if isinstance(default, dict):
                filled[key] = dict(default)
            elif isinstance(default, list):
                filled[key] = list(default)
            else:
                filled[key] = default
    return filled


# --- building the object tree -------------------------------------------------


def _build_sequence(
    document: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    main_sequence: str,
    calling: tuple[str, ...],
) -> Sequence:
    """
    Build one Sequence from one normalized, validated YAML document.

    Args:
        documents: every sequence document of the recipe, keyed by lowercased name.
        main_sequence: the main sequence's name, which no Sequence step may call.
        calling: the sequences whose Sequence steps led here, outermost first -
            what a cycle is detected and described with.
    """
    document = apply_defaults(document, SEQUENCE_DEFAULTS)
    name = document["sequence_name"]
    chain = (*calling, str(name))
    steps = _build_steps(name, list(document["steps"]), documents, main_sequence, chain)
    teardown_steps = _build_steps(
        name, list(document["teardown_steps"]), documents, main_sequence, chain
    )
    return Sequence(
        name=name,
        description=document["description"],
        steps=steps,
        teardown_steps=teardown_steps,
    )


def _build_steps(
    sequence_name: str,
    step_datas: list[Any],
    documents: dict[str, dict[str, Any]],
    main_sequence: str,
    chain: tuple[str, ...],
) -> list[Step]:
    """One step list: Indexed steps expanded, every call given its own sequence."""
    built = []
    expanded = _expand_indexed_steps(sequence_name, step_datas)
    for position, step_data in enumerate(expanded, start=1):
        if sequence_step.is_sequence_step(step_data):
            step_data = dict(step_data)
            step_data["sequence"] = _called_sequence(
                sequence_name, position, step_data, documents, main_sequence, chain
            )
        built.append(_build_step_or_refuse(sequence_name, position, step_data))
    return built


def _called_sequence(
    sequence_name: str,
    position: int,
    step_data: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    main_sequence: str,
    chain: tuple[str, ...],
) -> Sequence:
    """
    A fresh copy of the sequence one Sequence step calls.

    Fresh on every call, so two calls never share a Step object or a UUID - the
    step table and the report tell rows apart by id. Refused: a name no sequence
    has, the main sequence, and a call that would lead back to a sequence
    already on the way here, which would never end. Calling one sequence many
    times one after another is not that.
    """
    target = str(step_data["sequence_name"])
    where = f"Sequence '{sequence_name}', step {position} ('{target}')"
    document = documents.get(target.lower())
    if document is None:
        known = ", ".join(str(d["sequence_name"]) for d in documents.values())
        raise RecipeError(f"{where}: there is no sequence called '{target}'. Sequences: {known}")
    if target.lower() == main_sequence.lower():
        raise RecipeError(
            f"{where}: '{main_sequence}' is the main sequence. It runs the recipe and "
            f"cannot be called from another sequence."
        )
    called_name = str(document["sequence_name"])
    if called_name.lower() in {name.lower() for name in chain}:
        path = " -> ".join((*chain, called_name))
        raise RecipeError(f"{where}: calling '{called_name}' here would never end: {path}")
    return _build_sequence(document, documents, main_sequence, chain)


def _expand_indexed_steps(
    sequence_name: str, step_datas: list[Any]
) -> list[Any]:
    """
    Replace every Indexed step with the ordinary steps it stands for.

    Everything downstream - the registry, the Sequencer, the events, the report -
    then deals with plain steps and never learns that the steptype exists. The
    positions in a later error message therefore count expanded steps, which is
    what the operator sees in the step table too.
    """
    expanded: list[Any] = []
    for position, step_data in enumerate(step_datas, start=1):
        if not indexed_step.is_indexed_step(step_data):
            expanded.append(step_data)
            continue
        step_name = step_data.get("step_name", "<unnamed>")
        try:
            expanded.extend(indexed_step.expand_indexed_step(step_data))
        except ValueError as error:
            raise RecipeError(
                f"Sequence '{sequence_name}', step {position} ('{step_name}'): {error}"
            ) from error
    return expanded


def _build_step_or_refuse(sequence_name: str, position: int, step_data: dict[str, Any]) -> Step:
    """One step via the registry, with every failure wrapped into a RecipeError."""
    # A Sequence step has no step_name; it is named after the sequence it calls.
    step_name = step_data.get("step_name") or step_data.get("sequence_name") or "<unnamed>"
    try:
        return build_step(step_data)
    except KeyError as error:
        raise RecipeError(
            f"Sequence '{sequence_name}', step {position} ('{step_name}'): "
            f"missing required key {error}"
        ) from error
    except (ValueError, TypeError) as error:
        raise RecipeError(
            f"Sequence '{sequence_name}', step {position} ('{step_name}'): {error}"
        ) from error
