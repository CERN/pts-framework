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
from pypts.logger.levels import TRACE
from pypts.logger.log import (
    DEFAULT_LOG_LEVEL,
    Logger,
    init_logging,
    log,
    logger_main,
    parse_log_level,
    set_stdout_logging_enabled,
)
from pypts.messages import QueueWrapper
from pypts.messages.to_logger_communication import SetStdoutEnabled, StopLogger

# Matches one line written by the Logger, i.e. the LOG_FORMAT in log.py:
#   2026-08-11 09:37:00.958;INFO;Core;core.py:start;Starting module.
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
        log.info("%s|%s", name, index)


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
    saved_path = log_module._log_file_path

    yield root

    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)
    log_module._logger_control = saved_control
    log_module._log_file_path = saved_path


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
        QueueWrapper(log_queue).send(StopLogger())
        process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def stop_logger(log_queue, process, timeout=20):
    """Ask the Logger to stop and wait until it has drained and closed the file."""
    QueueWrapper(log_queue).send(StopLogger())
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
    # INFO, not DEBUG: DEBUG is developer detail, and TRACE the full message
    # trace - things to ask for rather than get from a caller that said nothing.
    assert root.level == DEFAULT_LOG_LEVEL == logging.INFO


def test_parse_log_level_reads_a_name_in_any_case():
    assert parse_log_level("debug") == logging.DEBUG
    assert parse_log_level(" WARNING ") == logging.WARNING


def test_parse_log_level_falls_back_instead_of_raising():
    """
    A level name arrives from a command line or from a config file in the temp
    directory. Neither is worth refusing to start over, and the caller has
    nowhere to report a traceback yet - logging is what is being set up.
    """
    assert parse_log_level("NONSENSE") == DEFAULT_LOG_LEVEL
    assert parse_log_level(None) == DEFAULT_LOG_LEVEL
    assert parse_log_level("") == DEFAULT_LOG_LEVEL
    assert parse_log_level("NONSENSE", logging.ERROR) == logging.ERROR


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


# --------------------------------------------------------------------------
# get_log_path
# --------------------------------------------------------------------------


def test_get_log_path_returns_what_init_logging_was_told(pristine_root_logger, tmp_path):
    """The run log is remembered per process, for whoever wants to read it back.

    Only the launcher decides the path, so a process that needs it - the GUI,
    for its log panel - is handed it and asks the logger module for it later.
    """
    log_file = tmp_path / "run.log"

    init_logging(None, logging.INFO, str(log_file))

    assert log_module.get_log_path() == str(log_file)


def test_get_log_path_is_none_when_no_log_file_was_given(pristine_root_logger):
    """A standalone tool or a test logs to stdout and has no file to point at."""
    init_logging()

    assert log_module.get_log_path() is None


# --------------------------------------------------------------------------
# Switching to a new run log (the operator unloaded the recipe)
# --------------------------------------------------------------------------


def _record(message):
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=message, args=None, exc_info=None,
    )


def test_switch_log_file_cuts_the_log_between_two_records(tmp_path):
    """Before the switch goes to the old file, after it to the new one - and
    the old file is not touched again."""
    from pypts.messages.to_logger_communication import SwitchLogFile

    old_file = tmp_path / "pypts_old.log"
    new_file = tmp_path / "pypts_new.log"
    logger = Logger(queue_module.Queue(), str(old_file), stdout_enabled=False)

    logger.handle_item(_record("before"))
    logger.handle_item(SwitchLogFile(log_file_path=str(new_file)))
    logger.handle_item(_record("after"))
    logger.close()

    assert [entry["message"] for entry in parse_log(old_file)] == ["before"]
    assert [entry["message"] for entry in parse_log(new_file)] == ["after"]
    assert logger.log_file_path == str(new_file)


def test_a_switch_to_a_file_that_cannot_be_opened_keeps_the_old_one(tmp_path):
    from pypts.messages.to_logger_communication import SwitchLogFile

    old_file = tmp_path / "pypts_old.log"
    logger = Logger(queue_module.Queue(), str(old_file), stdout_enabled=False)

    logger.handle_item(SwitchLogFile(log_file_path=str(tmp_path / "missing" / "new.log")))
    logger.handle_item(_record("still here"))
    logger.close()

    assert [entry["message"] for entry in parse_log(old_file)] == ["still here"]
    assert logger.log_file_path == str(old_file)


def test_switch_log_file_queues_the_switch_and_names_the_new_path(
    pristine_root_logger, tmp_path
):
    from pypts.messages.to_logger_communication import SwitchLogFile

    log_queue = queue_module.Queue()
    init_logging(log_queue, logging.INFO, str(tmp_path / "pypts_old.log"))
    new_path = str(tmp_path / "pypts_new.log")

    assert log_module.switch_log_file(new_path) is True

    assert log_module.get_log_path() == new_path
    assert log_queue.get_nowait() == SwitchLogFile(log_file_path=new_path)


def test_switch_log_file_does_nothing_without_a_logger_process(pristine_root_logger):
    init_logging()

    assert log_module.switch_log_file("anything.log") is False
    assert log_module.get_log_path() is None


def test_the_run_log_header_is_three_info_lines_from_the_caller(caplog):
    from pypts._version import __version__

    with caplog.at_level(logging.INFO):
        log_module.log_run_log_header("gui", "C:/logs/pypts_1.log")

    assert caplog.messages[0] == f"PyPTS {__version__} started in GUI mode."
    assert caplog.messages[1].startswith("Started by ")
    assert caplog.messages[2] == "Run log: C:/logs/pypts_1.log"
    # stacklevel=2: the lines name whoever wrote the header, not the helper.
    assert {record.funcName for record in caplog.records} == {
        "test_the_run_log_header_is_three_info_lines_from_the_caller"
    }


def test_trace_is_a_level_below_debug_with_its_own_name():
    """The message trace has a level of its own, under DEBUG."""
    assert TRACE < logging.DEBUG
    assert logging.getLevelName(TRACE) == "TRACE"
    assert parse_log_level("TRACE") == TRACE
    assert parse_log_level("trace") == TRACE


# --------------------------------------------------------------------------
# A run log: one run's lines in its own file, then back to the session log
# --------------------------------------------------------------------------


def test_a_run_log_takes_the_run_and_the_session_log_carries_on_after_it(tmp_path):
    from pypts.messages.to_logger_communication import EndRunLog, StartRunLog

    session_file = tmp_path / "pypts_session.log"
    run_file = tmp_path / "run" / "pypts_run.log"
    run_file.parent.mkdir()
    logger = Logger(queue_module.Queue(), str(session_file), stdout_enabled=False)

    logger.handle_item(_record("before"))
    logger.handle_item(StartRunLog(log_file_path=str(run_file)))
    logger.handle_item(_record("during"))
    logger.handle_item(EndRunLog())
    logger.handle_item(_record("after"))
    logger.close()

    assert [entry["message"] for entry in parse_log(session_file)] == ["before", "after"]
    assert [entry["message"] for entry in parse_log(run_file)] == ["during"]
    assert logger.log_file_path == str(session_file)


def test_a_run_log_returns_to_the_session_log_an_unload_switched_to(tmp_path):
    """The Logger, not the sender, knows which file the session is in now."""
    from pypts.messages.to_logger_communication import EndRunLog, StartRunLog, SwitchLogFile

    first = tmp_path / "pypts_first.log"
    second = tmp_path / "pypts_second.log"
    run_file = tmp_path / "pypts_run.log"
    logger = Logger(queue_module.Queue(), str(first), stdout_enabled=False)

    logger.handle_item(SwitchLogFile(log_file_path=str(second)))
    logger.handle_item(StartRunLog(log_file_path=str(run_file)))
    logger.handle_item(EndRunLog())
    logger.handle_item(_record("after the run"))
    logger.close()

    assert [entry["message"] for entry in parse_log(second)] == ["after the run"]
    assert parse_log(first) == []


def test_ending_a_run_log_that_was_never_started_changes_nothing(tmp_path):
    from pypts.messages.to_logger_communication import EndRunLog

    session_file = tmp_path / "pypts_session.log"
    logger = Logger(queue_module.Queue(), str(session_file), stdout_enabled=False)

    logger.handle_item(EndRunLog())
    logger.handle_item(_record("still here"))
    logger.close()

    assert [entry["message"] for entry in parse_log(session_file)] == ["still here"]
    assert logger.log_file_path == str(session_file)


def test_start_and_end_run_log_queue_the_requests_and_keep_the_session_path(
    pristine_root_logger, tmp_path
):
    """get_log_path() keeps naming the session log: the GUI's unload relies on it."""
    from pypts.messages.to_logger_communication import EndRunLog, StartRunLog

    log_queue = queue_module.Queue()
    session_path = str(tmp_path / "pypts_session.log")
    init_logging(log_queue, logging.INFO, session_path)
    run_path = str(tmp_path / "pypts_run.log")

    assert log_module.start_run_log(run_path) is True
    assert log_module.end_run_log() is True

    assert log_queue.get_nowait() == StartRunLog(log_file_path=run_path)
    assert log_queue.get_nowait() == EndRunLog()
    assert log_module.get_log_path() == session_path


def test_start_and_end_run_log_do_nothing_without_a_logger_process(pristine_root_logger):
    init_logging()

    assert log_module.start_run_log("anything.log") is False
    assert log_module.end_run_log() is False


def test_an_unload_during_a_run_log_becomes_the_session_log_to_return_to(tmp_path):
    """A SwitchLogFile while a run log is open moves the session, not the run."""
    from pypts.messages.to_logger_communication import EndRunLog, StartRunLog, SwitchLogFile

    first = tmp_path / "pypts_first.log"
    second = tmp_path / "pypts_second.log"
    run_file = tmp_path / "pypts_run.log"
    logger = Logger(queue_module.Queue(), str(first), stdout_enabled=False)

    logger.handle_item(StartRunLog(log_file_path=str(run_file)))
    logger.handle_item(SwitchLogFile(log_file_path=str(second)))
    logger.handle_item(_record("still the run"))
    logger.handle_item(EndRunLog())
    logger.handle_item(_record("after the run"))
    logger.close()

    assert [entry["message"] for entry in parse_log(run_file)] == ["still the run"]
    assert [entry["message"] for entry in parse_log(second)] == ["after the run"]
