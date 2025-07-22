import sys
import logging
import atexit
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread
from pypts.pts import run_pts
from pypts.gui import MainWindow
from pypts.event_proxy import RecipeEventProxy

logger = logging.getLogger(__name__)
_recipe_thread = None  # internal reference for cleanup

def _cleanup_thread():
    global _recipe_thread
    if _recipe_thread and _recipe_thread.isRunning():
        logger.debug("Stopping recipe event processing thread...")
        _recipe_thread.quit()
        _recipe_thread.wait(5000)
        if _recipe_thread.isRunning():
            logger.warning("Thread did not stop gracefully, terminating...")
            _recipe_thread.terminate()

def create_and_start_gui(recipe_path: str, sequence_name: str = "Main"):
    """Creates and starts the GUI with threading and signal connections.

    Returns:
        window (MainWindow): The main GUI window.
        app (QApplication): The Qt application instance.
    """
    global _recipe_thread

    app = QApplication(sys.argv)
    window = MainWindow()

    logging.getLogger().addHandler(window.log_handler)

    api = run_pts(recipe_path, sequence_name=sequence_name)
    window.q_in = api.input_queue

    recipe_event_processing_thread = QThread()
    recipe_event_processing_thread.setParent(app)
    _recipe_thread = recipe_event_processing_thread

    recipe_event_proxy = RecipeEventProxy(api.event_queue)
    recipe_event_proxy.moveToThread(recipe_event_processing_thread)
    recipe_event_processing_thread.started.connect(recipe_event_proxy.run)

    # Connect signals from proxy to GUI
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

    atexit.register(_cleanup_thread)
    app.aboutToQuit.connect(_cleanup_thread)

    # Temporary workaround for thread startup race
    time.sleep(1)

    return window, app