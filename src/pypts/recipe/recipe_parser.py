# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe parser: a file or a text in, a validated Recipe object out.

This module owns the whole loading pipeline, in order:

    read the file              (load_recipe only)
    parse the YAML             document 1 is the header, the rest are sequences
    normalize                  the recipe language is case-insensitive
    validate                   every mandatory field, via validator.py against
                               rules.py - all problems in one RecipeError
    check version              warn-only: a recipe written for another pypts is
                               an ERROR in the log and a notice to the operator,
                               and still loads (hard refusal ~v1.0)
    apply the defaults         every absent optional field gets its rules.py value
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
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from pypts.logger.log import log
from pypts.recipe import validator
from pypts.recipe.recipe import Recipe, RecipeError, Sequence
from pypts.recipe.rules import HEADER_DEFAULTS, SEQUENCE_DEFAULTS
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


def parse_recipe(text: str, file_name: str = "") -> Recipe:
    """Parse recipe YAML: document 1 is the header, the rest are sequences."""
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

    # Every mandatory-field problem in the whole file, reported at once.
    problems = validator.validate_header(header)
    sequence_documents = []
    for number, document in enumerate(documents[1:], start=2):
        if not isinstance(document, dict):
            problems.append(f"document {number} is not a mapping")
        else:
            document = normalize_sequence(document)
            sequence_documents.append(document)
            problems.extend(validator.validate_sequence(document))
    if problems:
        listed = "; ".join(problems)
        raise RecipeError(f"Recipe '{file_name}' is invalid: {listed}")

    version_notice = _check_framework_version(header, file_name)
    header = apply_defaults(header, HEADER_DEFAULTS)

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
        report_metadata=_report_metadata(header, file_name),
        version_notice=version_notice,
        sequences=sequences,
        file_name=file_name,
    )


def _report_metadata(header: dict[str, Any], file_name: str) -> tuple[str, ...]:
    """
    The `report_metadata` header field: the globals the Report stamps on
    every row of report.csv and in report.html's header.

    A list of names, refused here rather than half-applied later: the
    Report writes these as CSV columns and a column called `{}` or `3`
    would be nonsense. An empty list is legal and means no metadata.
    """
    declared = header["report_metadata"]
    if isinstance(declared, str) or not isinstance(declared, (list, tuple)):
        raise RecipeError(
            f"Recipe '{file_name}': report_metadata must be a list of global "
            f"names, not {type(declared).__name__}."
        )
    names = []
    for name in declared:
        if not isinstance(name, str) or not name.strip():
            raise RecipeError(
                f"Recipe '{file_name}': report_metadata entry {name!r} is not a "
                f"global name."
            )
        names.append(name.strip())
    return tuple(names)


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
    """One step mapping; anything malformed is left for the validator to name."""
    if not isinstance(step_data, dict):
        return step_data
    step_data = _lowercase_keys(step_data)
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
