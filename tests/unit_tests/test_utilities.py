# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for src/pypts/utilities/.

catch_and_report_errors still swallows the exception and returns None, and it
still assumes `self.core` exists. Both remain Phase 0 items and must be covered
before the sequencer executes real steps, otherwise step failures go silent.

What it no longer does is cache the *first caller's* module name: the source it
reports is now resolved from the decorated function at decoration time, which
is what test_catch_and_report_errors_detects_the_module_per_function pins down.

poll_queue is gone. Reading a queue is Channel.receive now, and it is covered in
test_messages.py alongside the rest of the transport.
"""

import queue

import pytest

from pypts.messages import Channel
from pypts.messages.common import ErrorSeverity, Heartbeat, ModuleError
from pypts.utilities.common import convert_string_to_int
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager

PLACEHOLDER = "placeholder - test not implemented yet"


class FakeModule:
    """The minimum a decorated class has to look like: something with `core`."""

    def __init__(self, outbox):
        self.core = Channel(outbox)

    @catch_and_report_errors()
    def explode(self):
        raise ValueError("boom")


def test_catch_and_report_errors_sends_a_module_error_to_core():
    outbox: queue.Queue = queue.Queue()

    FakeModule(outbox).explode()

    error = outbox.get_nowait()
    assert isinstance(error, ModuleError)
    assert error.message == "boom"
    assert error.exception == "ValueError('boom')"
    assert "ValueError: boom" in error.traceback
    # The enum survives. It used to be flattened to its .name by every sender
    # and was never turned back into an enum on the receiving side.
    assert error.severity is ErrorSeverity.ERROR


def test_catch_and_report_errors_detects_the_module_per_function():
    """Not once, for the first caller, and then reused forever.

    The old implementation read inspect.stack()[1] on the first invocation and
    cached it in a nonlocal, so the reported source was whichever module
    happened to call the function first - and every later failure inherited it.
    """
    outbox: queue.Queue = queue.Queue()

    FakeModule(outbox).explode()

    assert outbox.get_nowait().source == FakeModule.explode.__wrapped__.__module__


def test_catch_and_report_errors_lets_an_explicit_module_name_win():
    outbox: queue.Queue = queue.Queue()

    class Named:
        def __init__(self):
            self.core = Channel(outbox)

        @catch_and_report_errors(module_name="pypts.hardware_layer.hal")
        def explode(self):
            raise RuntimeError("driver lost")

    Named().explode()

    assert outbox.get_nowait().source == "pypts.hardware_layer.hal"


def test_heartbeat_manager_respects_its_interval():
    """One heartbeat per interval, however often tick() is called.

    tick() runs on every pass of an event loop - about a hundred times a second -
    so the interval is the only thing keeping the link quiet.
    """
    outbox: queue.Queue = queue.Queue()
    manager = HeartbeatManager(Channel(outbox), "sequencer", interval_s=60.0)

    for _ in range(10):
        manager.tick()

    beat = outbox.get_nowait()
    assert isinstance(beat, Heartbeat)
    assert beat.source == "sequencer"
    assert outbox.empty(), "tick() sent more than one heartbeat inside its interval"


def test_heartbeat_manager_sends_again_once_the_interval_has_passed():
    """Elapsed time is simulated rather than slept through.

    Two real tick() calls in a row can read the same time.time() - the clock is
    only about 15 ms granular on Windows - so a test that just called tick()
    twice would be asserting the resolution of the clock, not the behaviour.
    """
    outbox: queue.Queue = queue.Queue()
    manager = HeartbeatManager(Channel(outbox), "report", interval_s=60.0)

    manager.tick()
    manager.last_sent -= 120.0  # pretend two minutes went by
    manager.tick()

    assert outbox.qsize() == 2


def test_convert_string_to_int_rejects_non_numeric_input():
    assert convert_string_to_int("42") == 42

    with pytest.raises(ValueError):
        convert_string_to_int("not a number")

    with pytest.raises(TypeError):
        convert_string_to_int(None)


@pytest.mark.skip(reason=PLACEHOLDER)
def test_catch_and_report_errors_does_not_swallow_the_exception():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_catch_and_report_errors_works_without_a_core_attribute():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_local_storage_paths_are_platform_neutral():
    ...
