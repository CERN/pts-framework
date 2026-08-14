# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Public production parser API checks."""

from pypts.recipe_parser import RecipeParseError, parse_recipe_file, parse_recipe_text


def test_invalid_file_result_raises_structured_parse_error(tmp_path):
    path = tmp_path / "legacy.yml"
    path.write_text("name: legacy\nrecipe_version: 1.0.0\n", encoding="utf-8")
    result = parse_recipe_file(path)
    assert result.errors
    try:
        result.require_recipe()
    except RecipeParseError as error:
        assert error.diagnostics == result.diagnostics
    else:
        raise AssertionError("require_recipe() accepted an invalid recipe")


def test_non_text_source_is_a_structured_error():
    result = parse_recipe_text(None)  # type: ignore[arg-type]
    assert [item.code for item in result.errors] == ["invalid-source"]
