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
    app = QApplication(sys.argv)
    window = MainWindow()

    logging.getLogger().addHandler(window.log_handler)

    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'example_recipe.yml')
    api = run_pts(yaml_path, sequence_name="Main")
    window.q_in = api.input_queue
    recipe_event_processing_thread = QThread()
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

    exit_code = app.exec()
    
    sys.exit(exit_code)
