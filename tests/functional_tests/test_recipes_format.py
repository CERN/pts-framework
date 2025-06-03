# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest
from pypts.verify_recipe import validate_all_recipes_in_folder
from pypts.utils import get_project_root

def test_recipes_format():
    recipe_path = get_project_root() / "src" / "pypts" / "recipes"
    assert validate_all_recipes_in_folder(recipe_path)