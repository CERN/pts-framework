# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Production JSON-Schema-to-RST renderer checks."""

import ast
import json
from pathlib import Path

from pypts.recipe_artifacts import render_json_schema
from pypts.recipe_reference import render_reference

ROOT = Path(__file__).parents[2]


def test_reference_renders_every_discriminator_from_generated_json():
    schema = json.loads(render_json_schema())
    rendered = render_reference(schema)
    for group, definition in (
        ("step", "StepDefinition"),
        ("input", "InputMapping"),
        ("output", "OutputMapping"),
    ):
        mapping = schema["$defs"][definition]["discriminator"]["mapping"]
        for name in mapping:
            assert rendered.count(f".. _recipe-v2-{group}-{name.lower()}:") == 1
    assert "Step definitions" in rendered
    assert "Authorable" not in rendered


def test_json_only_renderer_has_no_model_runtime_gui_or_sphinx_imports():
    tree = ast.parse(
        (ROOT / "src" / "pypts" / "recipe_reference.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    forbidden = {"pydantic", "pypts.recipe_language", "pypts.recipe", "pypts.steps", "pypts.YamVIEW", "sphinx"}
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imported
        for prefix in forbidden
    )
