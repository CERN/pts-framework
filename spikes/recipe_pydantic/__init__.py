"""Isolated Pydantic prototype for recipe-language version 2."""

from importlib import import_module
from typing import Any

_PARSER_EXPORTS = {
    "Diagnostic",
    "ParseResult",
    "RecipeParseError",
    "SourcePosition",
    "SourceSpan",
    "dump_recipe",
    "parse_recipe_file",
    "parse_recipe_text",
}


def __getattr__(name: str) -> Any:
    """Keep JSON-only submodules importable without initializing Pydantic."""
    if name == "Recipe":
        return getattr(import_module(".models", __name__), name)
    if name in _PARSER_EXPORTS:
        return getattr(import_module(".parser", __name__), name)
    raise AttributeError(name)


def render_json_schema() -> str:
    return import_module(".artifacts", __name__).render_json_schema()


def render_reference() -> str:
    return import_module(".artifacts", __name__).rendered_artifacts()[1]


__all__ = [
    "Diagnostic",
    "ParseResult",
    "Recipe",
    "RecipeParseError",
    "SourcePosition",
    "SourceSpan",
    "dump_recipe",
    "parse_recipe_file",
    "parse_recipe_text",
    "render_json_schema",
    "render_reference",
]
