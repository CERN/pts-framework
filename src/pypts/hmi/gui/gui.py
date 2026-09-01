# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The PySide6 frontend: the operator screen.

Layout:

  QMenuBar  File / Edit / View / About
  QToolBar  Open | Start | Pause | Stop  ··· "pypts"
  recipe_label
  ┌────────────────────────┬──────────────────────────────┐
  │ left_stack (52%)       │ CenterContent (48%)          │
  │  page 0: idle logo     │  InteractionPanel            │
  │  page 1: StepTable     │  LogPanel                    │
  │  page 2: ResultsPanel  │                              │
  └────────────────────────┴──────────────────────────────┘
  QStatusBar  status label  ···  Open report folder button

HmiClient owns the protocol; GUI is the assembler (gui.md §6).
"""

import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.center_view import CenterContent
from pypts.hmi.gui.gui_theme import install_system_theme_sync
from pypts.hmi.gui.resources import load_cern_logo_pixmap
from pypts.hmi.gui.results_panel import ResultsPanel
from pypts.hmi.gui.step_table import StepTableContent
from pypts.hmi.gui.styles import get_stylesheet
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

POLL_INTERVAL_MS = 50

_PAGE_LEFT_IDLE = 0
_PAGE_LEFT_TABLE = 1
_PAGE_LEFT_RESULTS = 2


def gui_main(
    to_core: QueueWrapper[HmiToCore],
    from_core: QueueWrapper[CoreToHmi],
    log_queue,
    log_level: int = DEFAULT_LOG_LEVEL,
) -> None:
    """Entry point for the GUI process."""
    init_logging(log_queue, log_level)
    app = QApplication(sys.argv)
    gui = GUI(to_core, from_core)
    gui.show()
    sys.exit(app.exec())


class PtsMainWindow(QMainWindow):
    """
    The application main window.

    Builds the menu bar, native toolbar, body splitter
    (left stack 52% / right interaction 48%), and status bar.
    Content widgets are injected; the window owns layout, not logic.
    [X] is intercepted: it issues a shutdown request and only really closes
    when CORE sends StopHmi.
    """

    def __init__(
        self,
        on_close_request,
        top_bar: TopBarContent,
        step_table: StepTableContent,
        results_panel: ResultsPanel,
        center: CenterContent,
    ) -> None:
        super().__init__()
        self._on_close_request = on_close_request
        self.allow_close = False

        self.results_panel = results_panel
        self.top_bar = top_bar

        self.setWindowTitle("PTS")
        self.resize(1600, 1000)
        self.setMinimumSize(1000, 700)

        # Native toolbar
        self.addToolBar(top_bar)

        # Menu bar
        self._build_menu()

        # ── Central widget ────────────────────────────────────────────────────
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Body: recipe label + horizontal splitter
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 10)
        body_layout.setSpacing(8)

        self.recipe_label = QLabel("No recipe loaded")
        self.recipe_label.setObjectName("recipeLabel")
        body_layout.addWidget(self.recipe_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left stack: idle placeholder → step table → results panel
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self._build_idle_placeholder())  # page 0
        self.left_stack.addWidget(step_table)                       # page 1
        self.left_stack.addWidget(results_panel)                    # page 2

        splitter.addWidget(self.left_stack)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 52)
        splitter.setStretchFactor(1, 48)

        body_layout.addWidget(splitter, stretch=1)
        central_layout.addWidget(body, stretch=1)
        self.setCentralWidget(central)

    # --- Menu ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        open_action = file_menu.addAction("Open Recipe")
        open_action.triggered.connect(self.top_bar.choose_recipe_file)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self._on_close_request)

        edit_menu = menu_bar.addMenu("Edit")
        edit_menu.addAction("Edit Recipe")

        view_menu = menu_bar.addMenu("View")
        self.dark_mode_action = view_menu.addAction("Toggle Dark Mode")

        about_menu = menu_bar.addMenu("About")
        about_menu.addAction("GitLab")
        about_menu.addAction("Wiki")

    # --- Idle placeholder ------------------------------------------------------

    def _build_idle_placeholder(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = load_cern_logo_pixmap()
        if pixmap is not None and not pixmap.isNull():
            logo_label.setPixmap(
                pixmap.scaled(
                    180, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Open a YAML recipe to begin")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("font-size:12px; color:#94a3b8;")
        layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        return page

    # --- Close intercept -------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual
        if self.allow_close:
            super().closeEvent(event)
            return
        event.ignore()
        self._on_close_request()


class GUI(HmiClient):
    """
    The assembler: main window + four content widgets + hook wiring.

    Overrides only presentation hooks - the protocol itself (routing, stop,
    shutdown, the answer_* methods) stays inherited.
    """

    def __init__(
        self, to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]
    ) -> None:
        super().__init__(to_core, from_core)
        log.info("Starting module.")

        self.current_recipe: RecipeLoaded | None = None
        self._run_outcomes: list[StepOutcome] = []
        self._paused = False

        # Build content widgets
        self.top_bar = TopBarContent(
            on_open=self.load_recipe,
            on_start=self.start_sequence,
            on_stop=self.stop_sequence,
            on_pause=self._toggle_pause,
            on_sequence_selected=self.show_selected_sequence,
        )
        self.step_table = StepTableContent()
        _results = ResultsPanel()
        self.center = CenterContent()
        self.center.results = _results  # inject reference for update_results

        self.window = PtsMainWindow(
            self.request_shutdown,
            self.top_bar,
            self.step_table,
            _results,
            self.center,
        )

        # Status bar
        self.status_label = QLabel("Status: Idle")
        self.window.statusBar().addWidget(self.status_label, 1)

        self.report_dir: str | None = None
        self.open_report_button = QPushButton("Open report folder")
        self.open_report_button.setEnabled(False)
        self.open_report_button.clicked.connect(self.open_report_folder)
        self.window.statusBar().addPermanentWidget(self.open_report_button)

        # Theme — start in light mode; OS live-sync can still switch to dark
        app = QApplication.instance()
        self._dark = False
        self._apply_theme(False)
        self._theme_disconnect = install_system_theme_sync(app, self._on_system_theme_changed)
        self.window.dark_mode_action.triggered.connect(self._toggle_dark_mode)

        log.info("Starting main event loop.")
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_core)
        self.timer.timeout.connect(self.do_periodic_tasks)
        self.timer.start(POLL_INTERVAL_MS)

    def show(self) -> None:
        self.window.show()

    # --- Theme ------------------------------------------------------------------

    def _toggle_dark_mode(self) -> None:
        self._dark = not self._dark
        self._apply_theme(self._dark)

    def _on_system_theme_changed(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme(dark)

    def _apply_theme(self, dark: bool) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(dark))
        self.top_bar.set_dark(dark)
        self.center.set_dark(dark)
        self.window.results_panel.set_dark(dark)

    # --- Pause / browse mode ----------------------------------------------------

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.center.set_auto_switch(not self._paused)

    # --- Sequence dropdown ------------------------------------------------------

    def show_selected_sequence(self, sequence_name: str) -> None:
        if self.current_recipe is None:
            return
        for sequence in self.current_recipe.sequences:
            if sequence.sequence_name == sequence_name:
                self.step_table.show_sequence(sequence)
                self.window.left_stack.setCurrentIndex(_PAGE_LEFT_TABLE)
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
        self.window.recipe_label.setText(
            f"Loaded {event.recipe_name}\nReady to start"
        )

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        self._run_outcomes = []
        self._paused = False
        self.center.set_auto_switch(True)
        self.top_bar.show_run_started()
        self.step_table.reset_to_pending()
        self.center.show_idle()
        self.window.left_stack.setCurrentIndex(_PAGE_LEFT_TABLE)
        self.window.recipe_label.setText(f"Running {recipe_name}...")

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        self._paused = False
        self.center.set_auto_switch(True)
        self.top_bar.show_run_finished()
        self.center.cancel_pending()
        self.center.show_idle()
        self.window.results_panel.set_results(outcomes)

    def show_sequence_started(self, sequence_name: str) -> None:
        log.info("sequence started: %s", sequence_name)

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        log.info("sequence finished: %s %s", sequence_name, result)

    def show_step_started(self, event: StepStarted) -> None:
        self.step_table.mark_running(event)

    def show_step_finished(self, outcome: StepOutcome) -> None:
        self.step_table.show_outcome(outcome)
        self._run_outcomes.append(outcome)
        self.center.update_results(tuple(self._run_outcomes))

    def show_report_ready(self, event: ReportReady) -> None:
        self.report_dir = event.report_dir
        self.open_report_button.setEnabled(True)

    def open_report_folder(self) -> None:
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
        self._theme_disconnect()
        self.timer.stop()
        self.window.allow_close = True
        self.window.close()
        QTimer.singleShot(0, QApplication.quit)
