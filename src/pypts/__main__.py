# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# This file defines the script entry point for the PTS application.
#
# It allows the GUI to be launched directly by running:
#     python -m pypts
#
# It sets up the full application stack: GUI, threading, event proxy, and recipe execution.
# Intended for end users or developers running the app manually with a fixed recipe path.
#
# For programmatic use (e.g., testing or embedding), use `run_recipe_app()` in `__init__.py` instead.

from pypts._version import version as __version__
import logging
import sys
from pypts.pts import run_pts
from pypts.startup import create_and_start_gui

logger = logging.getLogger(__name__)

# Configure basic logging
log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)
# Reduce verbosity of noisy libraries
logging.getLogger("paramiko.transport").setLevel("WARN")


if __name__ == '__main__':
    """Main entry point for the PTS application.
    
    Sets up the QApplication, MainWindow, logging, RecipeEventProxy, 
    and connects signals/slots between the proxy and the window.
    Starts the recipe execution and event processing threads.
    """
    recipe_file="./src/pypts/recipes/comprehensive_recipe.yml"

    api = run_pts()
    
    window, app = create_and_start_gui(api)

    exit_code = app.exec()
    sys.exit(exit_code)
