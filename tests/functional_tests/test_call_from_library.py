import pytest
import os
from PyQt6.QtWidgets import QApplication
from pypts import run_recipe_app

@pytest.fixture
def recipe_path():
    """Get the path to the example recipe."""
    return os.path.join(os.path.dirname(__file__), '..', 'src', 'pypts', 'recipes', 'example_recipe.yml')

def test_run_recipe_app(app, recipe_path):
    """Test that the recipe app can be launched and runs successfully."""
    # Run the recipe app - this will create the window and set up the recipe
    window, app = run_recipe_app(recipe_path, sequence_name="Main")
    
    # Verify the window was created
    assert window is not None
    
    # Verify the app was created
    assert app is not None
    
    # Process events to ensure the window is properly initialized
    app.processEvents()
    
    # Clean up
    window.close()
