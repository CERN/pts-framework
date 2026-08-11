# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Generate the standalone reference for the pypts recipe language."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any

import yaml

from pypts.recipe_language import (
    CANONICAL_RECIPE_VERSION,
    COMMON_STEP_FIELDS,
    CONSTRAINT_SPECS,
    FieldSpec,
    HEADER_SPEC,
    INPUT_MAPPING_SPECS,
    MappingSpec,
    OUTPUT_MAPPING_SPECS,
    SEQUENCE_SPEC,
    STEP_SPECS,
    StepSpec,
)
from pypts.recipe_parser import dump_recipe, parse_recipe_text


DEFAULT_REFERENCE_PATH = Path("docs/generated/recipe_language_reference.rst")


def _header() -> dict[str, Any]:
    return {
        "name": "Recipe language reference fixture",
        "version": "1.0",
        "recipe_version": CANONICAL_RECIPE_VERSION,
        "description": "Executable generated-reference fixture.",
        "main_sequence": "Main",
        "globals": {
            "ssh_client": None,
            "host": "target",
            "user": "root",
            "port": 22,
            "password": "secret",
        },
    }


def _sequence(name: str, steps: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "sequence_name": name,
        "description": f"{name} sequence.",
        "parameters": {},
        "outputs": {},
        "locals": {"local_value": 1},
        "setup_steps": [],
        "steps": list(steps or []),
        "teardown_steps": [],
    }


def _documents_with_step(step: Mapping[str, Any]) -> list[dict[str, Any]]:
    authored = dict(step)
    main = _sequence("Main", [authored])
    documents = [_header(), main]
    if authored.get("steptype") == "SequenceStep":
        target = authored.get("sequence", {}).get("name")
        if isinstance(target, str) and target != "Main":
            documents.append(_sequence(target))
    if authored.get("steptype") == "SSHUploadStep":
        main["setup_steps"] = [{
            "steptype": "SSHConnectStep",
            "step_name": "Connect",
            "description": "Open the fixture connection.",
        }]
        main["teardown_steps"] = [{
            "steptype": "SSHCloseStep",
            "step_name": "Close",
            "description": "Close the fixture connection.",
        }]
    return documents


def _fixture_text(step: Mapping[str, Any]) -> str:
    return yaml.safe_dump_all(
        _documents_with_step(step),
        explicit_start=True,
        sort_keys=False,
        allow_unicode=True,
    )


def _canonical_step_example(spec: StepSpec) -> Mapping[str, Any]:
    result = parse_recipe_text(_fixture_text(spec.example), f"reference:{spec.name}")
    if result.diagnostics:
        details = "; ".join(f"{item.code}: {item.message}" for item in result.diagnostics)
        raise ValueError(f"Invalid canonical example for {spec.name}: {details}")
    documents = list(yaml.safe_load_all(dump_recipe(result.require_recipe())))
    main = next(document for document in documents[1:] if document["sequence_name"] == "Main")
    return main["steps"][0]


def _validate_mapping_example(spec: MappingSpec, *, output: bool) -> None:
    step: dict[str, Any] = {
        "steptype": "PythonModuleStep",
        "step_name": f"{spec.name} mapping",
        "description": "Executable mapping fixture.",
        "action_type": "method",
        "module": "tests.py",
        "method_name": "run",
        "input_mapping": {},
        "output_mapping": {},
    }
    mapping_name = "output_mapping" if output else "input_mapping"
    step[mapping_name] = {"example": dict(spec.example)}
    result = parse_recipe_text(_fixture_text(step), f"reference:{mapping_name}:{spec.name}")
    if result.diagnostics:
        details = "; ".join(f"{item.code}: {item.message}" for item in result.diagnostics)
        raise ValueError(f"Invalid {mapping_name} example for {spec.name}: {details}")


def _type_name(field: FieldSpec) -> str:
    if field.value_type is None:
        return "any"
    values = field.value_type if isinstance(field.value_type, tuple) else (field.value_type,)
    return " or ".join(value.__name__ for value in values)


def _literal(value: Any) -> str:
    if value == {}:
        return "{}"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _requirement(field: FieldSpec) -> str:
    parts = ["required" if field.required else "optional"]
    if field.has_default:
        parts.append(f"default: ``{_literal(field.default)}``")
    if field.choices:
        choices = ", ".join(f"``{_literal(value)}``" for value in field.choices)
        parts.append(f"allowed: {choices}")
    if field.legacy:
        parts.append("legacy")
    return "; ".join(parts)


def _field_table(fields: Sequence[FieldSpec]) -> list[str]:
    lines = [
        ".. list-table::",
        "   :header-rows: 1",
        "   :widths: 18 14 28 40",
        "",
        "   * - Field",
        "     - Type",
        "     - Requirement",
        "     - Description",
    ]
    for field in fields:
        lines.extend((
            f"   * - ``{field.name}``",
            f"     - {_type_name(field)}",
            f"     - {_requirement(field)}",
            f"     - {field.description}",
        ))
    return lines


def _yaml_block(value: Mapping[str, Any]) -> list[str]:
    rendered = yaml.safe_dump(
        dict(value), sort_keys=False, default_flow_style=False, allow_unicode=True,
    ).rstrip()
    return [".. code-block:: yaml", ""] + [f"   {line}" for line in rendered.splitlines()]


def _mapping_section(title: str, specs: Sequence[MappingSpec], prefix: str) -> list[str]:
    lines = [title, "-" * len(title), ""]
    for spec in specs:
        lines.extend((
            f".. _recipe-{prefix}-{spec.name}:",
            "",
            f"**``{spec.name}``**",
            "",
            spec.description,
            "",
        ))
        lines.extend(_field_table(spec.fields))
        lines.extend(("", "Canonical mapping:", ""))
        lines.extend(_yaml_block(spec.example))
        lines.append("")
    return lines


def render_recipe_reference() -> str:
    """Render the deterministic standalone recipe-language RST reference."""
    public_steps = tuple(spec for spec in STEP_SPECS if spec.source_allowed)
    examples = {spec.name: _canonical_step_example(spec) for spec in public_steps}
    for spec in INPUT_MAPPING_SPECS:
        _validate_mapping_example(spec, output=False)
    for spec in OUTPUT_MAPPING_SPECS:
        _validate_mapping_example(spec, output=True)

    lines = [
        ".. SPDX-FileCopyrightText: 2026 CERN <home.cern>",
        "..",
        ".. SPDX-License-Identifier: CC-BY-SA-4.0",
        "..",
        ".. This file is generated by pypts.recipe_reference. Do not edit it manually.",
        "",
        "Recipe Language Reference",
        "=========================",
        "",
        f"Canonical recipe language version: ``{CANONICAL_RECIPE_VERSION}``.",
        "",
        "Document grammar",
        "----------------",
        "",
        "A recipe is safe multi-document YAML. The first document is one recipe",
        "header and every following document is one sequence. At least one sequence",
        "is required, and ``main_sequence`` must name one of them.",
        "",
        "Recipe header",
        "-------------",
        "",
        HEADER_SPEC.description,
        "",
    ]
    lines.extend(_field_table(HEADER_SPEC.fields))
    lines.extend(("", "Sequence", "--------", "", SEQUENCE_SPEC.description, ""))
    lines.extend(_field_table(SEQUENCE_SPEC.fields))
    lines.extend((
        "",
        "Common step fields",
        "------------------",
        "",
        "These fields are shared by every authorable step type.",
        "",
    ))
    lines.extend(_field_table(COMMON_STEP_FIELDS))
    lines.extend(("", "Registered step types", "---------------------", ""))
    common_names = {field.name for field in COMMON_STEP_FIELDS}
    for spec in public_steps:
        lines.extend((
            f".. _recipe-step-{spec.name.lower()}:",
            "",
            spec.name,
            "~" * len(spec.name),
            "",
            spec.description,
            "",
        ))
        specific_fields = tuple(field for field in spec.fields if field.name not in common_names)
        if specific_fields:
            lines.extend(_field_table(specific_fields))
            lines.append("")
        if spec.required_inputs:
            required = ", ".join(f"``{name}``" for name in spec.required_inputs)
            lines.extend((f"Required input names: {required}.", ""))
        lines.extend(("Canonical example:", ""))
        lines.extend(_yaml_block(examples[spec.name]))
        lines.append("")
    lines.extend(_mapping_section("Input mapping types", INPUT_MAPPING_SPECS, "input"))
    lines.extend(_mapping_section("Output mapping types", OUTPUT_MAPPING_SPECS, "output"))
    lines.extend(("Semantic constraints", "--------------------", ""))
    for constraint in CONSTRAINT_SPECS:
        diagnostics = ", ".join(f"``{code}``" for code in constraint.diagnostic_codes)
        lines.extend((
            f"* ``{constraint.scope}`` — {constraint.description}",
            f"  Diagnostics: {diagnostics}.",
        ))
    lines.extend((
        "",
        "Canonicalization",
        "----------------",
        "",
        "The parser normalizes step type casing, implicit direct inputs, mapping",
        "defaults, and optional flags. Canonical serialization uses explicit YAML",
        "document starts and stable field ordering. Comments and original formatting",
        "are not preserved; parse/dump/reparse model equality is the guarantee.",
        "",
        "``IndexedStep`` is reserved for runtime construction and cannot be authored",
        "as a recipe step.",
        "",
    ))
    return "\n".join(lines)


def write_recipe_reference(path: str | Path = DEFAULT_REFERENCE_PATH) -> None:
    """Write the generated reference, creating its parent directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_recipe_reference(), encoding="utf-8")


def check_recipe_reference(path: str | Path = DEFAULT_REFERENCE_PATH) -> bool:
    """Return whether an existing reference exactly matches generated output."""
    destination = Path(path)
    try:
        current = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return current == render_recipe_reference()


def main(argv: Sequence[str] | None = None) -> int:
    """Generate or check the standalone reference artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument("--check", action="store_true", help="fail if the artifact is missing or stale")
    arguments = parser.parse_args(argv)
    if arguments.check:
        if check_recipe_reference(arguments.path):
            return 0
        print(f"Recipe language reference is missing or stale: {arguments.path}", file=sys.stderr)
        return 1
    try:
        write_recipe_reference(arguments.path)
    except OSError as error:
        print(f"Could not write recipe language reference: {error}", file=sys.stderr)
        return 2
    print(f"Wrote recipe language reference: {arguments.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
