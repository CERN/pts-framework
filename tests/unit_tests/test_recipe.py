# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Recipe module (src/pypts/recipe/).

SKELETON ONLY - placeholders declaring intended coverage. recipe/recipe.py is
currently a single comment line; Phase 1 moves loading/parsing/validation here
from old_code/recipe.py, stripped of all execution logic.

Sample recipes live in resources/recipes/ and
resources/example_commented_recipes/.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_recipe_is_parsed_from_yaml():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_recipe_is_data_only_and_carries_no_execution_logic():
    """The old Recipe mixed data, engine and events - the split is the point of the port."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_required_header_fields_are_enforced():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_invalid_recipe_never_reaches_the_sequencer():
    """The verificator gates execution."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_every_example_recipe_in_resources_parses():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_recipe_format_version_is_checked():
    """Open roadmap item: add format_version to the header before third party plugins ship."""
    ...
