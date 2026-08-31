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

import logging
<<<<<<< HEAD
import os
=======
import logging.handlers
>>>>>>> 04a05cd756975e2dc007fe919cc630e4191643db
import sys
from queue import Empty
from typing import get_args

<<<<<<< HEAD
# Env var used to propagate the chosen log file path to all child processes
# (multiprocessing spawn re-imports this module, so without a shared path each
# subprocess would create its own timestamped log file).
LOG_FILE_ENV_VAR = "PYPTS_LOG_FILE"


class NullStream:
    """A stream object that ignores all writes. Used to disable stdout logging."""
    def write(self, msg):
        pass
    def flush(self):
        pass


_formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger()
log.setLevel(logging.DEBUG)

for _hdlr in list(log.handlers):
    log.removeHandler(_hdlr)

_log_file_path = os.environ.get(LOG_FILE_ENV_VAR)
if _log_file_path is None:
    _log_file_path = get_log_file_path()
    os.environ[LOG_FILE_ENV_VAR] = _log_file_path

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_formatter)
log.addHandler(_stream_handler)

_file_handler = logging.FileHandler(_log_file_path, encoding="utf-8")
_file_handler.setFormatter(_formatter)
log.addHandler(_file_handler)


def set_stdout_logging_enabled(enabled: bool) -> None:
    """Enable or disable logging to stdout by redirecting the stream handler."""
    _stream_handler.stream = sys.stdout if enabled else NullStream()


def info(msg, *args, **kwargs): log.info(msg, *args, **kwargs)
def debug(msg, *args, **kwargs): log.debug(msg, *args, **kwargs)
def warning(msg, *args, **kwargs): log.warning(msg, *args, **kwargs)
def error(msg, *args, **kwargs): log.error(msg, *args, **kwargs)
def critical(msg, *args, **kwargs): log.critical(msg, *args, **kwargs)
=======
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.links import ANY_TO_LOGGER
from pypts.messages.to_logger_communication import LoggerControl, SetStdoutEnabled, StopLogger

DEFAULT_LOG_LEVEL = logging.INFO

#: The control messages that share the log queue with ordinary log records.
#: Used to steer/configure etc the Logger.
CONTROL_MESSAGES = get_args(LoggerControl)

# Log message format including timestamp with milliseconds, log level, originating
# process, source file, function and message.
LOG_FORMAT = "%(asctime)s.%(msecs)03d;%(levelname)s;%(processName)s;%(filename)s:%(funcName)s;%(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The root logger, exported so modules can keep doing `from ... import log`.
log = logging.getLogger()

# Control channel towards the Logger process; set by init_logging().
# Stays None in standalone mode, where there is no Logger process to talk to.
_logger_control: QueueWrapper[LoggerControl] | None = None


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


def init_logging(log_queue=None, level=DEFAULT_LOG_LEVEL):
    """
    Configures logging for the *current* process. Call this once, first thing
    in every module entry point.

    Args:
      log_queue: the shared log queue created by the launcher. Records are sent
                 to the Logger process through it. If None, the process logs
                 straight to stdout instead - used by standalone tools and tests.
      level: minimum level captured by the root logger

    Returns:
      The configured root logger.
    """
    global _logger_control

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
        Styarts Logger module execution by entering the main event loop, so we can communicate via queue.
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
                # Ctrl+C reaches every process in the group; the launcher decides
                # when we stop, so keep writing until it says otherwise.
                continue

            # Nothing shall take the Logger down
            try:
                self.handle_item(item)
            except Exception as exc:
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
            case StopLogger():
                self.running = False
            case _:
                unhandled(message)

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
>>>>>>> 04a05cd756975e2dc007fe919cc630e4191643db
