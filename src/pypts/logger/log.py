# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Central logging for pypts.

One dedicated process - the Logger - owns the only open handle of the log file
and is the single writer. Every other process and thread pushes
logging.LogRecord objects onto a shared queue (through logging's QueueHandler);
the Logger drains that queue and writes the records out.

"""

import getpass
import logging
import logging.handlers
import platform
import sys
from queue import Empty
from typing import get_args

from pypts._version import __version__
from pypts.logger.levels import TRACE  # noqa: F401 - registers the TRACE level name
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.links import ANY_TO_LOGGER
from pypts.messages.to_logger_communication import (
    EndRunLog,
    LoggerControl,
    SetStdoutEnabled,
    StartRunLog,
    StopLogger,
    SwitchLogFile,
)
from pypts.utilities.common import ignore_keyboard_interrupt

DEFAULT_LOG_LEVEL = logging.INFO

#: The control messages that share the log queue with ordinary log records.
#: Used to steer/configure etc the Logger.
CONTROL_MESSAGES = get_args(LoggerControl)

# Log message format including timestamp with milliseconds, log level, originating
# process, source file, function and message.
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d;%(levelname)s;%(processName)s"
    ";%(filename)s:%(funcName)s;%(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The root logger, exported so modules can keep doing `from ... import log`.
log = logging.getLogger()

# Control channel towards the Logger process; set by init_logging().
# Stays None in standalone mode, where there is no Logger process to talk to.
_logger_control: QueueWrapper[LoggerControl] | None = None

# The run log this process writes to, as the launcher decided it; set by
# init_logging(). Stays None where nobody passed one - a standalone tool, a
# test, or any process the launcher did not hand the path to.
_log_file_path: str | None = None


def build_formatter() -> logging.Formatter:
    """
    Returns the formatter used for every pypts log destination.
    """
    return logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)


def parse_log_level(name, default: int = DEFAULT_LOG_LEVEL) -> int:
    """
    Turn a level name into a level number.
    """
    if not name:
        return default
    return logging.getLevelNamesMapping().get(str(name).strip().upper(), default)


def init_logging(log_queue=None, level=DEFAULT_LOG_LEVEL, log_file_path=None):
    """
    Configures logging for the *current* process. Call this once, first thing
    in every module entry point.

    Args:
      log_queue: the shared log queue created by the launcher. Records are sent
                 to the Logger process through it. If None, the process logs
                 straight to stdout instead - used by standalone tools and tests.
      level: minimum level captured by the root logger
      log_file_path: the run log the Logger is writing, so this process can read
                 it back through get_log_path(). Only the launcher knows it - it
                 is decided there, once per run - so a process that wants it has
                 to be handed it. Optional: nothing here opens the file, and a
                 process that never reads the log does not need to be told.

    Returns:
      The configured root logger.
    """
    global _logger_control, _log_file_path

    _log_file_path = log_file_path

    root = logging.getLogger()
    root.setLevel(level)

    # Drop handlers if any are registered already
    for handler in list(root.handlers):
        root.removeHandler(handler)

    if log_queue is not None:
        # Add the QueueHandler to the root logger - used for usage as process, not standalone.
        root.addHandler(logging.handlers.QueueHandler(log_queue))
        _logger_control = QueueWrapper(log_queue, link=ANY_TO_LOGGER)
    else:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(build_formatter())
        root.addHandler(stdout_handler)
        _logger_control = None

    return root


def get_log_path() -> str | None:
    """
    The run log file of this run, for a module that wants to read it back.

    The GUI tails it into its log panel. It is not a way to write to the log:
    the Logger process owns the only open handle and is the single writer, so a
    caller opens this path read-only or not at all.

    Returns:
      The path init_logging() was given, or None where it was given none.
    """
    return _log_file_path


def switch_log_file(log_file_path: str) -> bool:
    """
    Have the Logger carry on in a new run log, and read that one from now on.

    The switch is queued behind every record this process has already logged,
    so those land in the old file; get_log_path() names the new one at once,
    although the Logger may not have created it yet. Only this process learns
    the new path - any other that was handed the old one keeps it.

    Returns:
      False, and nothing changes, where there is no Logger process to switch -
      a standalone tool or a test.
    """
    global _log_file_path

    if _logger_control is None:
        return False
    _logger_control.send(SwitchLogFile(log_file_path))
    _log_file_path = log_file_path
    return True


def start_run_log(log_file_path: str) -> bool:
    """
    Have the Logger write the coming run into its own file, until end_run_log().

    Queued like switch_log_file(), so what this process logged before lands in
    the session log. Unlike it, get_log_path() keeps naming the session log:
    the run log is a detour, and the GUI's unload and log panel work from the
    session path.

    Returns:
      False, and nothing changes, where there is no Logger process.
    """
    if _logger_control is None:
        return False
    _logger_control.send(StartRunLog(log_file_path))
    return True


def end_run_log() -> bool:
    """
    Have the Logger close the run log and carry on in the session log.

    Returns:
      False, and nothing changes, where there is no Logger process.
    """
    if _logger_control is None:
        return False
    _logger_control.send(EndRunLog())
    return True


def describe_operator() -> str:
    """
    Who is running this, for the second line of the run log.

    getpass.getuser() reads the environment before it asks the system, and on a
    machine where none of the usual variables is set it raises rather than
    returning anything: OSError where there is no password database entry, and
    KeyError from the pwd lookup underneath it. A run log that cannot name its
    operator is still a perfectly good run log, so the failure is worth a word
    and nothing more.
    """
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "an unknown user"


def log_run_log_header(mode: str, log_file_path: str) -> None:
    """
    The first three lines of every run log: what this is, who ran it, and
    where the file they are reading lives (logging_rules.md section 6).

    Written by the launcher at startup, and again by the GUI at the top of the
    new file when an unload switches the run log. `stacklevel=2`, so each line
    names the caller as its source, not this helper.
    """
    log.info("PyPTS %s started in %s mode.", __version__, mode.upper(), stacklevel=2)
    log.info(
        "Started by %s on %s.",
        describe_operator(),
        platform.node() or "an unknown host",
        stacklevel=2,
    )
    log.info("Run log: %s", log_file_path, stacklevel=2)


def set_stdout_logging_enabled(enabled: bool):
    """
    Enables or disables echoing log records to the console
    """
    if _logger_control is not None:
        _logger_control.send(SetStdoutEnabled(bool(enabled)))
        return

    for handler in logging.getLogger().handlers:
        is_console = isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        )
        if is_console:
            # Raising the level above CRITICAL silences the handler so it does not pollute stdout.
            handler.setLevel(logging.NOTSET if enabled else logging.CRITICAL + 1)


def logger_main(log_queue, log_file_path: str, stdout_enabled: bool = True) -> None:
    """
    Entry point for the launcher. Responsible for instantiating the Logger singleton object
    and starting its execution.
    """
    # The Logger must outlive every module it writes for, so it is the process
    # that can least afford to die to a stray Ctrl+C: the records explaining the
    # shutdown are written after the rest of the application has stopped. The
    # launcher ends it with StopLogger, and only that.
    ignore_keyboard_interrupt()

    logger = Logger(log_queue, log_file_path, stdout_enabled)
    logger.start()


class Logger:
    """
    The single writer of the run log file.
    Owns the only FileHandler on the log file
    """

    def __init__(self, log_queue, log_file_path: str, stdout_enabled: bool = True):
        self.log_queue = log_queue
        self.log_file_path = log_file_path
        #: The session log while a run log is open (StartRunLog), else None.
        self.session_log_file_path: str | None = None
        self.stdout_enabled = stdout_enabled
        self.running = True

        formatter = build_formatter()

        # encoding is pinned so that a non-ASCII message does not raise
        # UnicodeEncodeError on a Windows machine with a non-UTF-8 locale.
        # On linux we could use emojiiiiisss
        self.file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        self.file_handler.setFormatter(formatter)

        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setFormatter(formatter)

    # --- Startup ---
    def start(self):
        """
        Starts Logger module execution by entering the main event loop.
        """
        self._report(f"Logging to file: {self.log_file_path}")
        self.main_loop()
        self.close()

    # --- Main event loop ---
    def main_loop(self):
        """
        Blocks on the shared queue and writes every record it receives.
        blocking get() costs nothing, therefore no polling and wait mechanism
        """
        while self.running:
            try:
                item = self.log_queue.get()
            except (EOFError, OSError):
                # The queue died - nothing left to serve.
                break
            except KeyboardInterrupt:
                # Belt and braces. logger_main() ignores SIGINT outright, so this
                # is unreachable by Ctrl+C; it stays because the rule it enforces
                # - the launcher decides when we stop, so keep writing until it
                # says otherwise - has to hold however the interrupt arrived.
                continue

            # Nothing shall take the Logger down
            try:
                self.handle_item(item)
            except Exception as exc:  # noqa: BLE001 - the logger must never die
                self._report(f"Failed to handle queue item: {exc!r}")

        self.drain()

    def handle_item(self, item):
        """
        Handles one queue item at a time: either a control message or a log record.

        This is the one queue in the framework carrying two kinds of item, so it
        is also the one place where "anything else" is a meaningful answer:
        whatever is not a control message is a logging.LogRecord put here by
        logging's own QueueHandler.
        """
        if isinstance(item, CONTROL_MESSAGES):
            self.handle_control_message(item)
        else:
            self.write_record(item)

    def handle_control_message(self, message: LoggerControl):
        """
        Handles the control messages that steer the Logger itself.
        Here we can implement more control messages if needed.
        """
        match message:
            case SetStdoutEnabled(enabled=enabled):
                self.stdout_enabled = enabled
            case SwitchLogFile(log_file_path=log_file_path):
                if self.session_log_file_path is not None:
                    # An unload landing while a run log is open moves the
                    # session, not the run: the end of the run goes there.
                    self.session_log_file_path = log_file_path
                else:
                    self.switch_file(log_file_path)
            case StartRunLog(log_file_path=log_file_path):
                self.start_run_log(log_file_path)
            case EndRunLog():
                self.end_run_log()
            case StopLogger():
                self.running = False
            case _:
                unhandled(message)  # unreachable; keeps mypy's exhaustiveness check live

    def start_run_log(self, log_file_path: str):
        """
        Remember the session log and carry on in the run log.

        A second StartRunLog without an EndRunLog keeps the first session path,
        so the end still returns to the session log rather than to a run log.
        """
        session = self.session_log_file_path
        if session is None:
            session = self.log_file_path
        self.switch_file(log_file_path)
        if self.log_file_path == log_file_path:
            self.session_log_file_path = session

    def end_run_log(self):
        """Back to the session log the run log started from, appending to it."""
        session = self.session_log_file_path
        if session is None:
            return
        self.switch_file(session)
        if self.log_file_path == session:
            self.session_log_file_path = None

    def switch_file(self, log_file_path: str):
        """
        Close the run log and carry on writing in `log_file_path`.

        The new file is opened before the old one is closed: if it cannot be
        opened, the Logger keeps writing where it was rather than nowhere.
        """
        try:
            new_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        except OSError as exc:
            self._report(f"Could not open the new log file {log_file_path}: {exc!r}")
            return
        new_handler.setFormatter(build_formatter())
        self.file_handler.close()
        self.file_handler = new_handler
        self.log_file_path = log_file_path
        self._report(f"Logging to file: {self.log_file_path}")

    def write_record(self, record):
        """
        Writes a single log record to the file and, if enabled, to the console.

        A failure here must never propagate: losing the Logger would leave the
        rest of the run blind. Failures are reported to the stderr.
        """
        try:
            self.file_handler.emit(record)
            if self.stdout_enabled:
                self.stdout_handler.emit(record)
        except Exception as exc:  # noqa: BLE001 - logging must not raise
            self._report(f"Failed to write log record: {exc!r}")

    def drain(self):
        """
        Writes whatever is still queued - used only after the stop command.
        """
        while True:
            try:
                item = self.log_queue.get(timeout=0.2)
            except (Empty, EOFError, OSError):
                return
            # A late StopLogger from another module must not cut the drain short.
            if isinstance(item, CONTROL_MESSAGES):
                continue
            self.write_record(item)

    def close(self):
        """
        Releases the log file.
        """
        self.file_handler.close()

    def _report(self, message: str):
        """
        Logger-internal diagnostics.
        """
        print(f"[logger] {message}", file=sys.stderr, flush=True)
