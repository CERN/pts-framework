# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
import os
from PyQt6.QtWidgets import QApplication
from pypts import run_recipe_app

def main():
    # Get the path to the example recipe
    recipe_path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'pypts', 'recipes', 'simple_recipe.yml')
    
    # Run the recipe app - this will create the window and set up the recipe
    window, app = run_recipe_app(recipe_path, sequence_name="Main")
    
    # Start the Qt event loop
    exit_code = app.exec()
    
    # Exit with the application's exit code
    sys.exit(exit_code)

if __name__ == '__main__':
    main()