"""Generate or check the documentation artifacts for recipe language 2.0."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .models import Recipe
from .reference import render_reference

ROOT = Path(__file__).parents[2]
DEFAULT_SCHEMA_PATH = ROOT / "docs" / "source" / "_static" / "recipe_language.schema.json"
DEFAULT_REFERENCE_PATH = ROOT / "docs" / "source" / "recipe_language_reference.rst"


def render_json_schema() -> str:
    """Render deterministic JSON Schema from the accepted Pydantic model."""
    schema = Recipe.model_json_schema(by_alias=True, mode="validation")
    schema["$comment"] = (
        "SPDX-FileCopyrightText: 2026 CERN <home.cern>; "
        "SPDX-License-Identifier: CC-BY-SA-4.0"
    )
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def rendered_artifacts() -> tuple[str, str]:
    schema_text = render_json_schema()
    reference_text = render_reference(json.loads(schema_text))
    return schema_text, reference_text


def write_artifacts(
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    reference_path: str | Path = DEFAULT_REFERENCE_PATH,
) -> None:
    schema_text, reference_text = rendered_artifacts()
    for path, content in (
        (Path(schema_path), schema_text),
        (Path(reference_path), reference_text),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def check_artifacts(
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    reference_path: str | Path = DEFAULT_REFERENCE_PATH,
) -> bool:
    expected = rendered_artifacts()
    try:
        current = (
            Path(schema_path).read_text(encoding="utf-8"),
            Path(reference_path).read_text(encoding="utf-8"),
        )
    except (OSError, UnicodeError):
        return False
    return current == expected


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if either artifact is stale")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.check:
        if check_artifacts(arguments.schema, arguments.reference):
            return 0
        print("Recipe documentation artifacts are missing or stale.", file=sys.stderr)
        return 1
    try:
        write_artifacts(arguments.schema, arguments.reference)
    except OSError as error:
        print(f"Could not write recipe documentation artifacts: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {arguments.schema}")
    print(f"Wrote {arguments.reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
