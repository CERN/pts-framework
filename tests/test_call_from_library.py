import sys
import os
from PyQt6.QtWidgets import QApplication
from pypts import run_recipe_app

def main():
    # Create the QApplication instance
    app = QApplication(sys.argv)
    
    # Get the path to the example recipe
    recipe_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'pypts', 'recipes', 'example_recipe.yml')
    
    # Run the recipe app - this will create the window and set up the recipe
    window, app = run_recipe_app(recipe_path, sequence_name="Main")
    
    # Start the Qt event loop
    exit_code = app.exec()
    
    # Exit with the application's exit code
    sys.exit(exit_code)

if __name__ == '__main__':
    main()
