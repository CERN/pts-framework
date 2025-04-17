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
    
    Sets up the QApplication and MainWindow. Logging is configured.
    Recipe loading and execution will be handled later, triggered by user interaction.
    """
    app = QApplication(sys.argv)
    window = MainWindow()

    # Setup logging handler for the GUI
    logging.getLogger().addHandler(window.log_handler)

    # Recipe loading and execution logic has been removed from here.
    # It will be initiated by the MainWindow based on user actions.
    # This includes:
    # - Selecting the YAML file
    # - Calling run_pts()
    # - Creating RecipeEventProxy and its thread
    # - Connecting signals between the proxy and the window

    exit_code = app.exec()
    
    sys.exit(exit_code)
