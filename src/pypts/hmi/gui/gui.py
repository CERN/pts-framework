# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The PySide6 frontend.

Everything about the protocol is in HmiClient; this module is the presentation
half. It is still the minimal status window - the widget system, recipe preview
and results table are roadmap Phase 3.
"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from pypts.hmi.hmi_client import HmiClient
from pypts.logger.log import DEFAULT_LOG_LEVEL, init_logging, log
from pypts.messages import QueueWrapper
from pypts.messages.common_messages import ModuleError, ResultType, StepOutcome
from pypts.messages.core_hmi_communication import CoreToHmi, HmiToCore

#: Milliseconds between polls of the CORE inbox.
POLL_INTERVAL_MS = 50


def gui_main(
    to_core: QueueWrapper[HmiToCore],
    from_core: QueueWrapper[CoreToHmi],
    log_queue,
    log_level: int = DEFAULT_LOG_LEVEL,
) -> None:
    """
    Entry point. Runs in the GUI process, so log records have to be routed to
    the Logger before anything is logged.
    """
    init_logging(log_queue, log_level)
    app = QApplication(sys.argv)
    gui = GUI(to_core, from_core)
    gui.show()
    sys.exit(app.exec())


class GUI(HmiClient):
    """
    The status window.

    The window is *held* rather than inherited from. A `class GUI(QWidget,
    HmiClient)` mixin looks tidier but does not work: PySide6's QWidget.__init__
    cooperatively calls the next __init__ in the MRO, so HmiClient.__init__
    would be invoked with no arguments. Holding the widget sidesteps that and
    keeps protocol and presentation in separate objects anyway.
    """

    def __init__(
        self, to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]
    ) -> None:
        super().__init__(to_core, from_core)
        log.info("Starting module.")

        self.window = QWidget()
        self.window.setWindowTitle("PTS GUI")

        self.status_label = QLabel("Status: Idle")
        stop_button = QPushButton("STOP CORE")
        # Asks CORE to bring the application down in order. CORE answers StopHmi,
        # which HmiClient turns into stop() and then on_stop() below.
        stop_button.clicked.connect(self.request_shutdown)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(stop_button)
        self.window.setLayout(layout)

        # Qt's event loop drives the polling, so the GUI needs no thread of its own.
        log.info("Starting main event loop.")
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_core)
        self.timer.timeout.connect(self.do_periodic_tasks)
        self.timer.start(POLL_INTERVAL_MS)

    def show(self) -> None:
        self.window.show()

    # --- Presentation ---------------------------------------------------------

    def show_status(self, text: str) -> None:
        log.info("status update: %s", text)
        self.status_label.setText(f"Status: {text}")

    def show_error(self, error: ModuleError) -> None:
        log.error("%s: %s", error.source, error.message)
        self.status_label.setText(f"Error: {error.message}")

    def show_recipe_loaded(self, recipe_name: str, recipe_version: str) -> None:
        self.status_label.setText(f"Loaded {recipe_name} ({recipe_version})")

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        self.status_label.setText(f"{sequence_name}: {result}")

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        self.status_label.setText(f"Finished: {result} ({len(outcomes)} steps)")

    def on_stop(self) -> None:
        """Tear the window down. Called from stop(), once CORE has sent StopHmi."""
        self.timer.stop()
        self.window.close()
        QTimer.singleShot(0, QApplication.quit)
