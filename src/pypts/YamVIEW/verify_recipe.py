# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""YamVIEW compatibility wrappers around the production recipe parser."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pypts.recipe_parser import Diagnostic, parse_recipe_file, parse_recipe_text


def format_diagnostic(diagnostic: Diagnostic) -> str:
    """Format one structured parser finding for display in YamVIEW."""
    source = diagnostic.source_name or "<recipe>"
    location = source
    if diagnostic.span is not None:
        start = diagnostic.span.start
        end = diagnostic.span.end
        location += f":{start.line}:{start.column}-{end.line}:{end.column}"
    path = "".join(
        f"[{part}]" if isinstance(part, int) else (f".{part}" if index else str(part))
        for index, part in enumerate(diagnostic.path)
    )
    if path:
        location += f" ({path})"
    return f"[{diagnostic.code}] {location}: {diagnostic.message}"


class RecipeValidationError(Exception):
    """Compatibility exception containing formatted production diagnostics."""

    def __init__(
        self,
        faults: Iterable[str],
        warnings: Iterable[str] = (),
        diagnostics: Iterable[Diagnostic] = (),
    ):
        self.faults = list(faults)
        self.warnings = list(warnings)
        self.diagnostics = tuple(diagnostics)
        message = f"Validation failed with {len(self.faults)} faults and {len(self.warnings)} warnings"
        if self.faults or self.warnings:
            message += ":\n" + "\n".join((*self.faults, *self.warnings))
        super().__init__(message)


def _raise_for_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> None:
    faults = [format_diagnostic(item) for item in diagnostics if item.severity == "error"]
    warnings = [format_diagnostic(item) for item in diagnostics if item.severity == "warning"]
    if faults or warnings:
        raise RecipeValidationError(faults, warnings, diagnostics)


def validate_recipe_file(filepath) -> None:
    """Raise :class:`RecipeValidationError` unless *filepath* is valid v2."""
    result = parse_recipe_file(filepath)
    _raise_for_diagnostics(result.diagnostics)


def validate_recipe_filepath(file_path) -> bool:
    """Return whether *file_path* contains a valid recipe-language 2 recipe."""
    try:
        validate_recipe_file(file_path)
    except RecipeValidationError:
        return False
    return True


def validate_recipe_string_variable(content: str) -> tuple[bool, str]:
    """Validate edited YAML text and return YamVIEW's historical tuple result."""
    result = parse_recipe_text(content, "<editor>")
    if result.diagnostics:
        messages = "\n".join(format_diagnostic(item) for item in result.diagnostics)
        return False, messages
    return True, "Validation passed for the variable recipe."


validate_recipe_string = validate_recipe_string_variable


def validate_all_recipes_in_folder(folder_path):
    errors = []
    for path in Path(folder_path).iterdir():
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                validate_recipe_file(path)
            except RecipeValidationError as error:
                errors.append((path.name, error))
    return not errors


def validate_all_recipes_in_folders(folder_paths):
    if isinstance(folder_paths, (str, Path)):
        folder_paths = [folder_paths]
    errors = []
    for folder_path in folder_paths:
        for path in Path(folder_path).iterdir():
            if path.suffix.lower() in {".yaml", ".yml"}:
                try:
                    validate_recipe_file(path)
                except RecipeValidationError as error:
                    errors.append((path.name, error, str(folder_path)))
    return errors
