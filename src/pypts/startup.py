# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
import logging
import atexit
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread
from pypts.pts import run_pts, PtsApi
from pypts.gui import MainWindow
from pypts.event_proxy import RecipeEventProxy
from pypts.recipe import Runtime

logger = logging.getLogger(__name__)


def create_and_start_gui(api: PtsApi, recipe_file: str | None = None):
    app = QApplication(sys.argv)
    window = MainWindow()
    window.q_in = api.input_queue
    if window.log_handler not in logging.getLogger().handlers:
        logging.getLogger().addHandler(window.log_handler)

    # --- Event proxy thread (created here so QApplication already exists) ---
    proxy = RecipeEventProxy(api.event_queue)
    recipe_thread = QThread(parent=app)
    proxy.moveToThread(recipe_thread)
    recipe_thread.started.connect(proxy.run)

    # Wire proxy signals to window slots
    proxy.pre_run_recipe_signal.connect(window.update_recipe_name)
    proxy.post_run_recipe_signal.connect(window.show_results)
    proxy.pre_run_sequence_signal.connect(window.update_sequence)
    proxy.post_run_step_signal.connect(window.update_step_result)
    proxy.pre_run_step_signal.connect(window.update_running_step)
    proxy.user_interact_signal.connect(window.show_message)
    proxy.get_serial_number_signal.connect(window.get_serial_number)
    proxy.post_load_recipe_signal.connect(window.handle_post_load_recipe)
    proxy.post_run_sequence_signal.connect(window.handle_post_run_sequence)

    # Callbacks invoked by command_handler_loop (daemon thread) on START/STOP.
    # QThread.start() and threading.Event methods are both thread-safe, so no
    # Qt signal bridge is needed here.
    def _on_start():
        Runtime.stop_event.clear()
        if not recipe_thread.isRunning():
            recipe_thread.start()

    def _on_stop():
        Runtime.stop_event.set()

    def _cleanup():
        proxy.stop()
        if recipe_thread.isRunning():
            recipe_thread.quit()
            recipe_thread.wait(5000)

    api.on_start = _on_start
    api.on_stop = _on_stop

    app.aboutToQuit.connect(_cleanup)
    atexit.register(_cleanup)

    # Start the event proxy thread immediately so it is ready before any
    # recipe events arrive. This also removes the need for a sleep.
    recipe_thread.start()

    if recipe_file:
        window.recipe_file = recipe_file
        try:
            window.load_recipe()
            window.q_in.put(("LOAD", window.recipe_file))
            window.action_start_recipe_execution.setEnabled(True)
        except Exception:
            logger.exception("Failed to load recipe at startup: %s", recipe_file)

    window.show()

    return window, app
