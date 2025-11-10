# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# This file defines the package interface and provides reusable API entry points.
#
# In particular, `run_recipe_app()` can be imported and called to launch the GUI
# with a specified recipe path and sequence. This enables programmatic control
# for test frameworks, embedded use, or alternative frontends.
#
# For a standalone execution of the full GUI app (e.g., from the command line),
# use `__main__.py` which runs the same stack with a hardcoded recipe.


from pypts._version import version as __version__
import logging
from pypts.old_code.startup import create_and_start_gui
from pypts.pts import run_pts
from pypts.old_code.gui import MainWindow
from pypts.old_code.event_proxy import RecipeEventProxy

logger = logging.getLogger(__name__)

# Configure basic logging
log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)
# Reduce verbosity of noisy libraries
logging.getLogger("paramiko.transport").setLevel("WARN")


def run_recipe_app(recipe_path: str, sequence_name: str = "Main"):
    """Runs the PTS application with the given recipe file.

    Sets up the QApplication, MainWindow, logging, RecipeEventProxy,
    and connects signals/slots between the proxy and the window.
    Starts the recipe execution and event processing threads.
    """

    api = run_pts(recipe_path, sequence_name=sequence_name)

    window, app = create_and_start_gui(api)

    return window, app
