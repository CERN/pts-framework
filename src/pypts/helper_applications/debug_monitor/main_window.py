# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Monitor window: a trace table and a module table, fed by one timer.

The whole application is a loop: read whatever the Logger has written since the
last tick, parse it, fold it into the liveness tracker, and append whatever was a
message to the table. Everything else here is presentation.

Two things worth knowing before changing this file:

**Nothing blocks.** The timer owns the reading, the same way the GUI's QTimer
owns polling CORE (`hmi/gui/gui.py`), so there is no thread and no queue. A tick
that finds an idle log costs one `read()` that returns nothing.

**A window class may inherit QMainWindow here.** `hmi/gui/gui.py` deliberately
*holds* its widget instead, because `QWidget.__init__` cooperatively calls the
next `__init__` in the MRO and would reach `HmiClient.__init__` with no
arguments. The Monitor has no second base class - it is not an HmiClient, it
speaks no protocol, it holds no QueueWrapper - so the ordinary Qt spelling is safe.
That difference is the point: this tool only reads a file.

Known limit: attaching to an eight-hour run at DEBUG means parsing the whole file
on the first tick, which takes a moment. The file is read from the beginning on
purpose - replaying the run you just missed is half of what this is for - and the
table keeps a window on the tail regardless.
"""

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
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

from pypts.helper_applications.debug_monitor.liveness import (
    ALIVE,
    DEAD,
    STOPPED,
    VERDICT_FATAL,
    VERDICT_RESPONDING,
    VERDICT_TIMEOUT,
    LivenessTracker,
)
from pypts.helper_applications.debug_monitor.log_source import LogFollower
from pypts.helper_applications.debug_monitor.trace_model import TraceFilter, TraceModel
from pypts.helper_applications.debug_monitor.trace_parser import (
    as_trace_event,
    parse_line,
)

#: Milliseconds between reads of the log file. Ten times a second is far below
#: what the eye needs and far above what the file does, which leaves the batches
#: small enough that the model never inserts a visible stutter.
POLL_INTERVAL_MS = 100

#: There is no list of links here, and that is deliberate. A checkbox is created
#: the first time a link is seen in the log, so a link added to the framework is
#: filterable in this window without anybody editing this file - and so is the
#: `?` of an anonymous QueueWrapper, which is a defect you may well want to
#: isolate rather than merely notice.
#:
#: The list this replaced was imported from `links.py`, which was honest but
#: still a registration: a link that existed and was not named there appeared in
#: the table with no way to filter it out of the noise around it.

MODULE_COLUMNS = ("Module", "State", "Last heartbeat", "Age", "CORE says", "Last error")

STATE_COLOURS = {
    ALIVE: QColor(60, 150, 70),
    DEAD: QColor(190, 60, 60),
    STOPPED: QColor(130, 130, 130),
}

#: The same treatment for CORE's verdict, because the strongest thing CORE ever
#: says about a module must not be the same grey as the rest of the row.
#:
#: `fatal` is not a louder `timeout`, it is a different event: a timeout is CORE
#: reporting and the run went on, a fatal is CORE acting and the run did not.
#: Red for the one that ended the run, amber for the one that only warned about
#: it, green for a module that came back.
VERDICT_COLOURS = {
    VERDICT_FATAL: QColor(190, 60, 60),
    VERDICT_TIMEOUT: QColor(190, 140, 40),
    VERDICT_RESPONDING: QColor(60, 150, 70),
}

NO_TRACE_HINT = (
    "No message trace in this log yet — was the run started with --log-level DEBUG?"
)


class DebugMonitor(QMainWindow):
    """
    The window. Construct it with the path of a run log and call `show()`.

    It starts reading immediately, from the beginning of the file, so a run that
    is already finished renders in full and one that is still going catches up
    and then follows.
    """

    def __init__(self, log_path: Path) -> None:
        super().__init__()

        self.log_path = Path(log_path)
        self.follower = LogFollower(self.log_path)
        self.follower.open()
        self.tracker = LivenessTracker()

        #: Whether anything at all has been read. Distinct from `trace_seen`:
        #: an empty file is not the same complaint as a file with no trace in it.
        self.lines_read = 0

        self.setWindowTitle(f"PTS Debug Monitor — {self.log_path.name}")
        self.resize(1280, 720)

        tabs = QTabWidget()
        tabs.addTab(self._build_trace_tab(), "Trace")
        tabs.addTab(self._build_modules_tab(), "Modules")
        self.setCentralWidget(tabs)

        self.status = QLabel()
        self.statusBar().addWidget(self.status)
        # Permanent (right side of the status bar), so it is there on both tabs.
        self.open_logs_button = QPushButton("Open logs folder")
        self.open_logs_button.clicked.connect(self._open_logs_folder)
        self.statusBar().addPermanentWidget(self.open_logs_button)
        self._refresh_status()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_INTERVAL_MS)

    # --- Building the tabs ---

    def _build_trace_tab(self) -> QWidget:
        """The message trace: filters on top, table below."""
        self.trace_model = TraceModel()
        self.trace_filter = TraceFilter()
        self.trace_filter.setSourceModel(self.trace_model)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by link, message type or payload…")
        self.search.textChanged.connect(self.trace_filter.set_text)

        self.show_heartbeats = QCheckBox("Show heartbeats")
        self.show_heartbeats.setChecked(False)
        self.show_heartbeats.toggled.connect(
            lambda checked: self.trace_filter.set_hide_noise(not checked)
        )

        self.follow = QCheckBox("Follow")
        self.follow.setChecked(True)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_trace)

        controls = QHBoxLayout()
        controls.addWidget(self.search, stretch=1)
        controls.addWidget(self.show_heartbeats)
        controls.addWidget(self.follow)
        controls.addWidget(clear_button)

        # One checkbox per link, created as links are discovered rather than
        # from a list. Kept in a dict so the handler can rebuild the hidden set
        # from scratch rather than track individual toggles.
        self.link_boxes: dict[str, QCheckBox] = {}
        self.link_row = QHBoxLayout()
        self.link_row.addStretch(1)

        self.trace_view = QTableView()
        self.trace_view.setModel(self.trace_filter)
        self.trace_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trace_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trace_view.verticalHeader().setVisible(False)
        self.trace_view.horizontalHeader().setStretchLastSection(True)
        self.trace_view.setWordWrap(False)
        self.trace_view.resizeColumnsToContents()

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addLayout(self.link_row)
        layout.addWidget(self.trace_view)

        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def _build_modules_tab(self) -> QWidget:
        """
        Who is alive. One row per module *discovered in the log*, refreshed every
        tick - not per module this tool was told about, because it is told about
        none.

        It therefore starts with no rows at all and grows as the run introduces
        its modules, in the order it introduces them, which is roughly startup
        order. A module added to the framework after this file was written
        appears here on its own.

        A QTableWidget rather than a model: a handful of rows rewritten ten times
        a second is not worth a model, and the values are derived rather than
        stored, so there is nothing for a model to own.
        """
        self.modules_table = QTableWidget(0, len(MODULE_COLUMNS))
        self.modules_table.setHorizontalHeaderLabels(MODULE_COLUMNS)
        self.modules_table.verticalHeader().setVisible(False)
        self.modules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.modules_table.horizontalHeader().setSectionResizeMode(
            len(MODULE_COLUMNS) - 1, QHeaderView.Stretch
        )

        explanation = QLabel(
            "Derived from the heartbeat traces in the log, not reported by CORE — "
            "CORE keeps this state privately and sends it to nobody. "
            "Rows are discovered, not declared: a module appears here the first time it "
            "sends anything, so a module missing from this table is one that has not spoken "
            "yet, which is not the same as one that is not running. "
            "'CORE says' is its own verdict from its log lines: the two disagreeing is a defect. "
            "'timeout' is CORE reporting a module late and carrying on; "
            "'fatal' is CORE ending the run over it."
        )
        explanation.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(explanation)
        layout.addWidget(self.modules_table)

        tab = QWidget()
        tab.setLayout(layout)
        return tab

    # --- The loop ---

    def poll(self) -> None:
        """
        One tick: read, parse, fold, append.

        Everything downstream of `read_lines()` is pure, so a tick that reads
        nothing does nothing except leave the display as it was.
        """
        lines = self.follower.read_lines()
        if not lines:
            return

        self.lines_read += len(lines)

        events = []
        for raw in lines:
            line = parse_line(raw)
            self.tracker.feed(line)
            event = as_trace_event(line)
            if event is not None:
                events.append(event)

        if events:
            self.ensure_link_boxes(event.link for event in events)
            self.trace_model.append(events)
            if self.follow.isChecked():
                self.trace_view.scrollToBottom()

        self._refresh_modules()
        self._refresh_status()

    def ensure_link_boxes(self, seen_links) -> None:
        """
        Give every link a checkbox, creating them as links turn up.

        The Monitor has no list of links and does not want one - see the note
        where FILTERABLE_LINKS used to be. A new checkbox starts checked, because
        a link nobody has an opinion about yet is one whose messages you want to
        see; hiding something the moment it first appeared would be exactly
        backwards for a troubleshooting tool.

        Inserted before the trailing stretch, so the row stays left-aligned as
        it grows.
        """
        for link in seen_links:
            if link in self.link_boxes:
                continue
            box = QCheckBox(link)
            box.setChecked(True)
            box.toggled.connect(self._apply_link_filter)
            self.link_boxes[link] = box
            self.link_row.insertWidget(self.link_row.count() - 1, box)

    def _apply_link_filter(self) -> None:
        """Rebuild the hidden-link set from the checkboxes."""
        self.trace_filter.set_hidden_links(
            link for link, box in self.link_boxes.items() if not box.isChecked()
        )

    def _open_logs_folder(self) -> None:
        """
        Show the folder this log lives in, in the system file browser.

        Every run's log is a sibling file there - the folder is
        `paths.logs_dir` from config.ini - so this is the one button that
        answers "where are my logs".
        """
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path.parent)))

    def _clear_trace(self) -> None:
        """
        Empty the table without forgetting who is alive.

        The liveness tracker is deliberately not reset: clearing is about
        finding the next thing in a noisy table, not about pretending the run
        started over.
        """
        self.trace_model.clear()
        self._refresh_status()

    def _refresh_modules(self) -> None:
        """
        Redraw the module table from the tracker.

        The row count follows the tracker rather than a constant: modules are
        discovered, so the table has as many rows as the log has shown modules,
        and setRowCount() both grows it and leaves the existing rows alone.
        """
        modules = self.tracker.modules()
        if self.modules_table.rowCount() != len(modules):
            self.modules_table.setRowCount(len(modules))

        for row, module in enumerate(modules):
            state = self.tracker.state(module)
            age = self.tracker.age(module)
            last = self.tracker.last_heartbeat(module)

            values = (
                module,
                state,
                "—" if last is None else last.strftime("%H:%M:%S"),
                "—" if age == float("inf") else f"{age:.1f} s",
                self.tracker.core_verdict(module) or "—",
                self.tracker.last_error(module) or "—",
            )

            verdict = self.tracker.core_verdict(module)

            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 1 and state in STATE_COLOURS:
                    item.setForeground(STATE_COLOURS[state])
                elif column == 4 and verdict in VERDICT_COLOURS:
                    item.setForeground(VERDICT_COLOURS[verdict])
                    if verdict == VERDICT_FATAL:
                        # The one thing in this window worth finding at a glance:
                        # CORE did not merely notice, it ended the run over this.
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                self.modules_table.setItem(row, column, item)

        self.modules_table.resizeColumnsToContents()
        self.modules_table.horizontalHeader().setSectionResizeMode(
            len(MODULE_COLUMNS) - 1, QHeaderView.Stretch
        )

    def _refresh_status(self) -> None:
        """
        The status line, and the one warning that matters.

        A run at INFO produces a log with no trace in it at all. Showing an empty
        table over that would read as "nothing happened", which is wrong and
        expensive to work out, so it is said in words instead.
        """
        if self.lines_read and not self.tracker.trace_seen:
            self.status.setText(f"{self.log_path}  —  {NO_TRACE_HINT}")
            return

        shown = self.trace_filter.rowCount()
        total = self.trace_model.total_seen
        clock = self.tracker.now
        at = "" if clock is None else f"  —  log time {clock.strftime('%H:%M:%S')}"
        self.status.setText(f"{self.log_path}  —  {total} messages, {shown} shown{at}")

    # --- Teardown ---

    def closeEvent(self, event) -> None:
        """Stop the timer and let go of the file before the window goes."""
        self.timer.stop()
        self.follower.close()
        super().closeEvent(event)
