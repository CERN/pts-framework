# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The run log's grammar, in one place.

Two total functions and two values. `parse_line()` turns one line of the run log
into a `LogLine`; `as_trace_event()` decides whether that record is a message
crossing a QueueWrapper, and if so takes it apart. Neither raises, neither imports Qt,
and neither needs a framework to be running - a string is the whole input.

This module is the Monitor's single point of contact with a format it does not
own. `LOG_FORMAT` lives in `pypts/logger/log.py` and the trace text in
`pypts/messages/queue_wrapper.py`; if either changes, this file is what has to follow,
and the tests in `tests/unit_tests/test_debug_monitor.py` are what will say so.

The format being parsed
-----------------------

    LOG_FORMAT = "%(asctime)s.%(msecs)03d;%(levelname)s;%(processName)s;
                  %(filename)s:%(funcName)s;%(message)s"

    2026-08-12 09:32:58.056;DEBUG;Core;queue_wrapper.py:send;send core->sequencer StopSequencer()
    2026-08-12 09:32:58.101;DEBUG;Sequencer;queue_wrapper.py:receive;recv core->sequencer StopSequencer()

A record is a trace line when all three of these hold: the level is DEBUG, the
location is one of the two QueueWrapper methods, and the message starts with `send `
or `recv `. Note the mismatch between the two spellings - the function is called
`receive`, the trace it writes says `recv` - and that both are needed.

Deliberately *not* matched on the logger name. `QueueWrapper` traces on a logger
called `pypts.trace`, which would be the obvious discriminator, but `LOG_FORMAT`
has no `%(name)s` so the name never reaches the file. That is an open TODO in the
roadmap; until it is done, the location field is the reliable signal.

What is lost, and why that is accepted
--------------------------------------

The payload is the message's `repr()`, so the type name survives and the fields
do not - `StepFinished(outcome=StepOutcome(step_name='Power on', result=PASS))`
is text, not a StepOutcome. Recovering the object would mean evaluating a repr,
which is the trick the typed-message rework existed to get rid of. Filtering by
link and by type is what this is for, and the repr is legible enough to read.

One thing that is *not* lost: a repr escapes newlines inside strings, so a trace
line is always exactly one line, even for a ModuleError carrying a traceback.
Multi-line records exist in the log - `log.exception()` writes them - but they
are never trace lines, which is why continuations can simply be marked and
ignored here.
"""

import re
from dataclasses import dataclass
from datetime import datetime

#: One record of the run log, i.e. LOG_FORMAT in logger/log.py. The message is
#: `.*` and comes last, so a repr containing the ';' separator survives whole.
RECORD = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3});"
    r"(?P<level>[A-Z]+);"
    r"(?P<process>[^;]*);"
    r"(?P<location>[^;]*);"
    r"(?P<message>.*)$"
)

#: DATE_FORMAT in logger/log.py, plus the milliseconds appended after it. %f
#: reads them as microseconds, so ".056" becomes 56000us.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

#: The two QueueWrapper methods that trace. `filename:funcName`, as the Logger writes
#: it. `receive` rather than `recv`: this is the function name, not the trace.
TRACE_LOCATIONS = frozenset({"queue_wrapper.py:send", "queue_wrapper.py:receive"})

#: The two words a trace message can start with. These *are* `recv`, not
#: `receive` - see the module docstring.
SEND = "send"
RECV = "recv"
DIRECTIONS = (SEND, RECV)

#: What an anonymous QueueWrapper traces as, from `self.link or "?"` in queue_wrapper.py.
UNNAMED_LINK = "?"


@dataclass(frozen=True, slots=True)
class LogLine:
    """
    One line of the run log, parsed as far as the log format goes.

    Frozen for the same reason every message in the framework is: a parsed
    record is a value, and nothing downstream should be able to rewrite it.

    A line that does not match the record format is not an error - it is a
    continuation, the second and later lines of a traceback written by
    `log.exception()`. It is returned with `continuation=True`, no timestamp,
    and the raw text as its message, so a caller can display it without having
    to guess.
    """

    timestamp: datetime | None
    level: str
    process: str
    location: str
    message: str
    continuation: bool = False


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """
    One message crossing one QueueWrapper, as the trace recorded it.

    `direction` is `send` or `recv`, and the pair is the point: a send with no
    matching recv is a lost message, which is exactly the failure the trace was
    put on both sides of the transport to make visible.

    `process` is the process that logged the line, which is not derivable from
    the link - `core->hmi` is sent by Core and received by the GUI, and both
    lines say `core->hmi`.
    """

    timestamp: datetime | None
    process: str
    direction: str
    link: str
    message_type: str
    payload: str


def parse_line(raw_line: str) -> LogLine:
    """
    Parse one line of the run log. Never raises.

    Args:
        raw_line: one line, with or without its trailing newline.

    Returns:
        The parsed record, or a `LogLine` marked `continuation=True` when the
        line is not a record of its own. Blank lines land in the second case.
    """
    line = raw_line.rstrip("\n").rstrip("\r")

    match = RECORD.match(line)
    if match is None:
        return LogLine(
            timestamp=None,
            level="",
            process="",
            location="",
            message=line,
            continuation=True,
        )

    return LogLine(
        # Naive on purpose: the Logger writes local time with no offset, so
        # there is no zone in the file to read. Attaching one here would be
        # inventing information, and every timestamp the Monitor compares comes
        # from this same file.
        timestamp=datetime.strptime(match["timestamp"], TIMESTAMP_FORMAT),  # noqa: DTZ007
        level=match["level"],
        process=match["process"],
        location=match["location"],
        message=match["message"],
    )


def as_trace_event(line: LogLine) -> TraceEvent | None:
    """
    Take a parsed record apart as a message trace, if that is what it is.

    Returns:
        The event, or None for every other line in the log - and most lines are
        every other line. The narrative the framework logs at INFO, its warnings
        and its tracebacks all arrive here and all answer None.
    """
    if line.continuation or line.level != "DEBUG" or line.location not in TRACE_LOCATIONS:
        return None

    # maxsplit=2, so a payload containing spaces - every payload - stays whole.
    parts = line.message.split(" ", 2)
    if len(parts) != 3:
        return None

    direction, link, payload = parts
    if direction not in DIRECTIONS:
        return None

    return TraceEvent(
        timestamp=line.timestamp,
        process=line.process,
        direction=direction,
        link=link,
        message_type=message_type_of(payload),
        payload=payload,
    )


def message_type_of(payload: str) -> str:
    """
    The class name at the front of a dataclass repr.

    `StepFinished(outcome=StepOutcome(...))` is a StepFinished. Stopping at the
    first bracket is what keeps a nested message from being named by its inner
    type. A payload with no bracket at all is its own name.
    """
    return payload.split("(", 1)[0] or payload
