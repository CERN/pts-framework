# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Central logging for pypts.

One dedicated process - the Logger - owns the only open handle on the run log
file and is therefore the single writer. Every other process and thread pushes
logging.LogRecord objects onto a shared queue (through logging's QueueHandler);
the Logger drains that queue and writes the records out.

Why a single writer, rather than every process appending to the same file:

  - On Windows the C runtime emulates append mode as "seek to end, then write".
    Those are two separate operations, so two processes can seek to the same
    offset and one silently overwrites the other's record. Measured on this
    project: 0.5% to 15% of records lost per run, on every trial.
  - On Linux O_APPEND is atomic, so records are not lost, but a record larger
    than the stream buffer is split across several write() calls and can still
    be interleaved with another process's record.

Routing every record through one writer removes both failure modes on every
platform, and it also means the log file name is decided exactly once (by the
launcher) instead of being re-derived from the clock in each process.

Usage:
  - The launcher creates the queue, decides the log file path once, and starts
    the Logger process via logger_main(). It stops the Logger last, so that
    records emitted while the other modules shut down are not lost.
  - Every other process calls init_logging(log_queue) as the first thing in its
    entry point, then uses the module level `log` object exactly as before.
  - Standalone tools (helper applications, drivers used outside the framework)
    call init_logging() with no argument and get plain stdout logging.

Nothing here is configured at import time: a module that is merely imported
must not open files or install handlers, otherwise every spawned process
repeats the side effect.
"""

import logging
import logging.handlers
import sys
from queue import Empty
from typing import get_args

from pypts.messages import QueueWrapper, unhandled
from pypts.messages.links import ANY_TO_LOGGER
from pypts.messages.to_logger_communication import LoggerControl, SetStdoutEnabled, StopLogger

#: The level every process runs at unless the launcher says otherwise.
#:
#: INFO, not DEBUG, because DEBUG now means the full message trace: every
#: QueueWrapper logs each message twice, once on the send and once on the
#: receive (see messages/queue_wrapper.py). That is the right thing to ask for
#: deliberately and the wrong thing to get by default.
DEFAULT_LOG_LEVEL = logging.INFO

#: The control messages that share the log queue with ordinary log records.
#: Derived from the union so that adding a control message cannot leave the
#: two isinstance() checks below out of date.
CONTROL_MESSAGES = get_args(LoggerControl)

# Log message format including timestamp with milliseconds, log level, originating
# process, source file, function and message.
#
# Left as one over-long literal on purpose: the Debug Monitor's trace_parser.py
# mirrors this format field for field, and splitting it across lines would make
# the two harder to compare than the long line is to read.
LOG_FORMAT = "%(asctime)s.%(msecs)03d;%(levelname)s;%(processName)s;%(filename)s:%(funcName)s;%(message)s"  # noqa: E501
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

    Deliberately total: an unknown name, an empty string or None all return
    `default` rather than raising. The name comes from a command line or from a
    config file in the temp directory, and neither is worth refusing to start
    over - the caller logs a warning once logging is up, which is more useful
    than a traceback before there is anywhere to write it.

    Args:
      name: a level name such as "DEBUG", in any case. None is accepted so that
            the caller can pass an absent argument straight through.
      default: what to return when `name` names no level.
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
      level: minimum level captured by the root logger. The launcher resolves
             it once from --log-level and the config, and passes the same value
             to every process, so one run is captured at one level throughout.
             DEBUG additionally turns on the message trace.

    Returns:
      The configured root logger.
    """
    global _logger_control

    root = logging.getLogger()
    root.setLevel(level)

    # Drop handlers inherited from a parent process (fork) or from a previous
    # init_logging() call, so a process never ends up with two destinations.
    # The handlers are not closed: under fork they may wrap a descriptor that
    # the parent process is still using.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    if log_queue is not None:
        # QueueHandler.prepare() formats the record and folds any traceback into
        # the message, so what crosses the process boundary is always picklable.
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
    Enables or disables echoing log records to the console, for the whole
    application. The Logger process owns the console handler, so this is a
    control message rather than a local change - which is why it now works
    across process boundaries.

    In standalone mode (no Logger process) it mutes the local stdout handler.
    """
    if _logger_control is not None:
        _logger_control.send(SetStdoutEnabled(bool(enabled)))
        return

    for handler in logging.getLogger().handlers:
        is_console = isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        )
        if is_console:
            # Raising the level above CRITICAL silences the handler without
            # removing it, so it can be switched back on later.
            handler.setLevel(logging.NOTSET if enabled else logging.CRITICAL + 1)


def logger_main(log_queue, log_file_path: str, stdout_enabled: bool = True) -> None:
    """
    Entry point for the launcher. Responsible for instantiating the Logger class
    and starting its execution.
    """
    logger = Logger(log_queue, log_file_path, stdout_enabled)
    logger.start()


class Logger:
    """
    The single writer of the run log file.

    Owns the only FileHandler on the log file and, optionally, the console
    handler. It deliberately does not install a QueueHandler on its own root
    logger - that would feed its own records back into its own queue.
    """

    def __init__(self, log_queue, log_file_path: str, stdout_enabled: bool = True):
        self.log_queue = log_queue
        self.log_file_path = log_file_path
        self.stdout_enabled = stdout_enabled
        self.running = True

        formatter = build_formatter()

        # encoding is pinned so that a non-ASCII message does not raise
        # UnicodeEncodeError on a Windows machine with a non-UTF-8 locale.
        self.file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        self.file_handler.setFormatter(formatter)

        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setFormatter(formatter)

    # --- Startup ---
    def start(self):
        """
        Begins Logger module execution by entering the main event loop.
        """
        self._report(f"Logging to file: {self.log_file_path}")
        self.main_loop()
        self.close()

    # --- Main event loop ---
    def main_loop(self):
        """
        Blocks on the shared queue and writes every record it receives.

        Unlike the other modules this loop does not poll: a blocking get() costs
        nothing while idle and there is no second source to service.
        """
        while self.running:
            try:
                item = self.log_queue.get()
            except (EOFError, OSError):
                # The queue died with its owning process - nothing left to serve.
                break
            except KeyboardInterrupt:
                # Ctrl+C reaches every process in the group; the launcher decides
                # when we stop, so keep writing until it says otherwise.
                continue

            # Nothing a single queue item does may take the Logger down: losing
            # it leaves the rest of the run blind, and it cannot report its own
            # failures through logging because it is the thing serving logging.
            try:
                self.handle_item(item)
            except Exception as exc:  # noqa: BLE001 - logging must not raise
                self._report(f"Failed to handle queue item: {exc!r}")

        self.drain()

    def handle_item(self, item):
        """
        Routes one queue item: either a control message or a log record.

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
        rest of the run blind. Failures are reported on stderr instead.
        """
        try:
            self.file_handler.emit(record)
            if self.stdout_enabled:
                self.stdout_handler.emit(record)
        except Exception as exc:  # noqa: BLE001 - logging must not raise
            self._report(f"Failed to write log record: {exc!r}")

    def drain(self):
        """
        Writes whatever is still queued after the stop command.

        The launcher stops the Logger last, but records put by a module just
        before it exited may still be in flight, so give the queue a moment to
        deliver them.
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
        Releases the log file. After this the run log is complete and closed.
        """
        self.file_handler.close()

    def _report(self, message: str):
        """
        Logger-internal diagnostics. These cannot go through the logging module,
        because this process is the thing that serves it.
        """
        print(f"[logger] {message}", file=sys.stderr, flush=True)
