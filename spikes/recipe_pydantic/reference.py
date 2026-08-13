"""Render the Sphinx recipe reference from generated JSON Schema only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_schema(path: str | Path) -> dict[str, Any]:
    """Load and minimally verify an aggregate recipe JSON Schema."""
    source = Path(path)
    schema = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(schema, dict) or not isinstance(schema.get("$defs"), dict):
        raise TypeError(f"Recipe schema has no $defs object: {source}")
    return schema


def _reference_name(reference: str) -> str:
    prefix = "#/$defs/"
    if not reference.startswith(prefix):
        raise ValueError(f"Unsupported external JSON Schema reference: {reference}")
    return reference.removeprefix(prefix)


def _resolve(value: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in value:
        return value
    return definitions[_reference_name(value["$ref"])]


def _type_name(value: dict[str, Any]) -> str:
    if "$ref" in value:
        return _reference_name(value["$ref"])
    if "const" in value:
        return repr(value["const"])
    if "enum" in value:
        return " | ".join(repr(item) for item in value["enum"])
    if "anyOf" in value:
        return " | ".join(_type_name(item) for item in value["anyOf"])
    kind = value.get("type")
    if kind == "array":
        return f"list[{_type_name(value.get('items', {}))}]"
    if kind == "object":
        additional = value.get("additionalProperties")
        if isinstance(additional, dict):
            return f"dict[str, {_type_name(additional)}]"
        return "object"
    return {
        "boolean": "bool",
        "integer": "int",
        "number": "number",
        "null": "None",
        "string": "str",
    }.get(kind, "any")


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _field_table(
    definition: dict[str, Any],
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[str]:
    properties = definition.get("properties", {})
    required = set(definition.get("required", []))
    names = [
        name for name in properties
        if (include is None or name in include) and (exclude is None or name not in exclude)
    ]
    if not names:
        return ["This variant adds no fields.", ""]
    # REUSE-IgnoreStart
    lines = [
        ".. list-table:: Fields",
        "   :header-rows: 1",
        "   :widths: 18 19 25 38",
        "",
        "   * - Field",
        "     - Type",
        "     - Requirement",
        "     - Description and example",
    ]
    for name in names:
        field = properties[name]
        requirement = "required" if name in required else "optional"
        if "default" in field:
            requirement += f"; default ``{_literal(field['default'])}``"
        details = field.get("description", "")
        examples = field.get("examples", [])
        if examples:
            details += f" Example: ``{_literal(examples[0])}``."
        lines.extend((
            f"   * - ``{name}``",
            f"     - ``{_type_name(field)}``",
            f"     - {requirement}",
            f"     - {details}",
        ))
    lines.append("")
    return lines


def _model_section(
    definition_name: str,
    definitions: dict[str, Any],
    anchor: str,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[str]:
    definition = definitions[definition_name]
    title = definition.get("title", definition_name)
    lines = [f".. _{anchor}:", "", title, "~" * len(title), ""]
    if definition.get("description"):
        lines.extend((definition["description"], ""))
    lines.extend(_field_table(definition, include=include, exclude=exclude))
    return lines


def _discriminator_mapping(
    definitions: dict[str, Any], name: str
) -> dict[str, str]:
    definition = definitions[name]
    mapping = definition.get("discriminator", {}).get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(f"$defs.{name} has no discriminator mapping")
    return {key: _reference_name(reference) for key, reference in mapping.items()}


def _common_step_fields(
    definitions: dict[str, Any], step_names: list[str]
) -> set[str]:
    property_sets = [set(definitions[name].get("properties", {})) for name in step_names]
    common = set.intersection(*property_sets)
    result: set[str] = set()
    for field_name in common:
        values = [definitions[name]["properties"][field_name] for name in step_names]
        if all(value == values[0] for value in values[1:]):
            result.add(field_name)
    return result


def render_reference(schema: dict[str, Any]) -> str:
    """Render deterministic RST using only a parsed JSON Schema document."""
    definitions = schema["$defs"]
    steps = _discriminator_mapping(definitions, "Step")
    inputs = _discriminator_mapping(definitions, "InputMapping")
    outputs = _discriminator_mapping(definitions, "OutputMapping")
    common_fields = _common_step_fields(definitions, list(steps.values()))

    lines = [
        ".. SPDX-FileCopyrightText: 2026 CERN <home.cern>",
        "..",
        ".. SPDX-License-Identifier: CC-BY-SA-4.0",
        "..",
        ".. Generated from recipe_language.schema.json. Do not edit manually.",
        "",
        "Recipe Language 2.0 Reference",
        "=============================",
        "",
        "This page is generated from the current build's aggregate JSON Schema. It",
        "describes",
        "the accepted future recipe language model; production execution still uses",
        "the version 1 language until Phase 6 integration is complete.",
        "",
        ":download:`Download the JSON Schema <recipe_language.schema.json>`.",
        "",
        "See :doc:`/recipe_language_architecture` for parsing, semantic rules,",
        "documentation maintenance, and the planned YamVIEW and sequencer flows.",
        "",
        "Documents",
        "---------",
        "",
    ]
    # REUSE-IgnoreEnd
    lines.extend(_model_section("RecipeHeader", definitions, "recipe-v2-header"))
    lines.extend(_model_section("Sequence", definitions, "recipe-v2-sequence"))

    lines.extend(("Nested structures", "-----------------", ""))
    for name in ("InternalSequenceReference", "FileDestination", "UploadFile"):
        lines.extend(_model_section(name, definitions, f"recipe-v2-structure-{name.lower()}"))

    lines.extend(("Common step fields", "------------------", ""))
    representative = next(iter(steps.values()))
    lines.extend(_field_table(definitions[representative], include=common_fields))

    lines.extend(("Authorable steps", "----------------", ""))
    for discriminator, definition_name in steps.items():
        lines.extend(_model_section(
            definition_name,
            definitions,
            f"recipe-v2-step-{discriminator.lower()}",
            exclude=common_fields,
        ))

    lines.extend(("Input mappings", "--------------", ""))
    for discriminator, definition_name in inputs.items():
        lines.extend(_model_section(
            definition_name, definitions, f"recipe-v2-input-{discriminator}"
        ))

    lines.extend(("Output mappings", "---------------", ""))
    for discriminator, definition_name in outputs.items():
        lines.extend(_model_section(
            definition_name, definitions, f"recipe-v2-output-{discriminator}"
        ))
    return "\n".join(lines).rstrip() + "\n"


def render_reference_file(path: str | Path) -> str:
    return render_reference(load_schema(path))
