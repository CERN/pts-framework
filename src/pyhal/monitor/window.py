"""
The HAL monitor's window: a running HAL server's state, its devices, Close all / Stop, and the
HAL log's latest records. Plain and developer-facing. It only connects to a HAL: it never
starts one, and it stops one only when its user presses Stop HAL (user decision 2026-11-24).

**Threads.** Nothing here touches a socket, or anything that can block, on the GUI thread:
every MonitorLink call (status, close_all, stop, close, log_tail) and every LogTail
stop runs on a worker `threading.Thread`, and the worker reports back through a signal of
`_Signals`, which lives on the GUI thread, so the slot runs there (a queued connection).

- **The poll** (`HAL monitor poll`): the timer ticks every REFRESH_S; a tick while a poll is
  under way starts none (`_polling` is set on the GUI thread and cleared only when the poll's
  result has been shown). The poll worker also owns the log tail: when the status names
  another (pid, log) than the tail follows, it stops the old tail and starts a new one on the
  link's last `hello.log`. Only one poll runs at a time, so the tail is never touched by two.
- **An action** (`HAL monitor action`): Close all or Stop, after the user confirmed. One at a
  time; while it runs both buttons are disabled and the status bar says what runs. Its result
  goes to the status bar, and a list of devices not torn down also to a warning dialog.
- **The log tail** calls its sink on its own thread: the sink only stamps the record with the
  time it arrived and emits it; it never blocks, logs, or calls drain()/stop().
- **Closing** (`HAL monitor close`): closeEvent stops the timer and starts a worker that waits
  for a running poll, stops the tail and closes the link. Nothing is sent to the HAL; the
  window is gone before that worker ends. An action still running goes on to its end, its
  result unshown, and the process waits for it (wait_before_exit(), which `__main__` calls
  after the event loop): a Stop the user pressed is carried out even if the window is closed.
  Closing the window never stops the HAL.
- **Exit with the HAL** (`exit_with_hal=True`; what `python -m pyhal --window` opens): once a
  poll has seen a HAL answer, EXIT_AFTER_MISSED_POLLS polls in a row that find none close the
  window (one slow poll does not). The window follows the first HAL it saw, by its pid: a poll
  that finds a HAL of another pid (another starter's, started after this one had gone) counts
  as one that found none, so the window never latches onto it. Before any HAL has answered the
  window stays. The HAL ends its window at its own exit; this is the net for a HAL that was
  killed without one.
- **A poll that raises** (the link returns None for every failure it knows) still ends with
  `polled(None)`; the first such failure is logged at WARNING, the next ones at DEBUG.

`confirm()` and `warn()` are the module's two dialogs, so a test can answer them.
"""

import collections
import html
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyhal import client
from pyhal.client import DEFAULT_PORT
from pyhal.hal_log import TRACE
from pyhal.monitor.link import MonitorLink
from pyhal.protocol import messages

log = logging.getLogger(__name__)

#: How often the window polls the HAL's status.
REFRESH_S = 1.0

#: The most records the log view keeps.
LOG_VIEW_MAX_LINES = 500

#: The colours the window uses: medium tones, readable on light and dark backgrounds.
GREEN = "#2e9e44"
GREY = "#8a8a8a"
AMBER = "#d08a00"
RED = "#e03030"

#: The log view's level filter: its choices and the lowest level each shows.
LEVEL_FILTERS = {"DEBUG": 0, "INFO": logging.INFO, "WARNING": logging.WARNING}
DEFAULT_LEVEL_FILTER = "INFO"

TEARDOWN_WARNING = "Every open device is torn down, also those of other clients."

#: exit_with_hal: how many polls in a row must find no HAL, after one was seen, before the
#: window closes; more than one, so a single poll slower than POLL_TIMEOUT_S does not.
EXIT_AFTER_MISSED_POLLS = 2

#: How long the window waits for its closing worker when the process exits.
EXIT_WAIT_S = 10.0


def confirm(parent: QWidget, title: str, text: str) -> bool:
    """Ask Yes / No; True for Yes. No is the default."""
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def warn(parent: QWidget, title: str, text: str) -> None:
    """Show a warning dialog."""
    QMessageBox.warning(parent, title, text)


class _Signals(QObject):
    """The workers' way back to the GUI thread."""

    #: A poll ended: the StatusReport, or None when no HAL answered.
    polled = Signal(object)
    #: An action ended: its name, its result (or None), the error text ("" when none).
    acted = Signal(str, object, str)
    #: A log record arrived: level, the time it arrived (HH:MM:SS), the message.
    log_record = Signal(int, str, str)


class MonitorWindow(QMainWindow):
    """The monitor of the HAL on 127.0.0.1:<port>."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        *,
        exit_with_hal: bool = False,
    ) -> None:
        """
        Args:
            port: the HAL's port.
            exit_with_hal: the window closes itself once the HAL it has seen is gone
                (*Exit with the HAL* above).
        """
        super().__init__()
        self.port = port
        self.exit_with_hal = exit_with_hal
        self.link = MonitorLink(port)
        #: The log file the tail follows; "" while none. Set by the poll worker.
        self.tailed_log = ""

        self._signals = _Signals()
        self._signals.polled.connect(self._show_status)
        self._signals.acted.connect(self._show_action_result)
        self._signals.log_record.connect(self.add_log_record)

        self._closed = False
        self._polling = False
        self._reachable = False
        self._action: str | None = None
        self._workers: list[threading.Thread] = []
        self._poll_thread: threading.Thread | None = None
        self._poll_failed_before = False
        #: A poll has seen a HAL answer (exit_with_hal: only then does a HAL that has gone
        #: close the window).
        self._seen_hal = False
        #: The polls in a row that found no HAL since the last that found one.
        self._missed_polls = 0
        #: exit_with_hal: the pid of the first HAL a poll saw; a report of another pid counts
        #: as a poll that found none.
        self._hal_pid: int | None = None
        #: The other clients the last poll counted; 0 while no HAL answers.
        self._other_clients = 0
        #: The running action's worker and title; None when none runs.
        self._action_thread: threading.Thread | None = None
        self._action_title = ""
        # Owned by the poll worker (and, after it, by the closing worker).
        self._tail: client.LogTail | None = None
        self._tail_key: tuple[int, str] | None = None
        self._records: collections.deque[tuple[int, str, str]] = collections.deque(
            maxlen=LOG_VIEW_MAX_LINES
        )

        self.setWindowTitle(f"HAL monitor \N{EM DASH} 127.0.0.1:{port}")
        self._build()
        self._update_buttons()

        self._timer = QTimer(self)
        self._timer.setInterval(int(REFRESH_S * 1000))
        self._timer.timeout.connect(self._poll_now)
        self._timer.start()
        self._poll_now()

    # --- the widgets ---------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)

        header = QFormLayout()
        self.state_label = QLabel("")
        self.pid_label = self._value_label()
        self.version_label = self._value_label()
        self.bench_label = self._value_label()
        self.log_label = self._value_label()
        self.clients_label = self._value_label()
        self.activity_label = self._value_label()
        self.queued_label = self._value_label()
        self.refreshed_label = self._value_label()
        header.addRow("State:", self.state_label)
        header.addRow("PID:", self.pid_label)
        header.addRow("Version:", self.version_label)
        header.addRow("Bench file:", self.bench_label)
        header.addRow("Log file:", self.log_label)
        header.addRow("Other clients connected:", self.clients_label)
        header.addRow("Now:", self.activity_label)
        header.addRow("Queued requests:", self.queued_label)
        header.addRow("Last refresh:", self.refreshed_label)
        layout.addLayout(header)

        self.devices_table = QTableWidget(0, 4)
        self.devices_table.setHorizontalHeaderLabels(["Device", "Type", "State", "Last error"])
        self.devices_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.devices_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.devices_table.verticalHeader().setVisible(False)
        # Name, type and state as wide as their text; the last error takes the rest.
        devices_header = self.devices_table.horizontalHeader()
        for column in (0, 1, 2):
            devices_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        devices_header.setStretchLastSection(True)
        layout.addWidget(self.devices_table)

        buttons = QHBoxLayout()
        self.close_all_button = QPushButton("Close all devices")
        self.close_all_button.clicked.connect(self._close_all_pressed)
        self.stop_button = QPushButton("Stop HAL")
        self.stop_button.clicked.connect(self._stop_pressed)
        buttons.addWidget(self.close_all_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(QLabel("Log level:"))
        self.level_filter = QComboBox()
        self.level_filter.addItems(list(LEVEL_FILTERS))
        self.level_filter.setCurrentText(DEFAULT_LEVEL_FILTER)
        self.level_filter.currentTextChanged.connect(self._render_log)
        buttons.addWidget(self.level_filter)
        layout.addLayout(buttons)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_VIEW_MAX_LINES)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log_view, 1)

        self.setCentralWidget(central)
        self.resize(900, 650)

    def _value_label(self) -> QLabel:
        label = QLabel("-")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # A long path is cut at the window's edge rather than widening the window; its
        # tooltip has the whole text.
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    # --- the poll ------------------------------------------------------------------

    def _poll_now(self) -> None:
        """Start a poll on a worker, unless one runs or the window is closed."""
        if self._closed or self._polling:
            return
        self._polling = True
        thread = self._start_worker("HAL monitor poll", self._poll)
        self._poll_thread = thread

    def _poll(self) -> None:
        """
        On the poll worker: the status, and the log tail it calls for. Always ends with
        `polled`, so a poll that broke does not stop the polling for good.
        """
        report: messages.StatusReport | None = None
        try:
            report = self.link.status()
            if report is not None:
                self._follow_log(report)
        except Exception as exc:
            # Unexpected: the link returns None for every failure it knows.
            if self._poll_failed_before:
                log.debug("The HAL monitor's poll failed again: %s", exc, exc_info=True)
            else:
                self._poll_failed_before = True
                log.warning("The HAL monitor's poll failed: %s", exc, exc_info=True)
        finally:
            self._signals.polled.emit(report)

    def _follow_log(self, report: messages.StatusReport) -> None:
        """On the poll worker: a new tail when the HAL's (pid, log) is another."""
        key = (report.pid, report.log)
        if key == self._tail_key:
            return
        self._stop_tail()
        self._tail_key = key
        sink = self._log_sink()
        self._tail = self.link.log_tail(sink)
        if self._tail is not None and self.link.hello is not None:
            self.tailed_log = self.link.hello.log

    def _log_sink(self) -> Callable[[int, str], None]:
        signals = self._signals

        def sink(level: int, message: str) -> None:
            # On the tail's thread: stamp and hand over; never block, never log.
            signals.log_record.emit(level, time.strftime("%H:%M:%S"), message)

        return sink

    def _stop_tail(self) -> None:
        tail = self._tail
        self._tail = None
        self._tail_key = None
        self.tailed_log = ""
        if tail is not None:
            tail.stop()

    def _show_status(self, report: messages.StatusReport | None) -> None:
        """On the GUI thread: show a poll's result."""
        self._polling = False
        if self._closed:
            return
        self.refreshed_label.setText(time.strftime("%H:%M:%S"))
        if report is None:
            self._reachable = False
            self._other_clients = 0
            self._set_state("not reachable", GREY)
            for label in (
                self.pid_label,
                self.version_label,
                self.bench_label,
                self.log_label,
                self.clients_label,
                self.activity_label,
                self.queued_label,
            ):
                label.setText("-")
            self.devices_table.setRowCount(0)
        else:
            self._reachable = True
            if report.busy is None:
                self._set_state("running", GREEN)
                self.activity_label.setText("idle")
            else:
                self._set_state("busy", AMBER)
                self.activity_label.setText(_activity_text(report.busy))
            self.pid_label.setText(str(report.pid))
            self.version_label.setText(report.version)
            self.bench_label.setText(report.bench)
            self.bench_label.setToolTip(report.bench)
            self.log_label.setText(report.log)
            self.log_label.setToolTip(report.log)
            # The poll asks only `status`, so the HAL does not count it among its clients.
            self._other_clients = report.clients
            self.clients_label.setText(str(self._other_clients))
            self.queued_label.setText(str(report.queued))
            self._show_devices(report.devices)
        self._update_buttons()
        if self._is_our_hal(report):
            self._seen_hal = True
            self._missed_polls = 0
        elif self._seen_hal:
            self._missed_polls = self._missed_polls + 1
        gone = self._missed_polls >= EXIT_AFTER_MISSED_POLLS
        if self.exit_with_hal and gone:
            log.info("The HAL at 127.0.0.1:%d has gone; the monitor closes with it.", self.port)
            self.close()

    def _is_our_hal(self, report: messages.StatusReport | None) -> bool:
        """
        Whether the poll found the HAL the window follows: any HAL, except in exit_with_hal
        mode, where it is the first HAL seen - one another starter started on the port after
        it had gone is not, so the window does not latch onto it.
        """
        if report is None:
            return False
        if not self.exit_with_hal:
            return True
        if self._hal_pid is None:
            self._hal_pid = report.pid
            return True
        return report.pid == self._hal_pid

    def _set_state(self, word: str, colour: str) -> None:
        self.state_label.setText(word)
        self.state_label.setStyleSheet(f"color: {colour}; font-weight: bold;")

    def _show_devices(self, rows: list[dict[str, Any]]) -> None:
        table = self.devices_table
        table.setRowCount(len(rows))
        for number, row in enumerate(rows):
            last_error = row.get("last_error") or ""
            state = str(row.get("state", ""))
            cells = [str(row.get("name", "")), str(row.get("device_type", "")), state, last_error]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 2 and state == "failed":
                    item.setForeground(QColor(RED))
                if column == 3 and last_error:
                    item.setToolTip(last_error)
                table.setItem(number, column, item)

    # --- the actions ---------------------------------------------------------------

    def _close_all_pressed(self) -> None:
        text = (
            f"Close every open device on the HAL at 127.0.0.1:{self.port}?\n\n"
            f"{TEARDOWN_WARNING}"
        )
        if confirm(self, "Close all devices", text):
            self._run_action(
                "close_all", self.link.close_all, "Closing all devices...", "Close all devices"
            )

    def _stop_pressed(self) -> None:
        text = (
            f"Stop the HAL server at 127.0.0.1:{self.port}?\n\n"
            f"{TEARDOWN_WARNING} Then the HAL exits."
        )
        if confirm(self, "Stop HAL", text):
            self._run_action("stop", self.link.stop, "Stopping the HAL...", "Stop HAL")

    def _run_action(
        self, name: str, function: Callable[[], Any], running_text: str, button_title: str
    ) -> None:
        if self._action is not None or self._closed:
            return
        self._action = name
        self._update_buttons()
        self.statusBar().showMessage(running_text)
        signals = self._signals

        def run() -> None:
            result: Any = None
            error = ""
            try:
                result = function()
            except Exception as exc:
                # Whatever went wrong, the worker reports back, or the buttons stay disabled.
                log.debug("The HAL monitor's '%s' failed.", name, exc_info=True)
                error = str(exc) or type(exc).__name__
            signals.acted.emit(name, result, error)

        self._action_title = button_title
        self._action_thread = self._start_worker("HAL monitor action", run)

    def _show_action_result(self, name: str, result: object, error: str) -> None:
        """On the GUI thread: show what an action did."""
        self._action = None
        if self._closed:
            return
        titles = {"close_all": "Close all", "stop": "Stop"}
        title = titles.get(name, name)
        if error:
            self.statusBar().showMessage(f"{title} failed: {error}")
        else:
            names: list[str] = []
            if isinstance(result, list):
                names = [str(item) for item in result]
            done = ""
            if name == "stop":
                done = "The HAL stopped. "
            self.statusBar().showMessage(f"{title}: {done}{_torn_down_text(names)}")
            if names:
                warn(self, title, "These devices were not torn down: " + ", ".join(names))
        self._update_buttons()
        self._poll_now()

    def _update_buttons(self) -> None:
        idle = self._action is None
        self.close_all_button.setEnabled(idle and self._reachable)
        self.stop_button.setEnabled(idle and self._reachable)

    # --- the log view --------------------------------------------------------------

    def add_log_record(self, level: int, stamp: str, message: str) -> None:
        """On the GUI thread: keep a record, and show it if the level filter lets it through."""
        if self._closed:
            return
        self._records.append((level, stamp, message))
        if level >= self._lowest_level():
            self.log_view.appendHtml(_record_html(level, stamp, message))

    def _render_log(self) -> None:
        self.log_view.clear()
        lowest = self._lowest_level()
        for level, stamp, message in self._records:
            if level >= lowest:
                self.log_view.appendHtml(_record_html(level, stamp, message))

    def _lowest_level(self) -> int:
        return LEVEL_FILTERS.get(self.level_filter.currentText(), logging.INFO)

    # --- workers and closing -------------------------------------------------------

    def _start_worker(self, name: str, target: Callable[[], None]) -> threading.Thread:
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._workers.append(thread)
        thread.start()
        return thread

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        """
        Stop the timer; the tail and the link close on a worker. Sends nothing to the HAL and
        asks nothing: closing the window leaves the HAL and its devices as they are.
        """
        if not self._closed:
            self._closed = True
            self._timer.stop()
            poll_thread = self._poll_thread

            def close_down() -> None:
                if poll_thread is not None:
                    poll_thread.join()
                self._stop_tail()
                self.link.close()

            self._start_worker("HAL monitor close", close_down)
        event.accept()

    def wait_for_workers(self, timeout: float) -> bool:
        """Wait for every worker of the window, at most `timeout` s in all; True when all ended."""
        deadline = time.monotonic() + timeout
        for worker in list(self._workers):
            worker.join(max(deadline - time.monotonic(), 0.0))
        return not any(worker.is_alive() for worker in self._workers)

    def wait_before_exit(self) -> None:
        """
        Once the window is closed: wait for a running action to its end, however long that
        takes - a Stop the user pressed is carried out even when the window was closed under
        it - and then for the closing worker, at most EXIT_WAIT_S.
        """
        action_thread = self._action_thread
        if action_thread is not None and action_thread.is_alive():
            log.info("Waiting for %s to finish before the monitor exits.", self._action_title)
            action_thread.join()
        self.wait_for_closing(EXIT_WAIT_S)

    def wait_for_closing(self, timeout: float) -> bool:
        """Wait for the closing worker only (not for an action); True when it ended."""
        deadline = time.monotonic() + timeout
        for worker in list(self._workers):
            if worker.name == "HAL monitor close":
                worker.join(max(deadline - time.monotonic(), 0.0))
        return not any(
            worker.is_alive() for worker in self._workers if worker.name == "HAL monitor close"
        )


# --- texts -----------------------------------------------------------------------------


def _activity_text(busy: dict[str, Any]) -> str:
    operation = busy.get("operation", "?")
    device = busy.get("device")
    since = busy.get("since", "?")
    if device:
        return f"running {operation} on {device} since {since}"
    return f"running {operation} since {since}"


def _torn_down_text(names: list[str]) -> str:
    if names:
        return "Not torn down: " + ", ".join(names)
    return "Every device was torn down."


def _level_name(level: int) -> str:
    if level == TRACE:
        return "TRACE"
    return logging.getLevelName(level)


def _record_html(level: int, stamp: str, message: str) -> str:
    text = html.escape(f"{stamp} {_level_name(level)} {message}")
    text = text.replace("\n", "<br>")
    colour = ""
    if level >= logging.ERROR:
        colour = RED
    elif level >= logging.WARNING:
        colour = AMBER
    if colour:
        return f'<span style="white-space:pre; color:{colour};">{text}</span>'
    return f'<span style="white-space:pre;">{text}</span>'
