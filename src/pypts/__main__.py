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
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QThread
from pypts.pts import run_pts
from pypts.gui import MainWindow, TextEditLoggerHandler # Import necessary GUI classes
from pypts.event_proxy import RecipeEventProxy # Import the proxy class
from queue import SimpleQueue
from contextlib import suppress
from pypts import recipe
from pypts.startup import create_and_start_gui
import os
import uuid # Import uuid
import atexit
import time
from utils import setup_logging

# Initialize logging
logger = setup_logging()


if __name__ == '__main__':
    """Main entry point for the PTS application.
    
    Sets up the QApplication, MainWindow, logging, RecipeEventProxy, 
    and connects signals/slots between the proxy and the window.
    Starts the recipe execution and event processing threads.
    """

    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'driveFLEX_Acceptance_Tests.yml')
    # yaml_path = os.path.join(yaml_dir, 'simple_recipe.yml')

    api = run_pts(yaml_path, sequence_name="Main")

    window, app = create_and_start_gui(api)

    exit_code = app.exec()
    sys.exit(exit_code)
