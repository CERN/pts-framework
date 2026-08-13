# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Phase 5 checks for schema-driven recipe-language documentation."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from spikes.recipe_pydantic.artifacts import (
    main,
    render_json_schema,
    rendered_artifacts,
    write_artifacts,
)
from spikes.recipe_pydantic.parser import (
    dump_recipe,
    parse_recipe_file,
    parse_recipe_text,
)
from spikes.recipe_pydantic.reference import render_reference

ROOT = Path(__file__).parents[2]
DOC_RECIPE = ROOT / "docs" / "source" / "_examples" / "recipe_v2.yml"
ARCHITECTURE = ROOT / "docs" / "source" / "recipe_language_architecture.rst"
REFERENCE_RENDERER = ROOT / "spikes" / "recipe_pydantic" / "reference.py"


def _mapping(schema, name):
    return schema["$defs"][name]["discriminator"]["mapping"]


def test_schema_and_reference_generation_is_deterministic():
    schema_text, reference = rendered_artifacts()
    schema = json.loads(schema_text)
    assert schema_text == render_json_schema()
    assert reference == render_reference(schema)
    assert (schema_text, reference) == rendered_artifacts()


def test_check_mode_detects_stale_artifacts_without_writing(tmp_path):
    schema_path = tmp_path / "recipe.schema.json"
    reference_path = tmp_path / "reference.rst"
    write_artifacts(schema_path, reference_path)
    assert main([
        "--check", "--schema", str(schema_path), "--reference", str(reference_path)
    ]) == 0

    reference_path.write_text("stale\n", encoding="utf-8")
    assert main([
        "--check", "--schema", str(schema_path), "--reference", str(reference_path)
    ]) == 1
    assert reference_path.read_text(encoding="utf-8") == "stale\n"


def test_every_discriminator_is_rendered_once():
    schema_text, reference = rendered_artifacts()
    schema = json.loads(schema_text)
    for group, definition in (
        ("step", "Step"),
        ("input", "InputMapping"),
        ("output", "OutputMapping"),
    ):
        for discriminator in _mapping(schema, definition):
            anchor = f".. _recipe-v2-{group}-{discriminator.lower()}:"
            assert reference.count(anchor) == 1


def test_reference_metadata_comes_from_json_schema():
    schema_text, reference = rendered_artifacts()
    schema = json.loads(schema_text)
    direct = schema["$defs"]["DirectInput"]["properties"]["indexed"]
    assert direct["description"] in reference
    assert f"default ``{json.dumps(direct['default'])}``" in reference
    assert f"Example: ``{json.dumps(direct['examples'][0])}``." in reference
    assert "``bool``" in reference
    assert "``min``" in reference and "``max``" in reference
    assert "``value``" in reference and "required" in reference


def test_json_only_renderer_has_no_model_runtime_ui_or_sphinx_imports():
    tree = ast.parse(REFERENCE_RENDERER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "pydantic",
        "spikes.recipe_pydantic.models",
        "pypts.recipe",
        "pypts.steps",
        "pypts.YamVIEW",
        "sphinx",
    }
    assert not any(
        name == item or name.startswith(item + ".")
        for name in imported
        for item in forbidden
    )


def test_documentation_recipe_is_warning_free_and_model_stable():
    first = parse_recipe_file(DOC_RECIPE)
    assert first.is_valid, first.errors
    assert not first.warnings
    second = parse_recipe_text(dump_recipe(first.require_recipe()), "canonical:recipe_v2.yml")
    assert second.is_valid, second.errors
    assert not second.warnings
    assert second.recipe == first.recipe


def test_literalinclude_markers_are_unique_and_paired():
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    sources = {
        "models.py": (ROOT / "spikes" / "recipe_pydantic" / "models.py").read_text(
            encoding="utf-8"
        ),
        "parser.py": (ROOT / "spikes" / "recipe_pydantic" / "parser.py").read_text(
            encoding="utf-8"
        ),
    }
    markers = (
        ("models.py", "indexed-direct"),
        ("models.py", "method-name"),
        ("models.py", "wait-time"),
        ("parser.py", "sequence-semantics"),
        ("parser.py", "nested-reference"),
        ("parser.py", "mapping-semantics"),
        ("parser.py", "ssh-semantics"),
    )
    for filename, name in markers:
        start = f"# docs:{name}-start"
        end = f"# docs:{name}-end"
        assert sources[filename].count(start) == 1
        assert sources[filename].count(end) == 1
        assert architecture.count(start) == 1
        assert architecture.count(end) == 1


def test_sphinx_sources_link_reference_schema_and_example():
    index = (ROOT / "docs" / "source" / "index.rst").read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    assert "_generated/recipe_language_reference" in index
    assert "_generated/recipe_language.schema.json" in architecture
    assert "_examples/recipe_v2.yml" in architecture
