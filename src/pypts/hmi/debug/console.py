# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The debug console window, and the HmiClient behind it.

It is a real frontend. It speaks the same protocol the GUI and the CLI speak,
answers StopHmi with the same handshake, and answers the engine's questions -
because a console that declined every UserPromptRequest could not be used to
test the one thing about prompts that is hard, which is that the answer finds
its way back to the step that asked.

What it adds is four views of a system that otherwise shows a frontend one
status line:

    Trace    every message on every link, live
    Inject   put messages on those links
    Run      the run as a frontend sees it, drawn from the progress events
    Modules  heartbeat age and last error per module
"""

import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.debug import icons
from pypts.hmi.debug.icons import label
from pypts.hmi.debug.inject_panel import InjectPanel
from pypts.hmi.debug.trace_model import TraceFilter, TraceModel
from pypts.hmi.hmi_client import HmiClient
from pypts.logger.log import init_logging, log
from pypts.messages import Channel
from pypts.messages.common import ModuleError, ResultType, StepOutcome
from pypts.messages.debug_link import ALL_LINKS, InjectMessage, InjectTarget, TapRecord
from pypts.messages.hmi_link import CoreToHmi, HmiToCore
from pypts.messages.run_events import (
    SerialNumberRequest,
    StepStarted,
    UserPromptRequest,
)

#: Milliseconds between polls. Shorter than the GUI's 50 ms because this window
#: is also draining the tap, which carries every link's traffic rather than one.
POLL_INTERVAL_MS = 30

#: Modules CORE supervises, in the order the Modules tab lists them. Matches the
#: names in core.py, which are the `source` on each module's heartbeat.
MODULES = ("hmi", "sequencer", "report")

#: A module CORE has not heard from for this long is shown as late. Same value
#: as core.HEARTBEAT_TIMEOUT_S, duplicated rather than imported so that the
#: console does not pull the engine's module in just to draw a colour.
HEARTBEAT_TIMEOUT_S = 5.0

#: The events that mean a module's loop has ended, by message type name.
STOPPED_TYPES = {
    "HmiStopped": "hmi",
    "SequencerStopped": "sequencer",
    "ReportStopped": "report",
}

RESULT_COLOURS = {
    ResultType.PASS: "#2e7d32",
    ResultType.FAIL: "#c62828",
    ResultType.ERROR: "#c62828",
    ResultType.STOP: "#ef6c00",
    ResultType.SKIP: "#757575",
    ResultType.DONE: "#1565c0",
}


def debug_main(
    to_core: Channel[HmiToCore],
    from_core: Channel[CoreToHmi],
    log_queue,
    tap_inbox: Channel[TapRecord],
    to_core_debug: Channel[InjectMessage],
) -> None:
    """
    Entry point. Runs in its own process, like the GUI, so log records have to be
    routed to the Logger before anything is logged.
    """
    init_logging(log_queue)
    app = QApplication(sys.argv)
    console = DebugConsole(to_core, from_core, tap_inbox, to_core_debug)
    console.show()
    sys.exit(app.exec())


class DebugConsole(HmiClient):
    """
    The console's protocol half.

    Holds its window rather than inheriting from one, for the same reason the
    GUI does: QWidget.__init__ cooperatively calls the next __init__ in the MRO,
    which would reach HmiClient.__init__ with no arguments.
    """

    def __init__(
        self,
        to_core: Channel[HmiToCore],
        from_core: Channel[CoreToHmi],
        tap_inbox: Channel[TapRecord],
        to_core_debug: Channel[InjectMessage],
    ) -> None:
        super().__init__(to_core, from_core)
        log.info("Starting module...")

        self.tap_inbox = tap_inbox
        self.to_core_debug = to_core_debug

        #: Per-module state derived from the tap, for the Modules tab.
        self.last_heartbeat: dict[str, float] = {}
        self.stopped: set[str] = set()
        self.last_error: dict[str, str] = {}

        #: Row index per step_id, so StepFinished updates the row StepStarted made.
        self._step_rows: dict[object, int] = {}

        self._build_window()

        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_core)
        self.timer.timeout.connect(self.do_periodic_tasks)
        self.timer.timeout.connect(self.poll_tap)
        self.timer.start(POLL_INTERVAL_MS)
        log.info("Starting main event loop.")

    # --- Window ---------------------------------------------------------------

    def _build_window(self) -> None:
        self.window = QMainWindow()
        self.window.setWindowTitle("PTS Debug Console")
        self.window.resize(1280, 800)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_trace_tab(), "Trace")
        self.tabs.addTab(InjectPanel(self), "Inject")
        self.tabs.addTab(self._build_run_tab(), "Run")
        self.tabs.addTab(self._build_modules_tab(), "Modules")
        self.window.setCentralWidget(self.tabs)

        self.status_bar = self.window.statusBar()
        self.status_bar.showMessage("Idle")

    def _build_trace_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.trace_model = TraceModel()
        self.trace_filter = TraceFilter()
        self.trace_filter.setSourceModel(self.trace_model)

        controls = QHBoxLayout()

        search = QLineEdit()
        search.setPlaceholderText("Filter by link, message type or payload")
        search.textChanged.connect(self.trace_filter.set_text)
        controls.addWidget(search, stretch=1)

        heartbeats = QCheckBox("Show heartbeats")
        heartbeats.setChecked(False)
        heartbeats.toggled.connect(lambda shown: self.trace_filter.set_hide_noise(not shown))
        controls.addWidget(heartbeats)

        self.follow = QCheckBox("Follow")
        self.follow.setChecked(True)
        controls.addWidget(self.follow)

        clear = QPushButton("Clear")
        clear.clicked.connect(self.trace_model.clear)
        controls.addWidget(clear)
        layout.addLayout(controls)

        # One toggle per link. All on at the start, because the first question a
        # new user of this window has is "what is happening at all".
        link_row = QHBoxLayout()
        self._link_boxes: dict[str, QCheckBox] = {}
        for link in ALL_LINKS:
            box = QCheckBox(link)
            box.setChecked(True)
            box.toggled.connect(self._apply_link_filter)
            self._link_boxes[link] = box
            link_row.addWidget(box)
        link_row.addStretch(1)
        layout.addLayout(link_row)

        self.trace_view = QTableView()
        self.trace_view.setModel(self.trace_filter)
        self.trace_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trace_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trace_view.setAlternatingRowColors(True)
        self.trace_view.verticalHeader().setVisible(False)
        header = self.trace_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.trace_view)
        return page

    def _build_run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.run_label = QLabel("No run yet. Use Inject -> Simulate passing run.")
        self.run_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.run_label)

        self.steps_table = QTableWidget(0, 3)
        self.steps_table.setHorizontalHeaderLabels(("Step", "Result", "Info"))
        self.steps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.steps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.steps_table)
        return page

    def _build_modules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.modules_table = QTableWidget(len(MODULES), 4)
        self.modules_table.setHorizontalHeaderLabels(("Module", "State", "Last heartbeat", "Last error"))
        self.modules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.modules_table.verticalHeader().setVisible(False)
        self.modules_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for row, name in enumerate(MODULES):
            self.modules_table.setItem(row, 0, QTableWidgetItem(name))
        layout.addWidget(self.modules_table)

        layout.addWidget(
            QLabel(
                "Heartbeat age is measured from the last Heartbeat seen on the tap.\n"
                "CORE treats a module as late after 5.0 s."
            )
        )
        return page

    def show(self) -> None:
        self.window.show()

    def _apply_link_filter(self) -> None:
        chosen = {link for link, box in self._link_boxes.items() if box.isChecked()}
        self.trace_filter.set_links(None if len(chosen) == len(ALL_LINKS) else chosen)

    # --- The tap ---------------------------------------------------------------

    def poll_tap(self) -> None:
        """
        Drain the tap and update everything derived from it.

        Collected into a batch first so the table gets one insertion for the
        whole tick rather than one per record.
        """
        batch: list[TapRecord] = list(self.tap_inbox.receive(limit=500))

        if batch:
            self.trace_model.append(batch)
            for record in batch:
                self._note_module_state(record)
            if self.follow.isChecked():
                self.trace_view.scrollToBottom()

        self._refresh_modules()

    def _note_module_state(self, record: TapRecord) -> None:
        """Derive module liveness from traffic. The link names who sent it."""
        source = record.link.split("->")[0]

        if record.message_type == "Heartbeat":
            self.last_heartbeat[source] = record.timestamp
        elif record.message_type == "ModuleError":
            self.last_error[source] = record.payload
        elif record.message_type in STOPPED_TYPES:
            self.stopped.add(STOPPED_TYPES[record.message_type])

    def _refresh_modules(self) -> None:
        now = time.time()
        for row, name in enumerate(MODULES):
            if name in self.stopped:
                state, colour = label(icons.STOPPED, "stopped"), "#757575"
            elif name not in self.last_heartbeat:
                state, colour = label(icons.PENDING, "no heartbeat yet"), "#ef6c00"
            elif now - self.last_heartbeat[name] > HEARTBEAT_TIMEOUT_S:
                # Late is the one that means something is wrong right now, so it
                # gets the error glyph rather than the warning one.
                state, colour = label(icons.ERROR, "late"), "#c62828"
            else:
                state, colour = label(icons.OK, "alive"), "#2e7d32"

            self._set_cell(self.modules_table, row, 1, state, colour)

            last = self.last_heartbeat.get(name)
            self._set_cell(
                self.modules_table, row, 2, "-" if last is None else f"{now - last:.1f} s ago"
            )
            self._set_cell(self.modules_table, row, 3, self.last_error.get(name, ""))

    def _set_cell(self, table, row: int, column: int, text: str, colour: str | None = None) -> None:
        """Write one cell, optionally coloured. Replaces the item rather than
        editing it, so a cell that had a colour and no longer needs one loses it."""
        item = QTableWidgetItem(text)
        if colour:
            item.setForeground(QBrush(QColor(colour)))
        table.setItem(row, column, item)

    # --- Sending ---------------------------------------------------------------

    def send_as_hmi(self, message) -> None:
        """
        Put a message on hmi->core, as this console's own frontend traffic.

        Separate from inject() because it needs no help from CORE: the console is
        the HMI, so this is the same call the GUI makes.
        """
        self.core.send(message)

    def inject(self, target: InjectTarget, message) -> None:
        """Ask CORE to put a message on one of the links only it can reach."""
        self.to_core_debug.send(InjectMessage(target=target, message=message))

    # --- Presentation ----------------------------------------------------------

    def show_status(self, text: str) -> None:
        self.status_bar.showMessage(text)

    def show_error(self, error: ModuleError) -> None:
        log.error(f"{error.source}: {error.message}")
        # The severity is the sender's own judgement of how bad this is, so the
        # glyph follows it rather than treating every reported error alike.
        icon = icons.SEVERITY_ICONS.get(error.severity, icons.ERROR)
        self.status_bar.showMessage(label(icon, f"[{error.source}] {error.message}"))

    def show_recipe_loaded(self, recipe_name: str, recipe_version: str) -> None:
        self.run_label.setText(label(icons.OK, f"Loaded {recipe_name} ({recipe_version})"))

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        self.steps_table.setRowCount(0)
        self._step_rows.clear()
        self.run_label.setText(label(icons.RUNNING, f"Running {recipe_name} - {recipe_description}"))

    def show_sequence_started(self, sequence_name: str) -> None:
        self.status_bar.showMessage(label(icons.RUNNING, f"Sequence '{sequence_name}' started"))

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        icon = icons.RESULT_ICONS.get(result, "")
        self.status_bar.showMessage(label(icon, f"Sequence '{sequence_name}' -> {result}"))

    def show_step_started(self, event: StepStarted) -> None:
        row = self.steps_table.rowCount()
        self.steps_table.insertRow(row)
        self._step_rows[event.step_id] = row
        self.steps_table.setItem(row, 0, QTableWidgetItem(event.step_name))
        self._set_cell(self.steps_table, row, 1, label(icons.RUNNING, "running"), "#1565c0")
        self.steps_table.scrollToBottom()

    def show_step_finished(self, outcome: StepOutcome) -> None:
        row = self._step_rows.get(outcome.step_id)
        if row is None:
            # A StepFinished with no StepStarted before it. Legitimate when a
            # single step is injected on its own, so it gets a row rather than a
            # complaint.
            row = self.steps_table.rowCount()
            self.steps_table.insertRow(row)
            self._step_rows[outcome.step_id] = row
            self.steps_table.setItem(row, 0, QTableWidgetItem(outcome.step_name))

        self._set_cell(
            self.steps_table,
            row,
            1,
            label(icons.RESULT_ICONS.get(outcome.result, ""), str(outcome.result)),
            RESULT_COLOURS.get(outcome.result),
        )
        self.steps_table.setItem(row, 2, QTableWidgetItem(outcome.error_info))

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        icon = icons.RESULT_ICONS.get(result, "")
        self.run_label.setText(label(icon, f"Run finished: {result} over {len(outcomes)} steps"))
        self.status_bar.showMessage(label(icon, f"Run finished: {result}"))

    # --- Questions -------------------------------------------------------------
    #
    # Overridden so the round trip completes. HmiClient's defaults decline, which
    # is right for a frontend that cannot draw a dialog and wrong for this one.

    def ask_user(self, request: UserPromptRequest) -> None:
        options = list(request.options) or ["OK"]
        choice, accepted = QInputDialog.getItem(
            self.window, "Operator prompt", request.message, options, 0, False
        )
        self.answer_user_prompt(request, choice if accepted else None)

    def ask_serial_number(self, request: SerialNumberRequest) -> None:
        serial, accepted = QInputDialog.getText(
            self.window, "Serial number", "Serial number of the unit under test:"
        )
        self.answer_serial_number(request, serial if accepted else None)

    def on_stop(self) -> None:
        self.timer.stop()
        self.window.close()
        QTimer.singleShot(0, QApplication.quit)
