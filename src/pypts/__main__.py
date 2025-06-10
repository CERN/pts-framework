# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from queue import SimpleQueue
from contextlib import suppress
from pypts.pts import run_pts
from pypts import recipe
import os
from pypts.gui import MainWindow, TextEditLoggerHandler # Import necessary GUI classes
import uuid # Import uuid
from pypts.event_proxy import RecipeEventProxy # Import the proxy class
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

if __name__ == '__main__':
    """Main entry point for the PTS application.
    
    Sets up the QApplication, MainWindow, logging, RecipeEventProxy, 
    and connects signals/slots between the proxy and the window.
    Starts the recipe execution and event processing threads.
    """
    
    app = QApplication(sys.argv)
    window = MainWindow()

    logging.getLogger().addHandler(window.log_handler)

    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'simple_recipe.yml')
    api = run_pts(yaml_path, sequence_name="Main")
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

    # Connect new signals
    recipe_event_proxy.post_load_recipe_signal.connect(window.handle_post_load_recipe)
    recipe_event_proxy.post_run_sequence_signal.connect(window.handle_post_run_sequence)

    recipe_event_processing_thread.start()

    # Register cleanup function
    atexit.register(_cleanup_thread)
    
    # Connect app aboutToQuit signal to cleanup
    app.aboutToQuit.connect(_cleanup_thread)

    exit_code = app.exec()
    
    sys.exit(exit_code)
