from ._version import version as __version__
import logging
import sys
import os # Import os for path handling if needed later
from PyQt6.QtWidgets import QApplication, QMessageBox # Import QMessageBox for potential error display
from PyQt6.QtCore import QThread
from .gui import MainWindow # Relative import for gui.py
from .pts import run_pts # Relative import for pts.py
from .event_proxy import RecipeEventProxy # Relative import for event_proxy.py

# Configure logger for the library itself
logger = logging.getLogger(__name__)
# Consider adding a NullHandler by default if this is intended purely as a library
# logging.getLogger(__name__).addHandler(logging.NullHandler())

def launch_gui(recipe_file_path: str | None = None, sequence_name: str = "Main") -> int:
    """
    Launches the PyPTS GUI application.

    Args:
        recipe_file_path: Optional path to a .yml recipe file to load immediately.
                          If None, the GUI starts without a loaded recipe,
                          allowing the user to open one via the File menu.
        sequence_name: The name of the sequence to run within the recipe
                       (default is "Main"). Only used if recipe_file_path is provided.

    Returns:
        The exit code of the QApplication.
    """
    app = QApplication.instance() # Check if an app instance exists
    if app is None: # Create one if it doesn't
        # Create the application with sys.argv ONLY if it wasn't already created
        # This prevents issues if the calling application is also Qt-based
        app_argv = sys.argv if sys.argv else [''] # Provide a default if sys.argv is empty
        app = QApplication(app_argv)

    window = MainWindow() # Create the main window instance

    # Ensure the GUI logger handler is added only once
    if window.log_handler not in logging.getLogger().handlers:
         logging.getLogger().addHandler(window.log_handler)
         logger.debug("Added MainWindow log handler to root logger.")

    # Flag to indicate if launched with a specific recipe
    launched_with_recipe = False

    if recipe_file_path:
        logger.info(f"Attempting to load recipe from: {recipe_file_path}")
        try:
            # We will call the window's method to load and run the recipe
            window.load_and_run_recipe(recipe_file_path, sequence_name)
            launched_with_recipe = True
        except FileNotFoundError:
            err_msg = f"Recipe file not found:\n{recipe_file_path}"
            logger.error(err_msg)
            window.show_error_message(err_msg) # Show error in GUI
        except Exception as e:
            err_msg = f"Failed to load recipe '{os.path.basename(recipe_file_path)}':\n{e}"
            logger.error(err_msg, exc_info=True)
            window.show_error_message(err_msg) # Show error in GUI

    # Pass the flag to the window so it knows how it was launched
    window.set_initial_launch_mode(launched_with_recipe=launched_with_recipe)

    window.show()
    exit_code = app.exec()
    logger.info(f"PyPTS GUI exiting with code {exit_code}.")
    # Perform any necessary cleanup here if needed before returning
    # e.g., explicitly stop threads if they weren't daemonized or handled by window closure.
    return exit_code

# Expose other elements if needed, e.g.:
# from .pts import PtsApi
