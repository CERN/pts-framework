# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The PySide6 frontend: the operator screen.

Layout:

  QMenuBar  File / Edit / View / About
  QToolBar  Open | Start | Pause | Stop  ··· Open report folder
  recipe_label
  ┌────────────────────────┬──────────────────────────────┐
  │ left_stack (52%)       │ CenterContent (48%)          │
  │  page 0: idle logo     │  InteractionPanel            │
  │  page 1: StepTable     │  LogPanel                    │
  │  page 2: ResultsPanel  │                              │
  └────────────────────────┴──────────────────────────────┘
  QStatusBar  status label

HmiClient owns the protocol; GUI is the assembler (gui.md §6).
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pypts.config_handler import ConfigHandler
from pypts.hmi.gui.center_view import CenterContent
from pypts.hmi.gui.gui_theme import install_system_theme_sync
from pypts.hmi.gui.log_tail import LogTail
from pypts.hmi.gui.palette import LIGHT, get_palette
from pypts.hmi.gui.remove_cache_dialog import show_remove_cache_dialog
from pypts.hmi.gui.resources import load_cern_logo_pixmap
from pypts.hmi.gui.results_panel import ResultsPanel
from pypts.hmi.gui.step_table import StepTableContent
from pypts.hmi.gui.styles import get_stylesheet
from pypts.hmi.gui.top_bar import TopBarContent
from pypts.hmi.hmi_client import HmiClient
from pypts.logger.log import DEFAULT_LOG_LEVEL, get_log_path, init_logging, log
from pypts.messages import QueueWrapper
from pypts.messages.common_messages import (
    ErrorSeverity,
    ModuleError,
    ResultType,
    StepOutcome,
)
from pypts.messages.core_hmi_communication import CoreToHmi, HmiToCore, ReportReady
from pypts.messages.run_events import (
    RecipeLoaded,
    StepStarted,
    UserPromptRequest,
    UserTextRequest,
)
from pypts.recipe import step_source
from pypts.utilities.data_removal import survey
from pypts.utilities.error_handling import (
    catch_and_report_errors,
    report_error,
    report_problem,
)
from pypts.utilities.recent_recipes import RecentRecipes

POLL_INTERVAL_MS = 50

#: How often the LOG OUTPUT panel picks up what the Logger has written since.
#: Slower than the message poll on purpose: this one touches a file, and the
#: operator reads the panel rather than watching it.
LOG_POLL_INTERVAL_MS = 200

_PAGE_LEFT_IDLE = 0
_PAGE_LEFT_TABLE = 1
_PAGE_LEFT_RESULTS = 2

#: Where the About menu sends the operator. The project moved off CERN GitLab;
#: `pyproject.toml`'s `[project.urls]` still names the old repository.
_REPOSITORY_URL = "https://github.com/CERN/pts-framework"
_DOCUMENTATION_URL = "https://cern.github.io/pts-framework/"


def open_external_url(url: str) -> None:
    """
    Hand a URL to the operator's browser, and never take the window with it.

    `openUrl` returns False rather than raising when there is no browser to
    hand it to - a bench machine with no default set, or none installed at all.
    That is worth a line in the log and nothing more: the About menu is not
    part of running a recipe.
    """
    if not QDesktopServices.openUrl(QUrl(url)):
        log.warning("Could not open %s - no handler for it on this machine.", url)


def gui_main(
    to_core: QueueWrapper[HmiToCore],
    from_core: QueueWrapper[CoreToHmi],
    log_queue,
    log_level: int = DEFAULT_LOG_LEVEL,
    log_file_path: str | None = None,
) -> None:
    """
    Entry point for the GUI process.

    Args:
        log_file_path: this run's log, handed on from the launcher. The GUI tails
            it into the LOG OUTPUT panel; without it the panel stays empty and
            the rest of the window is unaffected.
    """
    init_logging(log_queue, log_level, log_file_path)
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

        self.setWindowTitle("pyPTS")
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

        # Filled by the assembler on aboutToShow - the window owns the widget,
        # the GUI owns the list. setToolTipsVisible, or the full paths the
        # entries carry would never be shown.
        self.recent_menu = file_menu.addMenu("Open Recent")
        self.recent_menu.setToolTipsVisible(True)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self._on_close_request)

        edit_menu = menu_bar.addMenu("Edit")
        edit_menu.setToolTipsVisible(True)  # or the disabled reason is invisible
        edit_menu.addAction("Edit Recipe")
        edit_menu.addSeparator()
        self.remove_cache_action = edit_menu.addAction("Remove Cache")

        view_menu = menu_bar.addMenu("View")
        self.dark_mode_action = view_menu.addAction("Toggle Dark Mode")

        about_menu = menu_bar.addMenu("About")
        about_menu.setToolTipsVisible(True)
        self.repository_action = about_menu.addAction("GitHub")
        self.repository_action.setToolTip(_REPOSITORY_URL)
        self.repository_action.triggered.connect(
            lambda: open_external_url(_REPOSITORY_URL)
        )
        self.documentation_action = about_menu.addAction("Wiki")
        self.documentation_action.setToolTip(_DOCUMENTATION_URL)
        self.documentation_action.triggered.connect(
            lambda: open_external_url(_DOCUMENTATION_URL)
        )

    # --- Idle placeholder ------------------------------------------------------

    def _build_idle_placeholder(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()

        self.idle_logo_label = QLabel()
        self.idle_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.paint_idle_logo(dark=False)
        layout.addWidget(self.idle_logo_label, alignment=Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Open a YAML recipe to begin")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"font-size:12px; color:{LIGHT.section_label};")
        layout.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        return page

    def paint_idle_logo(self, dark: bool) -> None:
        """
        Draw the idle placeholder's CERN logo for the given theme.

        Artwork, not a stylesheet colour: the dark theme tints it, because the
        file is a navy line drawing and navy on charcoal is a smudge.
        """
        pixmap = load_cern_logo_pixmap(get_palette(dark).logo_tint)
        if pixmap is None or pixmap.isNull():
            return
        self.idle_logo_label.setPixmap(
            pixmap.scaled(
                180, 120,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

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
        self.recent_recipes = RecentRecipes()
        self._requested_recipe_path: str | None = None

        #: Sequence name -> one rendered YAML fragment per step table row, read
        #: back off disk once per load for the step table's hover panel.
        self._recipe_yaml: dict[str, tuple[str, ...]] = {}

        self.top_bar = TopBarContent(
            on_open=self.open_recipe,
            on_start=self.start_sequence,
            on_stop=self.stop_sequence,
            on_pause=self._toggle_pause,
            on_sequence_selected=self.show_selected_sequence,
            on_open_report=self.open_report_folder,
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
        self.status_label.setObjectName("statusLabel")
        self.window.statusBar().addWidget(self.status_label, 1)

        self.report_dir: str | None = None

        # Theme — start in light mode; OS live-sync can still switch to dark
        app = QApplication.instance()
        self._dark = False
        self._apply_theme(False)
        self._theme_disconnect = install_system_theme_sync(app, self._on_system_theme_changed)
        self.window.dark_mode_action.triggered.connect(self._toggle_dark_mode)
        self.window.remove_cache_action.triggered.connect(self._remove_cache)
        self._set_remove_cache_enabled(True)

        # Rebuilt every time it opens rather than kept in step with the store,
        # so it can never show a stale list.
        self.window.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)

        # The LOG OUTPUT panel, on its own slower timer.
        self.log_tail: LogTail | None = None
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.poll_log)
        self.start_log_tail()

        log.info("Starting main event loop.")
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_core)
        self.timer.timeout.connect(self.do_periodic_tasks)
        self.timer.start(POLL_INTERVAL_MS)

    def show(self) -> None:
        self.window.show()

    # --- Log panel --------------------------------------------------------------

    def start_log_tail(self) -> None:
        """
        Point the LOG OUTPUT panel at this run's log and start following it.

        The path comes from the Logger module, which was told it by the launcher.
        A GUI built without one - a test, or a frontend started by hand - simply
        has no log to show, and says so in the panel instead of failing.
        """
        log_path = get_log_path()
        if log_path is None:
            log.debug("No run log path was given; the log panel stays empty.")
            self.center.log_panel.append_line("No run log to follow.")
            return

        tail = LogTail(log_path)
        try:
            tail.open()
        except OSError as exc:
            # Recognised and survivable: the run is fine, the panel is not.
            report_error(
                self,
                exc,
                severity=ErrorSeverity.WARNING,
                operation="GUI.start_log_tail",
            )
            self.center.log_panel.append_line(f"Could not open the run log: {log_path}")
            return

        log.debug("Log panel is following the run log: %s", log_path)
        self.log_tail = tail
        self.log_timer.start(LOG_POLL_INTERVAL_MS)

    @catch_and_report_errors()
    def poll_log(self) -> None:
        """
        Append whatever the Logger has written since the last tick.

        Timer housekeeping, so it is decorated to report and continue: a failed
        read must cost the operator the panel, never the window. A read that
        fails once will fail every 200 ms, so the follower is dropped rather than
        left to report the same failure forever.
        """
        if self.log_tail is None:
            return

        try:
            new_lines = self.log_tail.new_lines()
        except OSError:
            self.stop_log_tail()
            raise

        for line in new_lines:
            self.center.log_panel.append_line(line)

    def stop_log_tail(self) -> None:
        """Stop following the log and release the file. Safe to call twice."""
        self.log_timer.stop()
        if self.log_tail is not None:
            self.log_tail.close()
            self.log_tail = None

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
        # These two colour themselves per item, which no stylesheet can reach.
        self.step_table.set_dark(dark)
        self.window.paint_idle_logo(dark)

    # --- Pause / browse mode ----------------------------------------------------

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.center.set_auto_switch(not self._paused)
        # The button resumes now, so it must stop describing itself as Pause.
        self.top_bar.set_paused(self._paused)

    # --- Sequence dropdown ------------------------------------------------------

    def show_selected_sequence(self, sequence_name: str) -> None:
        if self.current_recipe is None:
            return
        for sequence in self.current_recipe.sequences:
            if sequence.sequence_name == sequence_name:
                self.step_table.show_sequence(
                    sequence, self._recipe_yaml.get(sequence_name, ())
                )
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
        self._recipe_yaml = {}
        if self._requested_recipe_path is not None:
            # Only now, with CORE's confirmation that the file parsed: a path
            # that does not load is not one to offer again.
            self.recent_recipes.remember(self._requested_recipe_path, event.recipe_name)
            self._recipe_yaml = step_source.step_yaml_by_sequence(
                self._requested_recipe_path
            )
            self._requested_recipe_path = None
        self.step_table.set_running(False)
        self.top_bar.show_recipe_loaded(event)
        self.show_selected_sequence(event.main_sequence)
        self.window.recipe_label.setText(
            f"Loaded {event.recipe_name}\nReady to start"
        )

    def show_run_metadata(self, values: tuple[tuple[str, str], ...]) -> None:
        super().show_run_metadata(values)
        self.top_bar.show_run_metadata(values)

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        self._set_remove_cache_enabled(False)
        self._run_outcomes = []
        self._paused = False
        self.center.set_auto_switch(True)
        self.top_bar.show_run_started()
        self.step_table.set_running(True)
        self.step_table.reset_to_pending()
        self.center.show_idle()
        self.window.left_stack.setCurrentIndex(_PAGE_LEFT_TABLE)
        self.window.recipe_label.setText(f"Running {recipe_name}...")

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        self._set_remove_cache_enabled(True)
        self._paused = False
        self.center.set_auto_switch(True)
        self.step_table.set_running(False)
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

    # --- Remove Cache -----------------------------------------------------------

    def _set_remove_cache_enabled(self, enabled: bool) -> None:
        """
        Only between runs. Deleting the reports directory while the Report
        thread is writing into it would take the run down, so the item greys
        out for the duration and says why on hover.
        """
        action = self.window.remove_cache_action
        action.setEnabled(enabled)
        if enabled:
            action.setToolTip("Delete the stored configuration, reports, logs and recents.")
        else:
            action.setToolTip("Not while a recipe is running - stop the run first.")

    @catch_and_report_errors()
    def _remove_cache(self) -> None:
        """
        Show what would go, and remove it if the operator says so.

        The survey is taken fresh every time the dialog opens, so the sizes are
        the sizes now. Decorated to report and continue: a cleanup that fails
        must not take the window down.
        """
        outcome = show_remove_cache_dialog(survey(), parent=self.window)
        if outcome is None:
            log.info("Remove Cache: cancelled by the operator.")
            return

        # The store still holds the list it read at start-up and would write it
        # straight back on the next load. Rebuild it from the now-absent file.
        self.recent_recipes = RecentRecipes()
        self.show_status("Cache removed")

    # --- Opening a recipe, and the recipes opened before ------------------------

    def open_recipe(self, recipe_path: str) -> None:
        """
        The one funnel every open goes through - the toolbar button, File ->
        Open Recipe, and File -> Open Recent all land here.

        It stashes the path because `RecipeLoaded` does not carry one: the HMI
        is the only side that knows which file it asked for, and the recents
        list needs the two halves together.
        """
        self._requested_recipe_path = recipe_path
        self.load_recipe(recipe_path)

    @catch_and_report_errors()
    def _rebuild_recent_menu(self) -> None:
        """
        Fill File -> Open Recent from the store, every time it is opened.

        Deliberately does **not** check whether the files still exist. Ten
        `stat()` calls against a dead network share would freeze the window for
        seconds each time the menu was opened; the check belongs on the click,
        where the operator has asked for that one file. Decorated to report and
        continue - a menu that cannot be built must not take the window down.
        """
        menu = self.window.recent_menu
        menu.clear()

        entries = self.recent_recipes.entries()
        if not entries:
            empty = menu.addAction("No recent recipes")
            empty.setEnabled(False)
            return

        for entry in entries:
            action = menu.addAction(entry.file_name)
            action.setToolTip(entry.path)
            action.triggered.connect(
                lambda _checked=False, path=entry.path: self._open_recent(path)
            )

        menu.addSeparator()
        menu.addAction("Clear list").triggered.connect(self._clear_recent_recipes)

    @catch_and_report_errors()
    def _open_recent(self, recipe_path: str) -> None:
        """
        One remembered recipe. The single place the list is checked against the
        disk: the file may have been moved, renamed or deleted since, and an
        entry that cannot be opened is dropped rather than left to fail again.
        """
        if not Path(recipe_path).is_file():
            self.recent_recipes.forget(recipe_path)
            report_problem(
                self,
                f"That recipe is no longer there, so it was removed from the "
                f"recent list: {recipe_path}",
                severity=ErrorSeverity.WARNING,
                operation="open_recent",
            )
            return
        self.open_recipe(recipe_path)

    @catch_and_report_errors()
    def _clear_recent_recipes(self) -> None:
        self.recent_recipes.clear()
        log.info("Recent recipes list cleared.")

    @catch_and_report_errors()
    def open_report_folder(self) -> None:
        """
        The report button: this run's own folder once there is one, the reports
        root before that - the operator browses old runs without finishing a new
        one. Decorated to report and continue: a file manager that will not open
        must not take the window with it.
        """
        if self.report_dir is not None:
            folder = Path(self.report_dir)
        else:
            folder = Path(ConfigHandler().get_parameter("paths.reports_dir"))
        if not folder.is_dir():
            report_problem(
                self,
                f"There is no report folder to open yet: {folder}",
                severity=ErrorSeverity.WARNING,
                operation="open_report_folder",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def ask_user(self, request: UserPromptRequest) -> None:
        self.center.show_prompt(
            request, lambda choice: self.answer_user_prompt(request, choice)
        )

    def ask_user_text(self, request: UserTextRequest) -> None:
        self.center.show_text_request(
            request, lambda text: self.answer_user_text(request, text)
        )

    def on_stop(self) -> None:
        """Tear the window down. Called from stop(), once CORE has sent StopHmi."""
        self._theme_disconnect()
        self.timer.stop()
        self.stop_log_tail()
        self.window.allow_close = True
        self.window.close()
        QTimer.singleShot(0, QApplication.quit)
