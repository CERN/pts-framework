# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The PySide6 frontend: the four-panel operator screen.

Everything about the protocol is in HmiClient; this module is the assembler
(gui.md section 6): it builds the scaffold window, one content widget per
panel, wires the contents' callbacks to the inherited protocol commands, and
turns the show_*/ask_* hooks into content updates. The contents themselves are
pure views in their own modules - top_bar, step_table, center_view - and know
nothing about messages' origins.

The GUI *holds* its widgets rather than inheriting from one. That is not a
style choice: PySide6's QWidget.__init__ cooperatively calls the next __init__
in the MRO, so `class GUI(QWidget, HmiClient)` would call HmiClient.__init__
with no arguments and fail at construction. Holding also keeps protocol and
presentation in separate objects.
"""

import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from pypts.hmi.gui.center_view import CenterContent
from pypts.hmi.gui.scaffold.main_window import MainWindow
from pypts.hmi.gui.scaffold.style_config import LayoutConfig
from pypts.hmi.gui.step_table import StepTableContent
from pypts.hmi.gui.top_bar import TopBarContent
from pypts.hmi.hmi_client import HmiClient
from pypts.logger.log import DEFAULT_LOG_LEVEL, init_logging, log
from pypts.messages import QueueWrapper
from pypts.messages.common_messages import ModuleError, ResultType, StepOutcome
from pypts.messages.core_hmi_communication import CoreToHmi, HmiToCore, ReportReady
from pypts.messages.run_events import (
    RecipeLoaded,
    SerialNumberRequest,
    StepStarted,
    UserPromptRequest,
)

#: Milliseconds between polls of the CORE inbox.
POLL_INTERVAL_MS = 50


def force_light_mode(app: QApplication) -> None:
    """
    Pin the application to the light color scheme, whatever the OS theme is.

    The GUI is designed light: the verdict colors are pale backgrounds with
    dark text (result_colors.py), and under Windows dark mode Qt would put
    them on dark panels. Deliberately no dark mode at all for now - a dark
    palette is a design task for the Phase 3 widget work, not a toggle.
    """
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)


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
    force_light_mode(app)
    gui = GUI(to_core, from_core)
    gui.show()
    sys.exit(app.exec())


class PtsMainWindow(MainWindow):
    """
    The scaffold window plus the one behaviour an app window needs: [X] asks.

    Closing the window must not orphan the engine, so the first close is
    turned into a shutdown *request*; CORE brings everything down in order and
    answers StopHmi, and only then (`allow_close`, set by GUI.on_stop) does a
    close actually close.
    """

    def __init__(self, on_close_request, **kwargs) -> None:
        super().__init__(**kwargs)
        self._on_close_request = on_close_request
        self.allow_close = False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual
        if self.allow_close:
            super().closeEvent(event)
            return
        event.ignore()
        self._on_close_request()


class GUI(HmiClient):
    """
    The assembler: scaffold window + four panel contents + the hook wiring.

    Overrides only presentation hooks - the protocol itself (routing, stop,
    shutdown, the answer_* methods) stays inherited, and test_messages.py
    asserts that it does.
    """

    def __init__(
        self, to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]
    ) -> None:
        super().__init__(to_core, from_core)
        log.info("Starting module.")

        #: The last RecipeLoaded, so the dropdown can re-fill the table locally.
        self.current_recipe: RecipeLoaded | None = None

        self.window = PtsMainWindow(
            self.request_shutdown,
            title="PTS",
            width=1600,
            height=1000,
            layout=LayoutConfig(
                top_bar_stretch=1,
                middle_row_stretch=12,
                left_sidebar_stretch=2,
                right_column_stretch=3,
            ),
        )

        self.top_bar = TopBarContent(
            on_open=self.load_recipe,
            on_start=self.start_sequence,
            on_stop=self.stop_sequence,
            on_sequence_selected=self.show_selected_sequence,
        )
        self.step_table = StepTableContent()
        self.center = CenterContent()
        self.status_label = QLabel("Status: Idle")

        #: The folder of the newest report, or None before the first one.
        self.report_dir: str | None = None
        self.open_report_button = QPushButton("Open report folder")
        # Dead until a ReportReady names a folder to open.
        self.open_report_button.setEnabled(False)
        self.open_report_button.clicked.connect(self.open_report_folder)

        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(8, 2, 8, 2)
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.open_report_button)

        self.window.top_bar.set_content(self.top_bar)
        self.window.left_sidebar.set_content(self.step_table)
        self.window.center_view.set_content(self.center)
        self.window.bottom_bar.set_content(bottom)

        # Qt's event loop drives the polling, so the GUI needs no thread of its own.
        log.info("Starting main event loop.")
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_core)
        self.timer.timeout.connect(self.do_periodic_tasks)
        self.timer.start(POLL_INTERVAL_MS)

    def show(self) -> None:
        self.window.show()

    def show_selected_sequence(self, sequence_name: str) -> None:
        """The dropdown changed: show that sequence's rows, from local data."""
        if self.current_recipe is None:
            return
        for sequence in self.current_recipe.sequences:
            if sequence.sequence_name == sequence_name:
                self.step_table.show_sequence(sequence)
                return

    # --- Presentation hooks -----------------------------------------------------

    def show_status(self, text: str) -> None:
        log.info("status update: %s", text)
        self.status_label.setText(f"Status: {text}")

    def show_error(self, error: ModuleError) -> None:
        log.error("%s: %s", error.source, error.message)
        self.status_label.setText(f"Error: {error.message}")

    def show_recipe_loaded(self, event: RecipeLoaded) -> None:
        self.current_recipe = event
        self.top_bar.show_recipe_loaded(event)
        self.show_selected_sequence(event.main_sequence)
        self.status_label.setText(f"Loaded {event.recipe_name} ({event.recipe_version})")

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        self.top_bar.show_run_started()
        self.step_table.reset_to_pending()
        self.status_label.setText(f"Status: Running {recipe_name}")

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        self.top_bar.show_run_finished()
        # A prompt outliving its run would strand the answer; decline it.
        self.center.cancel_pending()
        self.status_label.setText(f"Finished: {result} ({len(outcomes)} steps)")

    def show_sequence_started(self, sequence_name: str) -> None:
        self.status_label.setText(f"Status: Sequence {sequence_name}")

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        self.status_label.setText(f"{sequence_name}: {result}")

    def show_step_started(self, event: StepStarted) -> None:
        self.step_table.mark_running(event)

    def show_step_finished(self, outcome: StepOutcome) -> None:
        self.step_table.show_outcome(outcome)

    def show_report_ready(self, event: ReportReady) -> None:
        self.report_dir = event.report_dir
        self.open_report_button.setEnabled(True)
        self.status_label.setText(f"Report ready: {event.report_path}")

    def open_report_folder(self) -> None:
        """Open the newest report's folder in the platform's file browser."""
        if self.report_dir is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.report_dir))

    def ask_user(self, request: UserPromptRequest) -> None:
        self.center.show_prompt(
            request, lambda choice: self.answer_user_prompt(request, choice)
        )

    def ask_serial_number(self, request: SerialNumberRequest) -> None:
        self.center.show_serial_request(
            request, lambda serial: self.answer_serial_number(request, serial)
        )

    def on_stop(self) -> None:
        """Tear the window down. Called from stop(), once CORE has sent StopHmi."""
        self.timer.stop()
        self.window.allow_close = True
        self.window.close()
        QTimer.singleShot(0, QApplication.quit)
