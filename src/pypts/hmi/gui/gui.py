# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
)
from PySide6.QtCore import QTimer
from queue import Empty
import sys
from pypts.core.HMI_to_core_interface import HMIToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToHMIEvent, CoreToHMICommand
from pypts.logger.log import log


def gui_main(hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
    """
    Entry point for launching the GUI module.
    Instantiates QApplication and GUI window,
    shows the GUI and starts event loop until termination.
    """
    app = QApplication(sys.argv)
    gui = GUI(hmiToCoreInterface, core_to_hmi_queue)
    gui.show()
    sys.exit(app.exec())


class GUI(QWidget):
    """
    Main GUI window representing the Human Machine Interface.

    Attributes:
      - core: Communication interface for sending commands to Core.
      - core_to_hmi_queue: Incoming message queue from Core.
      - status_label: Displays current status in the GUI.
      - timer: Polling mechanism for asynchronous Core event handling.
    """

    def __init__(self, hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
        super().__init__()
        self.core = hmiToCoreInterface
        self.core_to_hmi_queue = core_to_hmi_queue

        self.setWindowTitle("PTS GUI")

        log.info("Starting module...")

        # Main window layout setup
        layout = QVBoxLayout()

        # Status display label
        self.status_label = QLabel("Status: Idle")
        layout.addWidget(self.status_label)

        # --- Example buttons to trigger actions on Core (currently commented out) ---
        # Each would send a command to Core to start/stop sequences or load recipes
        # via the HMIToCoreInterface when uncommented.

        btn_stop = QPushButton("STOP CORE")
        btn_stop.clicked.connect(self.core.exit)  # Button to terminate core process
        layout.addWidget(btn_stop)

        self.setLayout(layout)

        # Timer to periodically poll for incoming Core events
        self.timer = QTimer()
        log.info("Starting main event loop.")
        self.timer.timeout.connect(self.poll_core)
        self.timer.start(50)  # milliseconds interval for polling

    def poll_core(self):
        """
        Polls the core_to_hmi_queue for new events from Core.
        Processes each event using the handle_command method.
        Runs every timer tick; non-blocking queue poll.
        """
        try:
            event: CoreToHMIEvent = self.core_to_hmi_queue.get(timeout=0)
            self.handle_command(event)
        except Empty:
            # No events received from Core, continue waiting
            pass

    def handle_command(self, event: CoreToHMIEvent):
        """
        Handles incoming CoreToHMIEvent messages.
        Routes recognized commands to update GUI status or stop the module.
        Logs unknown events for debugging.
        """
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToHMICommand.UPDATE_STATUS:
                self.update_status(event.payload.get("text", ""))
            case CoreToHMICommand.STOP:
                self.stop()
            case _:
                log.error(f"Unknown event: {event}")

    def update_status(self, text: str):
        """
        Updates the GUI status label with provided text.
        Intended for visual feedback of system state.
        """
        log.info(f"status update: {text}")
        self.status_label.setText(f"Status: {text}")

    def do_periodic_tasks(self):
        """
        Placeholder for periodic GUI-driven operations.
        For example: automatically triggering core actions or status requests.
        """
        # Example: you may request Core to re-initiate sequences here if desired
        pass

    def stop(self):
        """
        Stops the GUI application.
        Stops the poll timer, closes the window, requests application quit,
        and signals core shutdown through the interface.
        """
        log.info("Stopping module")
        self.timer.stop()
        self.close()
        QTimer.singleShot(0, QApplication.quit)
        self.core.stop()

    def _test_all_messages(self):
        """
        Internal testing method for sending sample commands to Core.
        Useful for manual protocol or connection testing during development.
        """
        self.core.start_sequence("SOME SEQUENCE")
        self.core.load_recipe("SOME RECIPE")
        self.core.stop()
