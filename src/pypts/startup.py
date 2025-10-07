# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
import logging
import atexit
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread
from pypts.pts import run_pts
from pypts.gui import MainWindow
from pypts.Thread_context import RuntimeContext

logger = logging.getLogger(__name__)

def create_and_start_gui(api):
    """
    todo
    """
    app = QApplication(sys.argv)
    window = MainWindow()
    window.q_in = api.input_queue
    logging.getLogger().addHandler(window.log_handler)

    RuntimeContext.set(window, api, app)

    time.sleep(1)  # Prevents a race condition. To be properly fixed!!
    # If we don't put the sleep, recipe_event_processing_thread.start() may not
    # be finished before the app.exec() call.

    return window, app

