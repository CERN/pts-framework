# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Debug Monitor (src/pypts/helper_applications/debug_monitor/).

The Monitor reads the run log and nothing else. It is not part of the framework
and the framework does not know it exists, so everything worth testing here is a
pure function over text: a line of the run log in, a TraceEvent or a module
state out.

That is the whole reason the parser and the liveness fold are Qt-free modules of
their own. A GUI is not needed to prove that `recv sequencer->core Heartbeat(...)`
means the Sequencer was alive at that moment, and a running framework is not
needed either.

The sample lines below are embedded rather than kept as a .log fixture on
purpose: `reuse.toml` blanket-covers `tests/**/*.py` but not a `.log`, so a
fixture file would need its own licensing entry for no benefit. They are copied
from a real run, including the awkward ones - a traceback that spans lines, a
payload containing the field separator, and a QueueWrapper with no link name.
"""

import os
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from pypts.helper_applications.debug_monitor.liveness import (
    ALIVE,
    DEAD,
    STOPPED,
    UNKNOWN,
    LivenessTracker,
)
from pypts.helper_applications.debug_monitor.log_source import (
    LogFollower,
    find_latest_log,
)
from pypts.helper_applications.debug_monitor.trace_parser import (
    LogLine,
    as_trace_event,
    parse_line,
)
from pypts.utilities.heartbeat_manager import HEARTBEAT_TIMEOUT_S

# --------------------------------------------------------------------------
# Sample log text
# --------------------------------------------------------------------------

SEND_LINE = "2026-08-12 09:32:58.056;DEBUG;Core;queue_wrapper.py:send;send core->sequencer StopSequencer()"
RECV_LINE = (
    "2026-08-12 09:32:58.101;DEBUG;Sequencer;queue_wrapper.py:receive;recv core->sequencer StopSequencer()"
)
INFO_LINE = "2026-08-12 09:32:58.120;INFO;Core;core.py:start;Starting module."
UNNAMED_LINE = "2026-08-12 09:32:58.140;DEBUG;Core;queue_wrapper.py:send;send ? StatusChanged(text='ready')"
SEPARATOR_LINE = (
    "2026-08-12 09:32:58.150;DEBUG;Core;queue_wrapper.py:send;send core->hmi "
    "StatusChanged(text='ready; steady; go')"
)
NESTED_LINE = (
    "2026-08-12 09:32:58.160;DEBUG;Core;queue_wrapper.py:receive;recv sequencer->core "
    "StepFinished(outcome=StepOutcome(step_name='Power on', result=PASS))"
)
OTHER_DEBUG_LINE = "2026-08-12 09:32:58.170;DEBUG;Core;core.py:poll;Something else entirely"
EXCEPTION_LINE = "2026-08-12 09:32:59.000;ERROR;Core;core.py:poll;Failure while handling a message"
TRACEBACK_LINE = "Traceback (most recent call last):"
TRACEBACK_LINE_2 = '  File "core.py", line 210, in poll'


def heartbeat_line(timestamp: str, source: str) -> str:
    """One heartbeat trace line, as CORE's inbox records it."""
    return (
        f"2026-08-12 {timestamp};DEBUG;Core;queue_wrapper.py:receive;"
        f"recv {source}->core Heartbeat(source='{source}', timestamp=1786000000.0)"
    )


# --------------------------------------------------------------------------
# parse_line() - the run log's grammar
# --------------------------------------------------------------------------


def test_a_record_is_split_into_its_five_fields():
    """
    The five fields of LOG_FORMAT, in order. If this breaks, LOG_FORMAT in
    logger/log.py changed and the Monitor has to follow it.
    """
    line = parse_line(SEND_LINE)

    # Naive, like every timestamp in the run log - see trace_parser.parse_line().
    assert line.timestamp == datetime(2026, 8, 12, 9, 32, 58, 56000)  # noqa: DTZ001
    assert line.level == "DEBUG"
    assert line.process == "Core"
    assert line.location == "queue_wrapper.py:send"
    assert line.message == "send core->sequencer StopSequencer()"
    assert line.continuation is False


def test_a_payload_may_contain_the_field_separator():
    """
    The message is everything after the fourth ';'. A repr containing a
    semicolon must not be truncated, which is what a plain split() would do.
    """
    line = parse_line(SEPARATOR_LINE)

    assert line.message.endswith("StatusChanged(text='ready; steady; go')")


def test_a_line_that_is_not_a_record_is_a_continuation():
    """
    log.exception() writes a traceback across several lines. Only the first
    carries the timestamp; the rest belong to it and must not be parsed as
    records of their own.
    """
    line = parse_line(TRACEBACK_LINE)

    assert line.continuation is True
    assert line.timestamp is None
    assert line.message == TRACEBACK_LINE


def test_an_empty_line_is_a_continuation_rather_than_an_error():
    """Blank lines happen; parsing must be total rather than raise."""
    assert parse_line("").continuation is True


# --------------------------------------------------------------------------
# as_trace_event() - which records are messages
# --------------------------------------------------------------------------


def test_a_send_becomes_a_trace_event():
    event = as_trace_event(parse_line(SEND_LINE))

    assert event.direction == "send"
    assert event.link == "core->sequencer"
    assert event.message_type == "StopSequencer"
    assert event.payload == "StopSequencer()"
    assert event.process == "Core"


def test_a_receive_becomes_a_trace_event():
    """
    The funcName is `receive` but the message prefix is `recv`. Both spellings
    are load-bearing and this is the test that says so.
    """
    event = as_trace_event(parse_line(RECV_LINE))

    assert event.direction == "recv"
    assert event.link == "core->sequencer"
    assert event.message_type == "StopSequencer"


def test_an_unnamed_wrapper_traces_as_a_question_mark():
    """A QueueWrapper built without link= is anonymous; queue_wrapper.py traces it as '?'."""
    event = as_trace_event(parse_line(UNNAMED_LINE))

    assert event.link == "?"
    assert event.message_type == "StatusChanged"


def test_the_message_type_stops_at_the_first_bracket():
    """A nested message must be named by its outer type, not its inner one."""
    event = as_trace_event(parse_line(NESTED_LINE))

    assert event.message_type == "StepFinished"
    assert "StepOutcome" in event.payload


@pytest.mark.parametrize(
    "line",
    [INFO_LINE, OTHER_DEBUG_LINE, EXCEPTION_LINE, TRACEBACK_LINE],
    ids=["info", "debug-elsewhere", "error", "continuation"],
)
def test_only_wrapper_lines_are_trace_events(line):
    """
    Everything the framework logs is in the same file. A DEBUG line from
    somewhere other than queue_wrapper.py is not a message and must not be shown as
    one.
    """
    assert as_trace_event(parse_line(line)) is None


# --------------------------------------------------------------------------
# The coupling to the real transport
#
# Every other test in this file compares the parser against sample text, which
# is a copy of a format the Monitor does not own. A copy cannot notice that the
# original moved: when messages/channel.py became messages/queue_wrapper.py, the
# location field in every real log line changed, and sample-text tests would
# have stayed green while the Monitor matched nothing at all.
#
# These two tests look at the real thing instead.
# --------------------------------------------------------------------------


def test_the_parser_knows_which_module_writes_the_trace():
    """
    TRACE_LOCATIONS names a file and two methods that belong to the transport.
    Derived here from the class itself, so renaming the *file* cannot drift, and
    asserted for the methods, so renaming those cannot either.
    """
    import inspect
    from pathlib import Path

    from pypts.helper_applications.debug_monitor.trace_parser import TRACE_LOCATIONS
    from pypts.messages import QueueWrapper

    module = Path(inspect.getfile(QueueWrapper)).name

    assert {f"{module}:send", f"{module}:receive"} == TRACE_LOCATIONS
    assert callable(QueueWrapper.send)
    assert callable(QueueWrapper.receive)


def test_a_real_trace_line_round_trips_through_the_parser(caplog):
    """
    End to end across the seam, with no sample text anywhere: drive the real
    transport, take the record it actually logged, render it with the Logger's
    own formatter, and parse it back.

    This fails if LOG_FORMAT changes, if the transport module or its methods are
    renamed, or if the wording of the trace itself moves - which is the whole set
    of ways the Monitor can quietly stop working.
    """
    import logging
    import queue as queue_module

    from pypts.logger.log import build_formatter
    from pypts.messages import QueueWrapper
    from pypts.messages.core_hmi_communication import StatusChanged
    from pypts.messages.links import CORE_TO_HMI

    wrapper = QueueWrapper(queue_module.Queue(), link=CORE_TO_HMI)
    with caplog.at_level(logging.DEBUG, logger="pypts.trace"):
        wrapper.send(StatusChanged(text="ready"))

    record = next(r for r in caplog.records if r.name == "pypts.trace")
    event = as_trace_event(parse_line(build_formatter().format(record)))

    assert event is not None
    assert event.direction == "send"
    assert event.link == CORE_TO_HMI
    assert event.message_type == "StatusChanged"
    assert "ready" in event.payload


# --------------------------------------------------------------------------
# LivenessTracker - who is alive, derived from the trace
# --------------------------------------------------------------------------


def feed(tracker: LivenessTracker, lines) -> None:
    """Push raw log lines through the tracker the way the GUI does."""
    for raw in lines:
        tracker.feed(parse_line(raw))


def test_a_heartbeat_makes_a_module_alive():
    tracker = LivenessTracker()
    feed(tracker, [heartbeat_line("09:32:58.000", "sequencer")])

    assert tracker.state("sequencer") == ALIVE


def test_a_module_goes_dead_after_the_timeout():
    """
    The timeout is CORE's, imported rather than copied - the deleted debug
    console duplicated it and drifted.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "sequencer"),
            # Well past HEARTBEAT_TIMEOUT_S, from another module so the clock moves.
            heartbeat_line("09:33:20.000", "report"),
        ],
    )

    assert HEARTBEAT_TIMEOUT_S < 20.0
    assert tracker.state("sequencer") == DEAD
    assert tracker.state("report") == ALIVE


def test_now_is_the_last_line_not_the_wall_clock():
    """
    Replaying a log from last week must not paint every module dead. The
    tracker's clock is the file's own last timestamp.
    """
    tracker = LivenessTracker()
    feed(tracker, [heartbeat_line("09:32:58.000", "sequencer")])

    assert tracker.now == datetime(2026, 8, 12, 9, 32, 58)  # noqa: DTZ001
    assert tracker.state("sequencer") == ALIVE


def test_a_clean_stop_is_not_death():
    """
    A module that said goodbye is stopped, not lost. CORE makes the same
    distinction - it disarms the timeout for a module that reported itself
    stopped - and a Monitor that showed 'dead' here would contradict it.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "sequencer"),
            "2026-08-12 09:32:59.000;DEBUG;Core;queue_wrapper.py:receive;recv sequencer->core SequencerStopped()",
            heartbeat_line("09:33:20.000", "report"),
        ],
    )

    assert tracker.state("sequencer") == STOPPED


def test_a_module_never_heard_from_is_unknown():
    """Not the same as dead: nothing has been seen either way."""
    tracker = LivenessTracker()
    feed(tracker, [heartbeat_line("09:32:58.000", "sequencer")])

    assert tracker.state("hmi") == UNKNOWN


def test_cores_own_verdict_is_recorded_beside_the_derived_one():
    """
    CORE logs a warning when it declares a module late. Showing it next to the
    derived state is the point: a disagreement between them is a defect.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "sequencer"),
            "2026-08-12 09:33:05.000;DEBUG;Core;core.py:do_periodic_tasks;Heartbeat timeout for module: sequencer",
        ],
    )

    assert tracker.core_verdict("sequencer") == "timeout"

    feed(
        tracker,
        ["2026-08-12 09:33:06.000;DEBUG;Core;core.py:note_heartbeat;Module is responding again: sequencer"],
    )

    assert tracker.core_verdict("sequencer") == "responding"


def test_a_module_nobody_registered_gets_a_row():
    """
    The point of the whole discovery rewrite. There is no list of modules in the
    Monitor, so a module added to the framework long after this file was written
    shows up on its own, with no edit here and none in liveness.py.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:32:58.000;DEBUG;Core;queue_wrapper.py:send;send hal->core "
            "Heartbeat(source='hal', timestamp=1.0)",
        ],
    )

    assert "hal" in tracker.modules()
    assert tracker.state("hal") == ALIVE


def test_core_itself_gets_a_row():
    """
    CORE sends its own heartbeat since roadmap 1.21, so it is discovered like
    anything else - and whether the engine's own loop is turning is the one
    question this tab could not previously answer.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:32:58.000;DEBUG;Core;queue_wrapper.py:send;send core->hmi "
            "Heartbeat(source='core', timestamp=1.0)",
        ],
    )

    assert "core" in tracker.modules()
    assert tracker.state("core") == ALIVE


def test_modules_are_listed_in_the_order_the_run_introduced_them():
    """First-seen order, which is roughly startup order and is itself readable."""
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "sequencer"),
            heartbeat_line("09:32:58.100", "report"),
            heartbeat_line("09:32:58.200", "hmi"),
        ],
    )

    assert tracker.modules() == ("sequencer", "report", "hmi")


def test_a_name_that_only_ever_receives_is_not_a_module():
    """
    Only a sender can prove it is alive. The Logger never answers anybody, so a
    row for it could say nothing but "unknown" for the whole run.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:32:58.000;DEBUG;Core;queue_wrapper.py:send;send any->logger "
            "LogRecord(msg='hello')",
        ],
    )

    assert "logger" not in tracker.modules()


def test_the_any_wildcard_is_not_a_module():
    """
    `any->logger` is named for the fact that its sender is *not* one particular
    module - every process logs. It is the one name refused, and refused for
    being a wildcard rather than for being unfamiliar.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:32:58.000;DEBUG;Core;queue_wrapper.py:send;send any->logger "
            "LogRecord(msg='hello')",
        ],
    )

    assert "any" not in tracker.modules()


def test_an_anonymous_link_is_traced_but_is_not_a_module():
    """
    A QueueWrapper built without a link name traces as `?`. That is a defect
    worth seeing, and it keeps its row in the trace table and a checkbox of its
    own - but `?` names no sender, so it must not become a module. Caught when
    the discovery rewrite was checked against a real window: it had a row.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:32:58.000;DEBUG;Core;queue_wrapper.py:send;send ? "
            "SomethingNobodyNamed()",
        ],
    )

    assert tracker.modules() == ()


def test_a_goodbye_is_recognised_by_its_suffix_not_by_a_table():
    """
    `<Name>Stopped` names its own module, so a module added tomorrow needs no
    entry anywhere for its clean shutdown to read as STOPPED rather than DEAD.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:32:58.000;DEBUG;Core;queue_wrapper.py:send;send hal->core "
            "Heartbeat(source='hal', timestamp=1.0)",
            "2026-08-12 09:32:59.000;DEBUG;Core;queue_wrapper.py:receive;recv hal->core "
            "HalStopped()",
        ],
    )

    assert tracker.state("hal") == STOPPED


def test_a_run_level_stopped_event_does_not_invent_a_module():
    """
    The guard on the suffix rule. `RunStopped` and `SequenceStopped` match the
    convention perfectly well and have nothing to do with liveness; a real module
    has always spoken before it says goodbye, so nothing that has not been heard
    from can be stopped.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "sequencer"),
            "2026-08-12 09:32:59.000;DEBUG;Core;queue_wrapper.py:receive;recv sequencer->core "
            "RunStopped()",
        ],
    )

    assert "run" not in tracker.modules()
    assert tracker.state("sequencer") == ALIVE


def test_core_naming_a_module_is_enough_to_give_it_a_row():
    """
    A module that died before it ever managed a heartbeat is the run where you
    most want a row for it. CORE writes those lines only about modules it
    watches, so its word is as good as the module's own.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            "2026-08-12 09:33:05.000;DEBUG;Core;core.py:do_periodic_tasks;"
            "Heartbeat timeout for module: hal",
        ],
    )

    assert "hal" in tracker.modules()
    assert tracker.core_verdict("hal") == "timeout"


def test_core_ending_the_run_is_a_verdict_of_its_own():
    """
    `fatal` is not a louder `timeout`. A timeout is CORE reporting a module late
    and carrying on; a fatal is CORE ending the run over it. Collapsing the two
    would hide the single most important thing that happened in the log.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "sequencer"),
            "2026-08-12 09:33:05.000;DEBUG;Core;core.py:do_periodic_tasks;"
            "Heartbeat timeout for module: sequencer",
        ],
    )
    assert tracker.core_verdict("sequencer") == "timeout"

    feed(
        tracker,
        [
            "2026-08-12 09:33:15.000;DEBUG;Core;core.py:end_run_for_silent_module;"
            "Heartbeat fatal for module: sequencer",
        ],
    )

    assert tracker.core_verdict("sequencer") == "fatal"


def test_the_fatal_line_carries_nothing_but_the_module_name():
    """
    The prefix match takes everything after it as the name, so the measurements
    belong on the record below - the shape the timeout line has always had. This
    is the test that fails if somebody folds them back onto one line.
    """
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "report"),
            "2026-08-12 09:33:15.000;DEBUG;Core;core.py:end_run_for_silent_module;"
            "Heartbeat fatal for module: report (silent 16.0 s, limit 15.0 s).",
        ],
    )

    # The trailing detail makes the name unparseable, so no verdict is recorded
    # rather than a wrong one being invented.
    assert tracker.core_verdict("report") == ""


def test_a_fatal_verdict_does_not_leak_onto_another_module():
    """One module's death says nothing about the other two."""
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            heartbeat_line("09:32:58.000", "hmi"),
            heartbeat_line("09:32:58.000", "sequencer"),
            "2026-08-12 09:33:15.000;DEBUG;Core;core.py:end_run_for_silent_module;"
            "Heartbeat fatal for module: hmi",
        ],
    )

    assert tracker.core_verdict("hmi") == "fatal"
    assert tracker.core_verdict("sequencer") == ""


def test_the_fatal_prefix_matches_what_core_actually_writes():
    """
    Matching on log text is fragile and known to be. This is the guard: the
    prefix here and the format string in core.py are one fact in two files, and
    nothing but this test says so.
    """
    import inspect

    from pypts.core.core import Core
    from pypts.helper_applications.debug_monitor.liveness import FATAL_PREFIX

    source = inspect.getsource(Core.end_run_for_silent_module)

    assert f'"{FATAL_PREFIX}%s"' in source, (
        f"core.py no longer writes {FATAL_PREFIX!r} as a bare prefix + module name"
    )


def test_the_last_error_is_kept_per_module():
    """ModuleError crosses a QueueWrapper, so its whole repr is on one trace line."""
    tracker = LivenessTracker()
    feed(
        tracker,
        [
            (
                "2026-08-12 09:33:01.000;DEBUG;Core;queue_wrapper.py:receive;recv report->core "
                "ModuleError(source='report', severity=ERROR, message='disk full')"
            )
        ],
    )

    assert "disk full" in tracker.last_error("report")


def test_a_log_with_no_trace_lines_is_reported_as_such():
    """
    A run at INFO produces no trace at all. The Monitor has to say so rather
    than show an empty table and let the user assume nothing happened.
    """
    tracker = LivenessTracker()
    feed(tracker, [INFO_LINE, EXCEPTION_LINE, TRACEBACK_LINE, TRACEBACK_LINE_2])

    assert tracker.trace_seen is False

    feed(tracker, [SEND_LINE])

    assert tracker.trace_seen is True


# --------------------------------------------------------------------------
# LogFollower - reading a file somebody else is still writing
# --------------------------------------------------------------------------


def test_only_new_lines_are_returned(tmp_path):
    """
    The Monitor polls; each poll must return what arrived since the last one and
    not the whole file again.
    """
    log_file = tmp_path / "pypts_20260812_093258.log"
    log_file.write_text(INFO_LINE + "\n", encoding="utf-8")

    follower = LogFollower(log_file)
    follower.open()

    assert follower.read_lines() == [INFO_LINE]
    assert follower.read_lines() == []

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(SEND_LINE + "\n")

    assert follower.read_lines() == [SEND_LINE]

    follower.close()


def test_a_half_written_line_is_held_back(tmp_path):
    """
    A read can land between the Logger's write and its flush. Returning half a
    record would put a torn line in the trace table and, worse, make the parser
    call it a continuation.
    """
    log_file = tmp_path / "pypts_20260812_093258.log"
    log_file.write_text(SEND_LINE[:40], encoding="utf-8")

    follower = LogFollower(log_file)
    follower.open()

    assert follower.read_lines() == []

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(SEND_LINE[40:] + "\n")

    assert follower.read_lines() == [SEND_LINE]

    follower.close()


def test_the_newest_log_is_the_one_picked(tmp_path):
    """Attaching means attaching to the run that is happening now."""
    older = tmp_path / "pypts_20260812_090000.log"
    newer = tmp_path / "pypts_20260812_093258.log"
    older.write_text("", encoding="utf-8")
    newer.write_text("", encoding="utf-8")
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    assert find_latest_log(tmp_path) == newer


def test_an_empty_directory_has_no_latest_log(tmp_path):
    """Answered with None rather than raised: it just means pypts never ran."""
    assert find_latest_log(tmp_path) is None


# --------------------------------------------------------------------------
# LogLine is a plain value
# --------------------------------------------------------------------------


def test_log_lines_are_frozen():
    """
    Same house rule as the message dataclasses: a parsed record is a value, so
    nothing downstream can rewrite history.
    """
    line = parse_line(SEND_LINE)

    with pytest.raises(FrozenInstanceError):
        line.level = "INFO"  # type: ignore[misc]

    assert isinstance(line, LogLine)


# --------------------------------------------------------------------------
# The Qt half
#
# Guarded rather than skipped at module level: everything above is pure and has
# to keep running on a machine with no PySide6 installed.
# --------------------------------------------------------------------------

try:  # pragma: no cover - the import either works on this machine or it does not
    import PySide6  # noqa: F401

    HAS_PYSIDE6 = True
except ImportError:  # pragma: no cover
    HAS_PYSIDE6 = False

requires_qt = pytest.mark.skipif(not HAS_PYSIDE6, reason="the GUI is an optional extra")


def events(*lines):
    """The TraceEvents of some sample lines, for feeding a model directly."""
    return [as_trace_event(parse_line(line)) for line in lines]


@requires_qt
def test_the_table_trims_but_the_count_does_not(qapp):
    """
    The buffer is a window on the tail. Reporting its size as the number of
    messages seen would under-report every busy run, and a message trace that
    under-reports is worse than none.
    """
    from pypts.helper_applications.debug_monitor.trace_model import TraceModel

    model = TraceModel(max_rows=3)
    model.append(events(SEND_LINE, RECV_LINE))
    model.append(events(SEND_LINE, RECV_LINE, SEND_LINE))

    assert model.rowCount() == 3
    assert model.total_seen == 5


@requires_qt
def test_a_batch_larger_than_the_buffer_is_survivable(qapp):
    """
    Attaching to a finished run appends the whole file in one go. Inserting more
    rows than the deque can hold would leave the view's indices past the end.
    """
    from pypts.helper_applications.debug_monitor.trace_model import TraceModel

    model = TraceModel(max_rows=3)
    model.append(events(*([SEND_LINE] * 10)))

    assert model.rowCount() == 3
    assert model.total_seen == 10


@requires_qt
def test_heartbeats_are_hidden_until_asked_for(qapp):
    """Six rows a second of pulse would bury everything else."""
    from pypts.helper_applications.debug_monitor.trace_model import (
        TraceFilter,
        TraceModel,
    )

    model = TraceModel()
    model.append(events(heartbeat_line("09:32:58.000", "sequencer"), SEND_LINE))

    filtered = TraceFilter()
    filtered.setSourceModel(model)

    assert filtered.rowCount() == 1

    filtered.set_hide_noise(False)

    assert filtered.rowCount() == 2


@requires_qt
def test_a_hidden_link_disappears_and_an_unknown_one_does_not(qapp):
    """
    Filtering names what to hide rather than what to show, so a link nobody
    listed - an anonymous QueueWrapper tracing as '?' - stays visible. An unnamed
    QueueWrapper is a defect, and the filter must not be able to conceal one.
    """
    from PySide6.QtCore import Qt

    from pypts.helper_applications.debug_monitor.trace_model import (
        TraceFilter,
        TraceModel,
    )

    model = TraceModel()
    model.append(events(SEND_LINE, UNNAMED_LINE))

    filtered = TraceFilter()
    filtered.setSourceModel(model)
    filtered.set_hidden_links({"core->sequencer"})

    assert filtered.rowCount() == 1
    assert filtered.data(filtered.index(0, 0), Qt.UserRole).link == "?"


@requires_qt
def test_the_text_filter_searches_the_whole_payload(qapp):
    """
    The payload column is elided at any usable width, so searching what is drawn
    would miss most of what is there.
    """
    from pypts.helper_applications.debug_monitor.trace_model import (
        TraceFilter,
        TraceModel,
    )

    model = TraceModel()
    model.append(events(SEPARATOR_LINE, SEND_LINE))

    filtered = TraceFilter()
    filtered.setSourceModel(model)
    filtered.set_text("steady")

    assert filtered.rowCount() == 1


@requires_qt
def test_the_window_reads_the_log_it_was_given(qapp, tmp_path):
    """
    End to end over the real file path: construct, tick once, and the trace and
    the liveness view both reflect what is in the file.
    """
    from pypts.helper_applications.debug_monitor.main_window import DebugMonitor

    log_file = tmp_path / "pypts_20260812_093258.log"
    log_file.write_text(
        "\n".join([INFO_LINE, SEND_LINE, RECV_LINE, heartbeat_line("09:32:58.500", "sequencer")]) + "\n",
        encoding="utf-8",
    )

    monitor = DebugMonitor(log_file)
    try:
        monitor.timer.stop()  # tick by hand, so the test does not race the clock
        monitor.poll()

        assert monitor.trace_model.total_seen == 3
        assert monitor.tracker.state("sequencer") == ALIVE
        assert monitor.tracker.trace_seen is True
    finally:
        monitor.close()


@requires_qt
def test_the_open_logs_folder_button_shows_the_logs_directory(qapp, tmp_path, monkeypatch):
    """
    The button answers "where are my logs": it hands the folder of the log
    being followed - every run's log is a sibling there - to the system file
    browser. The hand-off is what is tested; opening a real Explorer window
    from a unit test would be an interruption, not a check.
    """
    from pathlib import Path

    from PySide6.QtGui import QDesktopServices

    from pypts.helper_applications.debug_monitor.main_window import DebugMonitor

    log_file = tmp_path / "pypts_20260812_093258.log"
    log_file.write_text(INFO_LINE + "\n", encoding="utf-8")

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True)
    )

    monitor = DebugMonitor(log_file)
    try:
        monitor.timer.stop()
        monitor.open_logs_button.click()
    finally:
        monitor.close()

    assert [Path(url.toLocalFile()) for url in opened] == [tmp_path]


@requires_qt
def test_a_log_with_no_trace_says_so_rather_than_showing_nothing(qapp, tmp_path):
    """
    A run at INFO produces a log with no trace in it. An empty table reads as
    'nothing happened', which is wrong and expensive to work out.
    """
    from pypts.helper_applications.debug_monitor.main_window import (
        NO_TRACE_HINT,
        DebugMonitor,
    )

    log_file = tmp_path / "pypts_20260812_093258.log"
    log_file.write_text(INFO_LINE + "\n", encoding="utf-8")

    monitor = DebugMonitor(log_file)
    try:
        monitor.timer.stop()
        monitor.poll()

        assert monitor.trace_model.total_seen == 0
        assert NO_TRACE_HINT in monitor.status.text()
    finally:
        monitor.close()
