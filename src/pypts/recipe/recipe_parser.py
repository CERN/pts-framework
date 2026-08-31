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
    check format_version       warn-only for now: a mismatch is an ERROR in the
                               log, the recipe still loads (hard refusal ~v1.0)
    apply the defaults         every absent optional field gets its rules.py value
    build                      Recipe -> Sequences -> Steps (via the step registry)

recipe.py holds the data classes this returns, plus the `Recipe.from_file` /
`Recipe.from_yaml_text` facades that delegate here - callers may use either
entry. The split keeps the object the Sequencer executes free of any parsing
machinery.
"""

from pathlib import Path
from typing import Any

import yaml

from pypts.logger.log import log
from pypts.recipe import validator
from pypts.recipe.recipe import Recipe, RecipeError, Sequence
from pypts.recipe.rules import HEADER_DEFAULTS, RECIPE_FORMAT_VERSION, SEQUENCE_DEFAULTS
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

    _check_format_version(header, file_name)
    header = apply_defaults(header, HEADER_DEFAULTS)

    # Sequence names keep their case but must be unique without it, so a
    # case-insensitive main_sequence lookup can never be ambiguous.
    sequences: dict[str, Sequence] = {}
    for document in sequence_documents:
        sequence = _build_sequence(document)
        if str(sequence.name).lower() in {name.lower() for name in sequences}:
            raise RecipeError(
                f"Recipe '{file_name}': duplicate sequence name '{sequence.name}'"
            )
        sequences[sequence.name] = sequence
    if not sequences:
        raise RecipeError(f"Recipe '{file_name}' contains no sequence documents")

    # An omitted main_sequence means the first sequence in the file.
    requested = str(header["main_sequence"] or next(iter(sequences)))
    found = [name for name in sequences if name.lower() == requested.lower()]
    if not found:
        raise RecipeError(
            f"Recipe '{file_name}': main_sequence '{requested}' does not exist. "
            f"Sequences: {', '.join(sequences)}"
        )
    main_sequence = found[0]

    return Recipe(
        name=header["name"],
        description=header["description"],
        version=str(header["version"]),
        globals=header["globals"],
        main_sequence=main_sequence,
        sequences=sequences,
        file_name=file_name,
    )


def _check_format_version(header: dict[str, Any], file_name: str) -> None:
    """
    Warn-only for the duration of the refactor: a recipe declaring a format
    this pypts does not read is an ERROR in the log, but it still loads. An
    absent `format_version` means "written for the current format". The hard
    refusal comes with the compatibility policy, ~v1.0 (roadmap).
    """
    declared = str(header.get("format_version") or "")
    if declared and declared != RECIPE_FORMAT_VERSION:
        log.error(
            "Recipe '%s' declares format_version %s but this pypts reads format %s "
            "- loading anyway.",
            file_name,
            declared,
            RECIPE_FORMAT_VERSION,
        )


# --- normalization and defaults - what the parser does with the rules --------


def normalize_header(header: dict[str, Any]) -> dict[str, Any]:
    """Lowercase the header's keys - the recipe language is case-insensitive."""
    return _lowercase_keys(header)


def normalize_sequence(document: dict[str, Any]) -> dict[str, Any]:
    """
    Lowercase everything that is the recipe's own language
    """
    document = _lowercase_keys(document)
    for list_name in ("setup_steps", "steps", "teardown_steps"):
        steps = document.get(list_name)
        if isinstance(steps, list):
            document[list_name] = [_normalize_step(step_data) for step_data in steps]
    return document


def _normalize_step(step_data: Any) -> Any:
    """One step mapping; anything malformed is left for the validator to name."""
    if not isinstance(step_data, dict):
        return step_data
    step_data = _lowercase_keys(step_data)
    if isinstance(step_data.get("action_type"), str):
        step_data["action_type"] = step_data["action_type"].lower()
    for mapping_name in ("input_mapping", "output_mapping"):
        mapping = step_data.get(mapping_name)
        if isinstance(mapping, dict):
            step_data[mapping_name] = {
                entry_name: _normalize_entry(config) for entry_name, config in mapping.items()
            }
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

    A key that is missing, or present with no value (YAML reads `locals:`
    alone as None), gets its default. Mutable defaults are copied, so no
    two recipes ever share a dict or a list.
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


def _build_sequence(document: dict[str, Any]) -> Sequence:
    """Build one Sequence from one normalized, validated YAML document."""
    document = apply_defaults(document, SEQUENCE_DEFAULTS)
    name = document["sequence_name"]

    # Setup steps are ordinary steps that run first - one flat list.
    steps = [
        _build_step_or_refuse(name, position, step_data)
        for position, step_data in enumerate(
            list(document["setup_steps"]) + list(document["steps"]), start=1
        )
    ]
    teardown_steps = [
        _build_step_or_refuse(name, position, step_data)
        for position, step_data in enumerate(document["teardown_steps"], start=1)
    ]
    return Sequence(
        name=name,
        description=document["description"],
        locals=document["locals"],
        parameters=document["parameters"],
        outputs=document["outputs"],
        steps=steps,
        teardown_steps=teardown_steps,
    )


def _build_step_or_refuse(sequence_name: str, position: int, step_data: dict[str, Any]) -> Step:
    """One step via the registry, with every failure wrapped into a RecipeError."""
    step_name = step_data.get("step_name", "<unnamed>")
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
