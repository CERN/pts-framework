# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from ._version import version as __version__

import logging
import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread
from pypts.pts import run_pts
from pypts.gui import MainWindow
from pypts.event_proxy import RecipeEventProxy
import time
import atexit

logger = logging.getLogger(__name__)

# Configure basic logging
log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)
# Reduce verbosity of noisy libraries
logging.getLogger("paramiko.transport").setLevel("WARN")

# Global variable to track the thread for cleanup
_recipe_thread = None

def _cleanup_thread():
    """Cleanup function to properly stop the recipe event processing thread."""
    global _recipe_thread
    if _recipe_thread and _recipe_thread.isRunning():
        logger.debug("Stopping recipe event processing thread...")
        _recipe_thread.quit()
        _recipe_thread.wait(5000)  # Wait up to 5 seconds for thread to finish
        if _recipe_thread.isRunning():
            logger.warning("Thread did not stop gracefully, terminating...")
            _recipe_thread.terminate()

def run_recipe_app(recipe_path: str, sequence_name: str = "Main"):
    """Runs the PTS application with the given recipe file.
    
    Sets up the QApplication, MainWindow, logging, RecipeEventProxy, 
    and connects signals/slots between the proxy and the window.
    Starts the recipe execution and event processing threads.
    """
    global _recipe_thread
    
    app = QApplication(sys.argv) # Only one instance of QApplication is allowed
    
    window = MainWindow()

    logging.getLogger().addHandler(window.log_handler)

    api = run_pts(recipe_path, sequence_name=sequence_name)
    window.q_in = api.input_queue
    recipe_event_processing_thread = QThread()
    # Make the thread a child of the app to ensure it's cleaned up
    recipe_event_processing_thread.setParent(app) 
    
    # Store reference for cleanup
    _recipe_thread = recipe_event_processing_thread
    
    recipe_event_proxy = RecipeEventProxy(api.event_queue)
    recipe_event_proxy.moveToThread(recipe_event_processing_thread)
    recipe_event_processing_thread.started.connect(recipe_event_proxy.run)

    recipe_event_proxy.pre_run_recipe_signal.connect(window.update_recipe_name)
    recipe_event_proxy.post_run_recipe_signal.connect(window.show_results)
    recipe_event_proxy.pre_run_sequence_signal.connect(window.update_sequence)
    recipe_event_proxy.post_run_step_signal.connect(window.update_step_result)
    recipe_event_proxy.pre_run_step_signal.connect(window.update_running_step)
    recipe_event_proxy.user_interact_signal.connect(window.show_message)
    recipe_event_proxy.get_serial_number_signal.connect(window.get_serial_number)
    recipe_event_proxy.post_load_recipe_signal.connect(window.handle_post_load_recipe)
    recipe_event_proxy.post_run_sequence_signal.connect(window.handle_post_run_sequence)

    recipe_event_processing_thread.start()

    # Register cleanup function
    atexit.register(_cleanup_thread)
    
    # Connect app aboutToQuit signal to cleanup
    app.aboutToQuit.connect(_cleanup_thread)

    time.sleep(1) # Prevents a race condition. To be properly fixed!!

    # If we don't put the sleep, recipe_event_processing_thread.start() may not 
    # be finished before the app.exec() call.

    return window, app
