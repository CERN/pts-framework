# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for src/pypts/utilities/.

There are two error decorators now, and which one a piece of code uses is the
whole point. `catch_and_report_errors` reports and continues, for event loops,
where a module that dies on one bad message takes the run with it.
`report_and_reraise` reports and lets the exception through, for the execution
layer, where a step whose failure is only a log line is a step the report will
call PASS. That split closes the Phase 0 item; the tests below pin both halves
and the case neither used to survive - a decorated object with no outbox.

What the decorator no longer does is cache the *first caller's* module name: the
source it reports is resolved from the decorated function at decoration time,
which is what test_catch_and_report_errors_detects_the_module_per_function pins.

poll_queue is gone. Reading a queue is wrapper.receive now, and it is covered in
test_messages.py alongside the rest of the transport.
"""

import queue
import traceback

import pytest

from pypts.messages import QueueWrapper
from pypts.messages.common_messages import ErrorSeverity, Heartbeat, ModuleError
from pypts.utilities.common import convert_string_to_int
from pypts.utilities.error_handling import (
    catch_and_report_errors,
    report_and_reraise,
    report_error,
    report_problem,
)
from pypts.utilities.heartbeat_manager import HeartbeatManager

PLACEHOLDER = "placeholder - test not implemented yet"


class FakeModule:
    """The minimum a decorated class has to look like: something with `core`."""

    def __init__(self, outbox):
        self.core = QueueWrapper(outbox)

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
            self.core = QueueWrapper(outbox)

        @catch_and_report_errors(module_name="pypts.hardware_layer.hal")
        def explode(self):
            raise RuntimeError("driver lost")

    Named().explode()

    assert outbox.get_nowait().source == "pypts.hardware_layer.hal"


def test_catch_and_report_errors_swallows_so_an_event_loop_survives():
    """The loop has to come round again. That is the whole reason it swallows."""
    outbox: queue.Queue = queue.Queue()

    assert FakeModule(outbox).explode() is None


def test_report_and_reraise_reports_and_then_lets_the_exception_through():
    """
    The execution layer's half. A step failure has to reach a StepResult, so the
    caller must see the exception - after CORE has been told about it.
    """
    outbox: queue.Queue = queue.Queue()

    class Step:
        def __init__(self):
            self.core = QueueWrapper(outbox)

        @report_and_reraise()
        def run(self):
            raise ValueError("the DUT did not answer")

    with pytest.raises(ValueError, match="the DUT did not answer"):
        Step().run()

    error = outbox.get_nowait()
    assert isinstance(error, ModuleError)
    assert error.message == "the DUT did not answer"
    assert error.severity is ErrorSeverity.ERROR


def test_report_and_reraise_keeps_the_original_traceback():
    """
    `raise` rather than `raise exc`, so the frame the failure happened in is
    still in the traceback the step turns into a result.
    """
    outbox: queue.Queue = queue.Queue()

    class Step:
        def __init__(self):
            self.core = QueueWrapper(outbox)

        @report_and_reraise()
        def run(self):
            raise ValueError("boom")

    with pytest.raises(ValueError) as caught:
        Step().run()

    frames = [frame.name for frame in traceback.extract_tb(caught.value.__traceback__)]
    assert "run" in frames


@pytest.mark.parametrize(
    "decorator", [catch_and_report_errors, report_and_reraise], ids=["catch", "reraise"]
)
def test_an_object_with_no_outbox_is_logged_rather_than_masked(decorator, caplog):
    """
    A driver or a half-built object can be decorated without CORE existing.

    Raising AttributeError from inside the error handler would replace the real
    failure with a much less interesting one, which is exactly what used to
    happen: the decorator reached for `self.core` unconditionally.
    """
    class NoOutbox:
        """Deliberately has no `core` attribute."""

        @decorator()
        def run(self):
            raise ValueError("boom")

    with caplog.at_level("ERROR"):
        if decorator is report_and_reraise:
            with pytest.raises(ValueError, match="boom"):
                NoOutbox().run()
        else:
            NoOutbox().run()

    assert any("boom" in record.getMessage() for record in caplog.records)
    assert any("has no outbox" in record.getMessage() for record in caplog.records)


def test_a_reported_error_names_the_method_and_the_exception_type():
    """
    The decorator knows both without being told, and neither can be recovered
    from `source` alone: it names the module, and a module has twenty methods.
    """
    outbox: queue.Queue = queue.Queue()

    FakeModule(outbox).explode()

    error = outbox.get_nowait()
    assert error.operation == "FakeModule.explode"
    assert error.error_type == "ValueError"


def test_a_decorator_can_declare_the_severity_of_an_unexpected_failure():
    """
    ERROR is right for almost everything, which is why it is the default. A
    method whose failure is routine says so once, where it is decorated.
    """
    outbox: queue.Queue = queue.Queue()

    class Poller:
        def __init__(self):
            self.core = QueueWrapper(outbox)

        @catch_and_report_errors(severity=ErrorSeverity.WARNING)
        def poll(self):
            raise TimeoutError("the instrument was slow")

    Poller().poll()

    assert outbox.get_nowait().severity is ErrorSeverity.WARNING


def test_report_error_lets_a_raise_site_classify_what_it_caught():
    """
    The point of the raise-site half: the method that knows what a TimeoutError
    means here says so, and carries on with its own recovery. The decorator
    could only have called it an ERROR and swallowed the rest of the method.
    """
    outbox: queue.Queue = queue.Queue()

    class Instrument:
        def __init__(self):
            self.core = QueueWrapper(outbox)

        @catch_and_report_errors()
        def measure(self):
            try:
                raise TimeoutError("no answer in 5 s")
            except TimeoutError as exc:
                report_error(self, exc, severity=ErrorSeverity.WARNING)
                return "retried"

    assert Instrument().measure() == "retried"

    error = outbox.get_nowait()
    assert isinstance(error, ModuleError)
    assert error.severity is ErrorSeverity.WARNING
    assert error.error_type == "TimeoutError"
    assert error.source == Instrument.__module__
    assert "TimeoutError: no answer in 5 s" in error.traceback
    assert outbox.empty(), "the decorator reported it a second time"


def test_report_problem_carries_no_traceback_because_nothing_was_raised():
    """
    A refusal is a fact worth reporting that nothing raised. Raising one only to
    catch it a frame later would attach a traceback through the module's own
    guard, which tells the reader nothing.
    """
    outbox: queue.Queue = queue.Queue()

    class Module:
        def __init__(self):
            self.core = QueueWrapper(outbox)

    report_problem(Module(), "already running", operation="Module.start")

    error = outbox.get_nowait()
    assert error.message == "already running"
    assert error.operation == "Module.start"
    assert error.traceback is None
    assert error.exception is None
    assert error.error_type == ""


@pytest.mark.parametrize("report", [report_error, report_problem], ids=["error", "problem"])
def test_a_raise_site_with_no_outbox_is_logged_rather_than_masked(report, caplog):
    """
    Same guarantee the decorators have. A driver or a half-built object can
    report without CORE existing, and the failure still has to be recorded.
    """
    class NoOutbox:
        """Deliberately has no `core` attribute."""

    if report is report_error:
        argument: object = ValueError("boom")
    else:
        argument = "boom"

    with caplog.at_level("ERROR"):
        report(NoOutbox(), argument)

    assert any("boom" in record.getMessage() for record in caplog.records)
    assert any("has no outbox" in record.getMessage() for record in caplog.records)


def test_heartbeat_manager_respects_its_interval():
    """One heartbeat per interval, however often tick() is called.

    tick() runs on every pass of an event loop - about a hundred times a second -
    so the interval is the only thing keeping the link quiet.
    """
    outbox: queue.Queue = queue.Queue()
    manager = HeartbeatManager(QueueWrapper(outbox), "sequencer", interval_s=60.0)

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
    manager = HeartbeatManager(QueueWrapper(outbox), "report", interval_s=60.0)

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
