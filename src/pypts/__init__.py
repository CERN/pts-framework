from ._version import version as __version__

import logging
import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread
from pypts.pts import run_pts
from pypts.gui import MainWindow
from pypts.event_proxy import RecipeEventProxy

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
    # Ensure QApplication instance exists. If running from another Qt app,
    # it might already exist.
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    window = MainWindow()

    logging.getLogger().addHandler(window.log_handler)

    api = run_pts(recipe_path, sequence_name=sequence_name)
    window.q_in = api.input_queue
    recipe_event_processing_thread = QThread()
    # Make the thread a child of the app or window to ensure it's cleaned up
    recipe_event_processing_thread.setParent(app) 
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

    # If this function is called, it means we are running it as a library.
    # We should not call app.exec() if a QApplication already exists and is running.
    # However, if we created the app, we need to run its event loop.
    # A simple way to manage this is to let the caller handle the app.exec() if they create the app.
    # For now, let's assume if we created the app, we run exec.
    # A more robust solution might involve checking QApplication.instance().thread()
    # or passing a flag.
    
    # If we created the app, we need to start the event loop.
    # If an event loop is already running, this call will do nothing.
    # current_app = QApplication.instance()
    # if not current_app or current_app.thread() != QThread.currentThread():
    #      # Only call exec if we created the app or if no event loop is running for the app
    #     if app is QApplication.instance() and not any(isinstance(widget, MainWindow) for widget in QApplication.topLevelWidgets()):
    #          # If we created the app and there's no main window yet (or this one)
    #          # This logic might need refinement depending on how it's called from another Qt app.
    #          pass # Do not call exec yet, let main window show handle it.

    # window.show() # Show the window << REMOVED THIS LINE

    # It's important that app.exec() is called for the GUI to run.
    # If this `run_recipe_app` is the main entry point for a script,
    # then app.exec() should be called after this function returns,
    # or the main script should handle it.
    # For now, let's return the app and window, so the caller can decide.
    # However, your __main__.py will need to call app.exec().
    
    # Let's simplify: if this function is called, it should try to run the app.
    # If an app is already running, exec() might not be needed or behave differently.
    # The window.show() should make it visible.

    # The app.exec() call is blocking. If called from another script,
    # that script will block here until the GUI is closed.

    # Return the window instance in case the caller wants to interact with it.
    # The event loop is managed by app.exec(), which should be called by the top-level script.
    return window, app
