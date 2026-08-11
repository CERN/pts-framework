# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Logger module (src/pypts/logger/).

The Logger is a dedicated process and the *single writer* of the run log file.
Every other process and thread pushes logging.LogRecord objects onto a shared
queue through logging's QueueHandler; the Logger drains that queue and writes.

These tests exist because the obvious alternative - every process opening the
same file in append mode - silently loses records on Windows, where the C
runtime emulates append as "seek to end, then write" rather than as one atomic
operation. Measured on this project before the change: 0.5% to 15% of records
lost per run, plus a filename race that split 6 runs out of 10 across two files.
So the properties worth pinning down are: one file, every record present, no
record torn, and no side effect at import time.

The suite is split in two halves:

  * cheap in-process tests, which check how init_logging() configures the root
    logger of whichever process calls it, and
  * real multi-process tests, which spawn workers and a Logger process and
    assert on the file that actually lands on disk.

The second half is the one that would have caught the original bug, so the
worker functions live at module level: on Windows multiprocessing uses `spawn`,
which pickles the target by reference and re-imports this module in the child.
Locals and lambdas cannot cross that boundary.
"""

import logging
import logging.handlers
import multiprocessing as mp
import queue as queue_module
import re
import subprocess
import sys

import pytest

from pypts.logger import log as log_module
from pypts.logger.log import (
    Logger,
    init_logging,
    log,
    logger_main,
    set_stdout_logging_enabled,
)
from pypts.messages import Channel
from pypts.messages.logger_link import SetStdoutEnabled, StopLogger

# Matches one line written by the Logger, i.e. the LOG_FORMAT in log.py:
#   2026-08-11 09:37:00.958;INFO;Core;core.py:start;Starting module...
LOG_LINE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3});"
    r"(?P<level>[A-Z]+);"
    r"(?P<process>[^;]*);"
    r"(?P<location>[^;]*);"
    r"(?P<message>.*)$"
)

WORKER_COUNT = 4
RECORDS_PER_WORKER = 50


# --------------------------------------------------------------------------
# Helpers running in spawned child processes.
# Must be importable by name - see the module docstring.
# --------------------------------------------------------------------------

def _burst_worker(log_queue, count):
    """Emit `count` records tagged with this worker's process name."""
    init_logging(log_queue)
    name = mp.current_process().name
    for index in range(count):
        log.info(f"{name}|{index}")


def _origin_worker(log_queue):
    """Emit a single record, so the test can inspect where it claims to come from."""
    init_logging(log_queue)
    log.info("origin probe")


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def pristine_root_logger():
    """Restore the root logger after a test reconfigures it.

    init_logging() deliberately clears the root logger's handlers, which would
    otherwise tear down pytest's own capturing for every later test.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_control = log_module._logger_control

    yield root

    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)
    log_module._logger_control = saved_control


@pytest.fixture
def running_logger(tmp_path):
    """A live Logger process plus the queue that feeds it and the file it owns.

    Yields (log_queue, log_file, process). Tests normally call stop_logger()
    themselves, because the file must not be read until the Logger has drained
    and closed it; the teardown here is only a safety net.
    """
    log_file = tmp_path / "run.log"
    log_queue = mp.Queue()
    process = mp.Process(
        target=logger_main,
        name="Logger",
        args=(log_queue, str(log_file), False),
    )
    process.start()

    yield log_queue, log_file, process

    if process.is_alive():
        Channel(log_queue).send(StopLogger())
        process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def stop_logger(log_queue, process, timeout=20):
    """Ask the Logger to stop and wait until it has drained and closed the file."""
    Channel(log_queue).send(StopLogger())
    process.join(timeout=timeout)
    assert not process.is_alive(), "Logger did not stop within the timeout"


def parse_log(log_file):
    """Return the parsed lines of a log file, asserting that none is malformed.

    A torn line is the signature of more than one writer, so this doubles as the
    corruption check for every test that reads the file.
    """
    text = log_file.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line]

    parsed = []
    malformed = []
    for line in lines:
        match = LOG_LINE.match(line)
        if match:
            parsed.append(match.groupdict())
        else:
            malformed.append(line)

    assert not malformed, f"{len(malformed)} malformed line(s), e.g. {malformed[:2]}"
    return parsed


# --------------------------------------------------------------------------
# How a process configures itself
# --------------------------------------------------------------------------

def test_no_handlers_are_installed_at_import_time():
    """Importing the module must not configure logging or touch the filesystem.

    This is the property that makes the design work under `spawn`: every child
    process re-imports pypts.logger.log, so an import-time side effect would be
    repeated once per process. The previous implementation opened a timestamped
    log file and printed to stdout at import, which is exactly how one run ended
    up split across several files.

    Checked in a fresh interpreter, because the pytest process has handlers of
    its own and could not tell the difference.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging, pypts.logger.log; print(len(logging.getLogger().handlers))",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    # Exactly "0" and nothing else: no handlers, and no stray print either.
    assert result.stdout.strip() == "0", f"unexpected stdout: {result.stdout!r}"


def test_init_logging_installs_exactly_one_queue_handler(pristine_root_logger):
    """In queue mode the root logger gets a QueueHandler bound to the shared queue.

    "Exactly one" matters: a second destination would mean the process writes
    somewhere the Logger does not control, which is how the single-writer
    guarantee gets lost.
    """
    log_queue = queue_module.Queue()

    root = init_logging(log_queue)

    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert isinstance(handler, logging.handlers.QueueHandler)
    assert handler.queue is log_queue
    assert root.level == logging.DEBUG


def test_init_logging_is_idempotent(pristine_root_logger):
    """Calling it twice must not duplicate handlers, and so must not duplicate records.

    Every module entry point calls init_logging(), and a process can host more
    than one of them, so this is a realistic mistake rather than a theoretical one.
    """
    log_queue = queue_module.Queue()

    init_logging(log_queue)
    root = init_logging(log_queue)

    assert len(root.handlers) == 1

    log.info("only once")

    assert log_queue.qsize() == 1


def test_init_logging_without_queue_falls_back_to_stdout(pristine_root_logger):
    """Standalone mode, for helper applications and drivers used outside the framework.

    There is no Logger process to talk to, so the process logs to stdout itself
    and no control interface is created.
    """
    root = init_logging()

    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)
    assert handler.stream is sys.stdout
    assert log_module._logger_control is None


def test_exception_tracebacks_survive_the_queue(pristine_root_logger):
    """A traceback must reach the file even though exc_info cannot be pickled.

    QueueHandler.prepare() formats the record first, folding the traceback into
    the message text, and then clears exc_info. Both halves are asserted here:
    the text is present, and the unpicklable attribute is gone.
    """
    log_queue = queue_module.Queue()
    init_logging(log_queue)

    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("step failed")

    record = log_queue.get_nowait()

    assert "step failed" in record.msg
    assert "Traceback (most recent call last)" in record.msg
    assert "ValueError: boom" in record.msg
    # Cleared by prepare(), which is what makes the record safe to pickle.
    assert record.exc_info is None
    assert record.exc_text is None


# --------------------------------------------------------------------------
# Control messages
# --------------------------------------------------------------------------

def test_set_stdout_enabled_applies_across_processes(pristine_root_logger, tmp_path):
    """Toggling the console echo is a message, which is why it crosses processes.

    The Logger owns the only console handler, so the switch cannot be a local
    variable - the previous implementation flipped a module global, which had no
    effect in any other process and left child output printing over the CLI
    prompt. The two halves of the mechanism are checked together: the caller
    emits the control event, and the Logger honours it.
    """
    log_queue = queue_module.Queue()
    init_logging(log_queue)

    set_stdout_logging_enabled(False)

    message = log_queue.get_nowait()
    assert isinstance(message, SetStdoutEnabled)
    assert message.enabled is False

    # ... and the receiving end acts on it.
    logger = Logger(log_queue, str(tmp_path / "run.log"), stdout_enabled=True)
    try:
        logger.handle_control_message(message)
        assert logger.stdout_enabled is False

        logger.handle_control_message(SetStdoutEnabled(True))
        assert logger.stdout_enabled is True
    finally:
        logger.close()


def test_logger_survives_a_failing_record(tmp_path, capsys):
    """A write failure must never kill the Logger - the whole run would go blind.

    The failure is reported on stderr rather than through logging, because this
    process is the thing that serves logging.
    """
    log_file = tmp_path / "run.log"
    logger = Logger(mp.Queue(), str(log_file), stdout_enabled=False)

    def explode(_record):
        raise OSError("disk on fire")

    working_emit = logger.file_handler.emit
    logger.file_handler.emit = explode

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="doomed", args=None, exc_info=None,
    )

    try:
        logger.write_record(record)  # must not raise
        assert "[logger]" in capsys.readouterr().err

        # Still usable afterwards.
        logger.file_handler.emit = working_emit
        logger.write_record(record)
    finally:
        logger.close()

    assert "doomed" in log_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The real thing: several processes, one file
# --------------------------------------------------------------------------

def test_records_from_several_processes_land_in_one_file(running_logger):
    """The central guarantee: N processes, one file, every record intact.

    Each worker emits a numbered burst tagged with its own process name, so the
    result can be checked exactly rather than approximately - every (worker,
    index) pair must appear exactly once. Loss and duplication both fail here,
    and parse_log() fails on any torn line.
    """
    log_queue, log_file, process = running_logger

    workers = [
        mp.Process(
            target=_burst_worker,
            name=f"Worker-{index}",
            args=(log_queue, RECORDS_PER_WORKER),
        )
        for index in range(WORKER_COUNT)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
        assert worker.exitcode == 0, f"{worker.name} exited with {worker.exitcode}"

    stop_logger(log_queue, process)

    entries = parse_log(log_file)
    delivered = {entry["message"] for entry in entries}
    expected = {
        f"Worker-{index}|{record}"
        for index in range(WORKER_COUNT)
        for record in range(RECORDS_PER_WORKER)
    }

    assert delivered >= expected, f"{len(expected - delivered)} record(s) lost"
    assert len(entries) == len(expected), "a record was written more than once"


def test_record_origin_is_preserved_across_the_process_boundary(running_logger):
    """The record must still describe where it came from, not where it was written.

    Everything the format needs - originating process name, source file,
    function and the original timestamp - is computed in the emitting process
    and has to survive pickling. If the Logger re-derived any of it, every line
    in the file would claim to come from the Logger itself.
    """
    log_queue, log_file, process = running_logger

    worker = mp.Process(target=_origin_worker, name="Sequencer", args=(log_queue,))
    worker.start()
    worker.join(timeout=60)
    assert worker.exitcode == 0

    stop_logger(log_queue, process)

    entries = parse_log(log_file)
    probe = [entry for entry in entries if entry["message"] == "origin probe"]
    assert len(probe) == 1

    entry = probe[0]
    assert entry["process"] == "Sequencer"
    assert entry["location"] == "test_logger.py:_origin_worker"
    assert entry["level"] == "INFO"


def test_logger_drains_pending_records_on_stop(tmp_path):
    """Records still in flight when STOP arrives must not be dropped.

    The launcher stops the Logger last, but a module may have put a record on
    the queue just before exiting. Ordering it deliberately - STOP first, then a
    record - proves the drain runs rather than the queue merely being empty by
    the time the loop ends.
    """
    log_file = tmp_path / "run.log"
    log_queue = mp.Queue()

    log_queue.put(StopLogger())
    log_queue.put(
        logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="trailing record", args=None, exc_info=None,
        )
    )

    process = mp.Process(target=logger_main, name="Logger", args=(log_queue, str(log_file), False))
    process.start()
    process.join(timeout=30)
    assert not process.is_alive(), "Logger did not stop after the STOP command"
    assert process.exitcode == 0

    entries = parse_log(log_file)
    assert [entry["message"] for entry in entries] == ["trailing record"]
