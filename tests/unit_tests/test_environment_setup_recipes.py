# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Environment setup commands copy valid recipe-language 2 templates."""

from pypts.examples.environment_setup_tools.Minimal_setup import init_env_min
from pypts.examples.environment_setup_tools.Package_based_setup import init_env_pack
from pypts.recipe_parser import parse_recipe_file


def test_minimal_setup_copies_a_valid_v2_recipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_env_min.main()

    copied = tmp_path / "Minimal_setup_recipe.yml"
    result = parse_recipe_file(copied)
    assert result.is_valid, result.errors
    assert result.require_recipe().header.recipe_version == "2.0.0"


def test_package_setup_copies_a_valid_v2_recipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(init_env_pack.subprocess, "check_call", lambda command: None)
    init_env_pack.main()

    copied = (
        tmp_path / "src" / "example_package" / "resources" / "Package_based_recipe.yml"
    )
    result = parse_recipe_file(copied)
    assert result.is_valid, result.errors
    assert result.require_recipe().header.recipe_version == "2.0.0"
