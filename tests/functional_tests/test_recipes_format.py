import pytest
from pypts.verify_recipe import validate_all_recipes_in_folder
from pypts.utils import get_project_root

def test_recipes_format():
    recipe_path = get_project_root() / "src" / "pypts" / "recipes"
    assert validate_all_recipes_in_folder(recipe_path)