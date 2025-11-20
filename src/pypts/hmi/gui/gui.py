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
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager
from pypts.utilities.common import poll_queue

def gui_main(hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
    app = QApplication(sys.argv)
    gui = GUI(hmiToCoreInterface, core_to_hmi_queue)
    gui.show()
    sys.exit(app.exec())


class GUI(QWidget):
    def __init__(self, hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
        super().__init__()
        self.core = hmiToCoreInterface
        self.core_to_hmi_queue = core_to_hmi_queue
        self.heartbeat_manager = HeartbeatManager(self.core.send_heartbeat)

        self.setWindowTitle("PTS GUI")
        log.info("Starting module...")

        layout = QVBoxLayout()
        self.status_label = QLabel("Status: Idle")
        layout.addWidget(self.status_label)

        btn_stop = QPushButton("STOP CORE")
        btn_stop.clicked.connect(self.core.exit)
        layout.addWidget(btn_stop)

        self.setLayout(layout)
        self.timer = QTimer()
        log.info("Starting main event loop.")
        self.timer.timeout.connect(self.poll_core)
        self.timer.timeout.connect(self.do_periodic_tasks)
        self.timer.start(50)

    @catch_and_report_errors()
    def poll_core(self):
        poll_queue(self.core_to_hmi_queue, self.handle_core_event)

    @catch_and_report_errors()
    def handle_core_event(self, event: CoreToHMIEvent):
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToHMICommand.UPDATE_STATUS:
                self.update_status(event.payload.get("text", ""))
            case CoreToHMICommand.STOP:
                self.stop()
            case _:
                log.error(f"Unknown event: {event}")

    @catch_and_report_errors()
    def update_status(self, text: str):
        log.info(f"status update: {text}")
        self.status_label.setText(f"Status: {text}")

    @catch_and_report_errors()
    def do_periodic_tasks(self):
        """
        Executes any periodic status updates or maintenance tasks.
        """
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def stop(self):
        log.info("Stopping module")
        self.timer.stop()
        self.close()
        QTimer.singleShot(0, QApplication.quit)
        self.core.stop()

    @catch_and_report_errors()
    def _test_all_messages(self):
        self.core.start_sequence("SOME SEQUENCE")
        self.core.load_recipe("SOME RECIPE")
        self.core.stop()
