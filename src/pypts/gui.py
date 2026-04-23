# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from importlib.resources import files
from queue import SimpleQueue
from typing import List

import serial
import serial.tools.list_ports
from PySide6.QtCore import QAbstractItemModel, QEventLoop, QModelIndex, QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pypts import recipe
from pypts.gui_components.interaction_panel import InteractionPanel
from pypts.gui_components.log_panel import LogPanel
from pypts.gui_components.resources import load_cern_logo_pixmap
from pypts.gui_components.results_panel import ResultsPanel
from pypts.gui_components.step_table import StepTable
from pypts.gui_components.styles import CERN_BLUE, MTA_BLUE, get_stylesheet
from pypts.gui_components.toolbar import PtsToolBar
from pypts.utils import WAIT_FOR_TERMINATION, find_resource_path, get_project_root, get_step_result_colors


logger = logging.getLogger(__name__)

SCREEN_IDLE = 0
SCREEN_RUNNING = 1
SCREEN_PROMPT = 2
SCREEN_RESULTS = 3


class TextEditLoggerHandler(QObject, logging.Handler):
    """A logging handler that emits Qt signals for log messages."""

    new_message = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        super(logging.Handler).__init__()

    def emit(self, record):
        self.new_message.emit(self.format(record))


class ConfigFileLoader(QWidget):
    def __init__(self, return_content=True, binary=False):
        super().__init__()

        file_filter = (
            "Configuration Files (*.yaml *.yml *.json *.xml *.ini *.env *.sta *.csa *.cal *.snp *.mat *.bin);;"
            "All Files (*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Configuration File", "", file_filter)
        self.file_path = file_path or None
        self.content = None

        if self.file_path and return_content:
            mode = "rb" if binary else "r"
            with open(self.file_path, mode) as handle:
                self.content = handle.read()

        self.result = (self.file_path, self.content)


class MainWindow(QMainWindow):
    """The main application window, displaying recipe progress and results."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.q_in = None
        self.response_q = None
        self.running = False
        self.recipe_file = None
        self.recipe_to_run = None
        self._screen_idx = SCREEN_IDLE
        self._current_recipe_name = None
        self._current_recipe_description = None
        self._dark_mode = False

        self.cern_logo = load_cern_logo_pixmap()

        self.setWindowTitle("pypts")
        self.resize(1600, 1000)
        self.setMinimumSize(1000, 700)

        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._apply_theme()
        self._switch_screen(SCREEN_IDLE)

        self.log_handler = TextEditLoggerHandler(self)
        self.log_handler.setFormatter(logging.Formatter("%(levelname)s : %(name)s : %(message)s"))
        self.log_handler.new_message.connect(self.log_text_box.append_line)

    def _build_menu(self):
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)

        self.file_menu = menu_bar.addMenu("File")
        self.new_recipe_action = QAction("New Recipe", self)
        self.open_recipe_action = QAction("Open Recipe", self)
        self.exit_action = QAction("Exit", self)
        self.file_menu.addAction(self.new_recipe_action)
        self.file_menu.addAction(self.open_recipe_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = menu_bar.addMenu("Edit")
        self.edit_recipe_action = QAction("Edit Recipe", self)
        self.edit_menu.addAction(self.edit_recipe_action)

        self.view_menu = menu_bar.addMenu("View")
        self.toggle_dark_action = QAction("Toggle Dark Mode", self)
        self.view_menu.addAction(self.toggle_dark_action)

        self.about_menu = menu_bar.addMenu("About")
        self.open_gitlab = QAction("Gitlab", self)
        self.open_wiki = QAction("Wiki", self)
        self.about_menu.addAction(self.open_gitlab)
        self.about_menu.addAction(self.open_wiki)

        self.new_recipe_action.triggered.connect(self.on_new_clicked)
        self.open_recipe_action.triggered.connect(self.on_open_clicked)
        self.exit_action.triggered.connect(self.application_close)
        self.edit_recipe_action.triggered.connect(self.on_edit_clicked)
        self.toggle_dark_action.triggered.connect(self._toggle_dark)
        self.open_wiki.triggered.connect(self.on_open_wiki_clicked)
        self.open_gitlab.triggered.connect(self.on_open_gitlab_clicked)

    def _build_toolbar(self):
        self.toolbar = PtsToolBar(self)
        self.addToolBar(self.toolbar)

        self.action_open_recipe = self.toolbar.action_open
        self.action_start_recipe_execution = self.toolbar.action_start
        self.action_abort_recipe_execution = self.toolbar.action_stop

        self.action_open_recipe.triggered.connect(self.on_open_clicked)
        self.action_start_recipe_execution.triggered.connect(self.on_start_clicked)
        self.action_abort_recipe_execution.triggered.connect(self.on_abort_clicked)

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.screen_tab_bar = QTabBar()
        self.screen_tab_bar.setObjectName("screenTabBar")
        self.screen_tab_bar.setExpanding(False)
        for label in ("Idle", "Running", "Prompt", "Results"):
            self.screen_tab_bar.addTab(label)
        self.screen_tab_bar.currentChanged.connect(self._switch_screen)
        root.addWidget(self.screen_tab_bar)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 10)
        body_layout.setSpacing(8)
        root.addWidget(body, stretch=1)

        self.recipe_label = QLabel("No recipe loaded")
        self.recipe_label.setObjectName("recipeLabel")
        body_layout.addWidget(self.recipe_label)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        body_layout.addWidget(self._splitter, stretch=1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._left_stack = QStackedWidget()

        self._idle_left = self._make_idle_placeholder_left()
        self._left_stack.addWidget(self._idle_left)

        self.step_list = StepTable()
        self._left_stack.addWidget(self.step_list)

        self._results_panel = ResultsPanel()
        self.result_list = self._results_panel.tree_view
        self._left_stack.addWidget(self._results_panel)

        left_layout.addWidget(self._left_stack)
        self._splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._interaction_panel = InteractionPanel()
        self._interaction_panel.response_given.connect(self.interaction_response)
        self.picture_box = self._interaction_panel.image_label
        self.message_box = self._interaction_panel.message_label
        right_layout.addWidget(self._interaction_panel, stretch=1)

        log_label = QLabel("Log Output")
        log_label.setObjectName("sectionLabel")
        right_layout.addWidget(log_label)

        self.log_text_box = LogPanel()
        right_layout.addWidget(self.log_text_box)

        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 52)
        self._splitter.setStretchFactor(1, 48)

    def _build_statusbar(self):
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.statusBar().showMessage("Ready")

    def _apply_theme(self):
        self.setStyleSheet(get_stylesheet(self._dark_mode))
        self.toolbar.set_dark(self._dark_mode)
        self.step_list.set_dark(self._dark_mode)
        self._results_panel.set_dark(self._dark_mode)
        self._interaction_panel.set_dark(self._dark_mode)
        self.log_text_box.set_dark(self._dark_mode)

        bg = "#2b2b2b" if self._dark_mode else CERN_BLUE
        self.screen_tab_bar.setStyleSheet(
            f"QTabBar {{ background:{bg}; }}"
            f"QTabBar::tab {{ background:transparent; color:#B3CFF0; padding:6px 16px; border:none; border-radius:4px 4px 0 0; margin-right:2px; font-size:11px; }}"
            f"QTabBar::tab:selected {{ background:{MTA_BLUE}; color:#ffffff; font-weight:600; }}"
        )

    def _toggle_dark(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()

    def _switch_screen(self, index: int):
        self._screen_idx = index

        self.screen_tab_bar.blockSignals(True)
        self.screen_tab_bar.setCurrentIndex(index)
        self.screen_tab_bar.blockSignals(False)

        if index == SCREEN_IDLE:
            self._left_stack.setCurrentIndex(0)
            self._interaction_panel.set_idle()
            self.toolbar.set_can_start(bool(self.recipe_file))
            self.toolbar.set_can_stop(False)
            self.statusBar().showMessage("Ready")
        elif index == SCREEN_RUNNING:
            self._left_stack.setCurrentIndex(1)
            self._interaction_panel.set_idle()
            self.toolbar.set_can_start(False)
            self.toolbar.set_can_stop(True)
            self.statusBar().showMessage("Recipe running")
        elif index == SCREEN_PROMPT:
            self._left_stack.setCurrentIndex(1)
            self.toolbar.set_can_start(False)
            self.toolbar.set_can_stop(True)
            self.statusBar().showMessage("Waiting for user input")
        elif index == SCREEN_RESULTS:
            self._left_stack.setCurrentIndex(2)
            self.toolbar.set_can_start(True)
            self.toolbar.set_can_stop(False)
            self.statusBar().showMessage("Recipe completed")

    def _make_idle_placeholder_left(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)

        logo = QLabel()
        if self.cern_logo is not None and not self.cern_logo.isNull():
            logo.setPixmap(self.cern_logo.scaled(180, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo.setText("pypts")
            logo.setStyleSheet("font-size:24px; font-weight:600; color:#94a3b8;")
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        hint = QLabel("Open a YAML recipe to begin")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("font-size:12px; color:#94a3b8;")
        layout.addWidget(hint)
        return widget

    def on_open_wiki_clicked(self):
        webbrowser.open("https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/master/")

    def on_open_gitlab_clicked(self):
        webbrowser.open("https://gitlab.cern.ch/pts/framework/pypts")

    def on_new_clicked(self):
        previous_recipe = self.recipe_file
        self.recipe_file = None
        self.on_edit_clicked()
        self.recipe_file = previous_recipe

    def on_edit_clicked(self):
        logger.info("Opening recipe editor")
        root = get_project_root()
        recipe_editor_path = find_resource_path("recipe_creator.py", root=root)
        args = [sys.executable, str(root / recipe_editor_path)]
        if self.recipe_file:
            args.append(self.recipe_file)
        subprocess.Popen(args)

    def application_close(self):
        logger.info("Closing application")
        if self.q_in is not None:
            self.q_in.put(("EXIT",))
        self.close()

    def on_open_clicked(self):
        loader = ConfigFileLoader(return_content=False)
        if self.q_in is not None:
            self.q_in.put(("STOP",))
        if loader.result[0] is None:
            return

        self.recipe_file = str(loader.result[0])
        try:
            self.load_recipe()
            if self.q_in is not None:
                self.q_in.put(("LOAD", self.recipe_file))
            self.action_start_recipe_execution.setEnabled(True)
            self.toolbar.set_can_start(True)
            logger.info("Loaded recipe file %s", self.recipe_file)
        except Exception as exc:
            logger.error("Failed to create recipe from %s: %s", self.recipe_file, exc, exc_info=True)
            raise

    def on_start_clicked(self):
        if not self.running:
            self.reset_gui()
            self.load_recipe()
            self.running = True
        if self.q_in is not None:
            self.q_in.put(("START",))
        self.action_abort_recipe_execution.setEnabled(True)
        self.action_open_recipe.setEnabled(False)
        self.open_recipe_action.setEnabled(False)
        self._switch_screen(SCREEN_RUNNING)

    def on_abort_clicked(self):
        self.running = False
        self.action_abort_recipe_execution.setEnabled(False)
        self.action_start_recipe_execution.setEnabled(False)

        WAIT_FOR_TERMINATION.clear()
        self.clear_interaction_buttons()

        if self.q_in is not None:
            self.q_in.put(("STOP",))

        loop = QEventLoop()

        def check_if_done():
            if WAIT_FOR_TERMINATION.is_set():
                loop.quit()

        timer = QTimer()
        timer.timeout.connect(check_if_done)
        timer.start(100)
        loop.exec()
        timer.stop()

        self.action_open_recipe.setEnabled(True)
        self.open_recipe_action.setEnabled(True)
        self.action_start_recipe_execution.setEnabled(True)
        self.toolbar.set_can_start(True)
        self.toolbar.set_can_stop(False)
        self._switch_screen(SCREEN_IDLE)

    def reset_gui(self):
        self.step_list.load_steps([])
        self._results_panel.set_results([])
        self.log_text_box.clear()
        self.recipe_label.setText("No recipe loaded")
        self.message_box.clear()
        self._interaction_panel.set_idle()
        self.clear_interaction_buttons()
        self._switch_screen(SCREEN_IDLE)

    def load_recipe(self):
        recipe_to_run = recipe.Recipe(self.recipe_file)
        self.recipe_to_run = recipe_to_run
        sequence = recipe_to_run.sequences[recipe_to_run.main_sequence]
        self.update_sequence({"sequence": sequence})

    def add_interaction_button(self, label, value=None):
        self._interaction_panel.add_button(label, value or label)

    def clear_interaction_buttons(self):
        self._interaction_panel.clear_buttons()

    def get_serial_number(self, event_dict):
        logger.debug("get_serial_number method called")
        response_q: SimpleQueue = event_dict["response_q"]
        max_attempts = 3

        for _attempt in range(max_attempts):
            try:
                dialog = QInputDialog(self)
                text, ok = dialog.getText(self, "Serial Number of DUT", "Serial Number:")
                if ok and text.strip():
                    response_q.put(text.strip())
                    return
                if not ok:
                    response_q.put("CANCELLED")
                    return
            except Exception as exc:
                logger.error("Error in serial number dialog: %s", exc, exc_info=True)
                response_q.put("ERROR")
                return

        response_q.put("MAX_ATTEMPTS_REACHED")

    def interaction_response(self, response):
        if self.response_q is None:
            return

        self.response_q.put(response)
        if str(response) == "file":
            loader = ConfigFileLoader()
            self.response_q.put(loader.result)
        elif str(response) == "wrt":
            dialog = QInputDialog(self)
            written, _ok = dialog.getText(self, "", "Input:")
            self.response_q.put(written)
        elif str(response) == "ID":
            selected, ok = SerialPortDialog.getPort(self)
            self.response_q.put(selected if ok else ("", 9600, None))

        self.clear_interaction_buttons()
        self.message_box.clear()
        self._switch_screen(SCREEN_RUNNING if self.running else SCREEN_IDLE)

    def show_message(self, event_dict):
        self.response_q = event_dict["response_q"]
        message = event_dict["message"]
        image_path = event_dict["image_path"]
        flat_options = {
            key: value
            for option in event_dict.get("options") or []
            if isinstance(option, dict)
            for key, value in option.items()
        }

        buttons = [{"label": label or value.capitalize(), "value": value} for value, label in flat_options.items()]
        if not buttons:
            buttons = [{"label": "Confirm", "value": ""}]

        self._interaction_panel.set_prompt(message, buttons, image_path or None)
        self._switch_screen(SCREEN_PROMPT)

    def update_recipe_name(self, event_dict):
        recipe_name = event_dict["recipe_name"]
        recipe_description = event_dict["recipe_description"]
        self._current_recipe_name = recipe_name
        self._current_recipe_description = recipe_description
        self.recipe_label.setText(f"Running {recipe_name}...\n{recipe_description}")
        self.setWindowTitle("pypts")

    def update_sequence(self, event_dict):
        sequence: recipe.Sequence = event_dict["sequence"]
        steps = [
            {
                "id": str(step.id),
                "name": step.name,
                "description": getattr(step, "description", ""),
                "status": "PENDING",
            }
            for step in sequence.steps
            if not isinstance(step, recipe.SequenceStep)
        ]
        self.step_list.load_steps(steps)
        self.recipe_label.setText(f"Loaded {sequence.name}" if sequence.name else "Loaded recipe")
        self._switch_screen(SCREEN_RUNNING if self.running else SCREEN_IDLE)

    def update_step_result(self, step_status_vm: dict):
        updated = self.step_list.update_step_status(
            str(step_status_vm["step_uuid"]),
            step_status_vm["status_text"],
            status_color=step_status_vm.get("status_color"),
            text_color=step_status_vm.get("text_color"),
        )
        if not updated:
            logger.warning(
                "Could not find step with UUID %s in the step list to update status.",
                step_status_vm["step_uuid"],
            )

    def show_results(self, event_dict):
        results: List[recipe.StepResult] = event_dict["results"]
        self._results_panel.set_results(results)
        self.running = False
        self.action_abort_recipe_execution.setEnabled(False)
        self.action_open_recipe.setEnabled(True)
        self.open_recipe_action.setEnabled(True)
        self.action_start_recipe_execution.setEnabled(True)
        self._switch_screen(SCREEN_RESULTS)

    def update_running_step(self, event_dict):
        updated = self.step_list.mark_running(str(event_dict["step_uuid"]))
        if not updated:
            logger.warning(
                "Could not find step with UUID %s in the step list to highlight as running.",
                event_dict["step_uuid"],
            )

    def handle_post_load_recipe(self, event_dict):
        recipe_name = event_dict["recipe_name"]
        recipe_version = event_dict["recipe_version"]
        logger.info("Recipe '%s' (v%s) loaded.", recipe_name, recipe_version)
        self.statusBar().showMessage(f"Loaded recipe: {recipe_name} v{recipe_version}")

    def handle_post_run_sequence(self, event_dict):
        sequence_name = event_dict["sequence_name"]
        sequence_result = event_dict["sequence_result"]
        logger.info("Sequence '%s' finished with result: %s.", sequence_name, sequence_result)
        self.statusBar().showMessage(f"Sequence {sequence_name}: {sequence_result}")


class SerialWorker(QThread):
    result_ready = Signal(str, str)

    def __init__(self, port, baudrate, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate

    def run(self):
        try:
            with serial.Serial(self.port, self.baudrate, timeout=0.5) as ser:
                ser.write(b"*IDN?\n")
                response = ser.readline().decode(errors="replace").strip()
                idn = response or None
                self.result_ready.emit(f"{self.port} @ {self.baudrate} -> {idn}", idn)
        except Exception as exc:
            self.result_ready.emit(f"Error on {self.port}: {exc}", "")


class SerialPortDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Serial Port")
        self.resize(300, 150)
        self.worker_thread = None
        self.idn_response = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Available Serial Ports:"))
        self.combo = QComboBox()
        layout.addWidget(self.combo)
        self.refresh_ports()

        layout.addWidget(QLabel("Baudrate:"))
        self.baud_combo = QComboBox()
        self.common_baudrates = [
            300, 1200, 2400, 4800, 9600, 14400, 19200, 28800, 38400, 57600,
            74880, 115200, 128000, 230400, 250000, 256000, 460800, 500000,
            576000, 921600, 1000000, 1500000, 2000000, 3000000, 4000000,
        ]
        for rate in self.common_baudrates:
            self.baud_combo.addItem(str(rate))
        layout.addWidget(self.baud_combo)

        self.baudrate = int(self.baud_combo.currentText())
        self.baud_combo.currentIndexChanged.connect(self.update_baudrate)

        self.send_button = QPushButton("Send *IDN?")
        self.send_button.clicked.connect(self.send_idn)
        layout.addWidget(self.send_button)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.clicked.connect(self.ok_clicked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_baudrate(self):
        try:
            self.baudrate = int(self.baud_combo.currentText())
        except ValueError:
            self.baudrate = 9600

    def refresh_ports(self):
        self.combo.clear()
        for port in serial.tools.list_ports.comports():
            self.combo.addItem(port.device)

    def send_idn(self):
        port = self.combo.currentText()
        baud = self.baudrate
        self.output.append(f"Querying {port} @ {baud}...")
        self.send_button.setEnabled(False)

        self.worker_thread = SerialWorker(port, baud)
        self.worker_thread.result_ready.connect(self.handle_idn_result)
        self.worker_thread.finished.connect(lambda: self.send_button.setEnabled(True))
        self.worker_thread.start()

    def handle_idn_result(self, result_text, idn_response):
        self.output.append(result_text)
        self.idn_response = idn_response

    def ok_clicked(self):
        self.ok_button.setEnabled(False)
        port = self.combo.currentText()
        baud = self.baudrate
        self.output.append("Running final *IDN? query before accepting...")
        self.worker_thread = SerialWorker(port, baud)
        self.worker_thread.result_ready.connect(self._final_idn_done)
        self.worker_thread.start()

    def _final_idn_done(self, result_text, idn_response):
        self.output.append(result_text)
        self.idn_response = idn_response
        self.ok_button.setEnabled(True)
        self.accept()

    def selected_port(self):
        return self.combo.currentText()

    def selected_baudrate(self):
        return self.baudrate

    def idn(self):
        return self.idn_response

    @staticmethod
    def getPort(parent=None):
        dialog = SerialPortDialog(parent)
        result = dialog.exec()
        return (dialog.selected_port(), dialog.selected_baudrate(), dialog.idn()), result == QDialog.Accepted


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
