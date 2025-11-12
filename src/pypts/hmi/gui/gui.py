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
    """Entry point called by launcher"""
    app = QApplication(sys.argv)
    gui = GUI(hmiToCoreInterface, core_to_hmi_queue)
    gui.show()
    sys.exit(app.exec())


class GUI(QWidget):
    def __init__(self, hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
        super().__init__()
        self.core = hmiToCoreInterface
        self.core_to_hmi_queue = core_to_hmi_queue

        self.setWindowTitle("PTS GUI")

        log.info("Starting module...")
        layout = QVBoxLayout()

        self.status_label = QLabel("Status: Idle")
        layout.addWidget(self.status_label)

        # --- Explicit buttons + connects ---
        # btn_start_A = QPushButton("Start Sequence A")
        # btn_start_A.clicked.connect(lambda: self.hmiToCoreInterface.start_sequence("A"))
        # layout.addWidget(btn_start_A)
        #
        # btn_start_B = QPushButton("Start Sequence B")
        # btn_start_B.clicked.connect(lambda: self.hmiToCoreInterface.start_sequence("B"))
        # layout.addWidget(btn_start_B)
        #
        # btn_recipe_X = QPushButton("Load Recipe X")
        # btn_recipe_X.clicked.connect(lambda: self.hmiToCoreInterface.load_recipe("/tmp/recipe_x.yml"))
        # layout.addWidget(btn_recipe_X)
        #
        # btn_recipe_Y = QPushButton("Load Recipe Y")
        # btn_recipe_Y.clicked.connect(lambda: self.hmiToCoreInterface.load_recipe("/tmp/recipe_y.yml"))
        # layout.addWidget(btn_recipe_Y)

        btn_stop = QPushButton("STOP CORE")
        btn_stop.clicked.connect(self.core.exit)
        layout.addWidget(btn_stop)
        self.setLayout(layout)

        self.timer = QTimer()
        log.info("Starting main event loop.")
        self.timer.timeout.connect(self.poll_core)
        self.timer.start(50)  # ms

    def poll_core(self):
        try:
            event: CoreToHMIEvent = self.core_to_hmi_queue.get(timeout=0)
            self.handle_command(event)
        except Empty:
            pass

    def handle_command(self, event: CoreToHMIEvent):
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToHMICommand.UPDATE_STATUS:
                self.update_status(event.payload.get("text", ""))
            case CoreToHMICommand.STOP:
                self.stop()
            case _:
                log.error(f"Unknown event: {event}")

    def update_status(self, text: str):
        log.info(f"status update: {text}")

    def do_periodic_tasks(self):
        """Example GUI behavior: periodically request something"""
        # Example: Keep telling Core to start same sequence

    def stop(self):
        log.info("Stopping module")
        self.timer.stop()
        self.close()
        # executed at the next timer tick
        QTimer.singleShot(0, QApplication.quit)
        self.core.stop()

    def _test_all_messages(self):
        self.core.start_sequence("SOME SEQUENCE")
        self.core.load_recipe("SOME RECIPE")
        self.core.stop()