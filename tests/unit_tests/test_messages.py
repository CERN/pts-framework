# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the message layer (src/pypts/messages/).

Three properties are pinned down here, each of them a defect the previous
design could not have caught:

  * Every message crossing the HMI <-> Core process boundary can be pickled.
    This is the roadmap TODO that keeps the thread/process split a one-line
    launcher change; the moment a message starts carrying something live, this
    fails rather than the GUI failing at run time.
  * Every member of every link's union is matched by its recipient's handler.
    Core had no branch for the HMI's ModuleError and silently discarded every
    error a frontend reported; the Sequencer had none for StopSequence, a
    command Core has a method to send. Both were invisible because the handlers
    ended in `case _: pass`.
  * The GUI and the CLI answer the protocol identically. They used to differ on
    StopHmi - the GUI completed the handshake and the CLI did not - so in CLI
    mode Core could never establish that every module had stopped.

The EXAMPLES table below is the mechanism that makes the first two exhaustive:
test_every_message_type_has_an_example fails when a message is added to a union
without an example, so nothing here can be forgotten by omission.
"""

import pickle
import queue
from dataclasses import FrozenInstanceError, fields, is_dataclass
from enum import Enum
from typing import get_args
from uuid import UUID

import pytest

from pypts.core.core import Core
from pypts.hmi.hmi_client import HmiClient
from pypts.logger.log import Logger
from pypts.messages import Channel, UnhandledMessage
from pypts.messages.common import (
    ErrorSeverity,
    Heartbeat,
    ModuleError,
    ResultType,
    StepOutcome,
)
from pypts.messages.hmi_link import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    LoadRecipe,
    ModuleErrorReported,
    ShutdownRequested,
    StartSequence,
    StatusChanged,
    StopHmi,
)
from pypts.messages.logger_link import LoggerControl, SetStdoutEnabled, StopLogger
from pypts.messages.report_link import (
    CoreToReport,
    ExportReport,
    GenerateReport,
    ReportExported,
    ReportGenerated,
    ReportStopped,
    ReportToCore,
    StopReport,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    SerialNumberRequest,
    SerialNumberResponse,
    StepFinished,
    StepStarted,
    UserPromptRequest,
    UserPromptResponse,
)
from pypts.messages.sequencer_link import (
    CoreToSequencer,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequence,
    StopSequencer,
)
from pypts.report.report import Report
from pypts.sequencer.sequencer import Sequencer

STEP_ID = UUID("00000000-0000-4000-8000-000000000001")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000002")

AN_ERROR = ModuleError(
    source="pypts.sequencer.sequencer",
    severity=ErrorSeverity.ERROR,
    message="boom",
    exception="ValueError('boom')",
    traceback="Traceback (most recent call last):\n...",
)

AN_OUTCOME = StepOutcome(
    step_id=STEP_ID,
    step_name="Measure voltage",
    result=ResultType.PASS,
)

#: One populated instance of every message type in the framework. Kept explicit
#: rather than generated from the annotations, so that a message with a field
#: nobody thought about cannot be filled in with a plausible-looking default.
EXAMPLES = {
    # common
    Heartbeat: Heartbeat(source="sequencer", timestamp=1_760_000_000.5),
    ModuleError: AN_ERROR,
    # run_events
    RecipeLoaded: RecipeLoaded(recipe_name="DUT smoke test", recipe_version="1.2.0"),
    RunStarted: RunStarted(recipe_name="DUT smoke test", recipe_description="Nightly"),
    RunFinished: RunFinished(result=ResultType.PASS, outcomes=(AN_OUTCOME,)),
    SequenceStarted: SequenceStarted(sequence_name="Main"),
    SequenceFinished: SequenceFinished(sequence_name="Main", result=ResultType.FAIL),
    StepStarted: StepStarted(step_id=STEP_ID, step_name="Measure voltage"),
    StepFinished: StepFinished(outcome=AN_OUTCOME),
    UserPromptRequest: UserPromptRequest(
        request_id=REQUEST_ID,
        message="Connect the DUT",
        options=("OK", "Abort"),
        image_path="/tmp/dut.png",
    ),
    UserPromptResponse: UserPromptResponse(request_id=REQUEST_ID, choice="OK"),
    SerialNumberRequest: SerialNumberRequest(request_id=REQUEST_ID),
    SerialNumberResponse: SerialNumberResponse(request_id=REQUEST_ID, serial_number="SN-42"),
    # hmi_link
    LoadRecipe: LoadRecipe(recipe_path="resources/recipes/example.yaml"),
    StartSequence: StartSequence(sequence_name="Main"),
    ShutdownRequested: ShutdownRequested(),
    HmiStopped: HmiStopped(),
    StopHmi: StopHmi(),
    StatusChanged: StatusChanged(text="Idle"),
    ModuleErrorReported: ModuleErrorReported(error=AN_ERROR),
    # sequencer_link
    RunSequence: RunSequence(sequence_name="Main"),
    StopSequence: StopSequence(),
    StopSequencer: StopSequencer(),
    SequencerStopped: SequencerStopped(),
    # report_link
    GenerateReport: GenerateReport(),
    ExportReport: ExportReport(),
    StopReport: StopReport(),
    ReportStopped: ReportStopped(),
    ReportGenerated: ReportGenerated(report_path="/tmp/run/report.html"),
    ReportExported: ReportExported(report_path="/tmp/run/report.html"),
    # logger_link
    SetStdoutEnabled: SetStdoutEnabled(enabled=False),
    StopLogger: StopLogger(),
}

#: Every link, as (name, union). The handler coverage test walks this.
LINKS = {
    "HmiToCore": HmiToCore,
    "CoreToHmi": CoreToHmi,
    "CoreToSequencer": CoreToSequencer,
    "SequencerToCore": SequencerToCore,
    "CoreToReport": CoreToReport,
    "ReportToCore": ReportToCore,
    "LoggerControl": LoggerControl,
}

#: Only these two cross a process boundary, and only in GUI mode.
BOUNDARY_LINKS = ("HmiToCore", "CoreToHmi")


def message_types(*link_names):
    """The message classes carried by the named links, de-duplicated."""
    seen = {}
    for name in link_names:
        for message_type in get_args(LINKS[name]):
            seen[message_type] = None
    return list(seen)


def ids(message_types_):
    return [message_type.__name__ for message_type in message_types_]


BOUNDARY_TYPES = message_types(*BOUNDARY_LINKS)
ALL_TYPES = message_types(*LINKS)


# --------------------------------------------------------------------------
# The table itself
# --------------------------------------------------------------------------

def test_every_message_type_has_an_example():
    """Adding a message to a union without an example must fail here.

    This is what makes the parametrised tests below exhaustive rather than
    merely broad: they iterate over the unions, and this asserts the unions and
    the table agree.
    """
    missing = [message_type.__name__ for message_type in ALL_TYPES if message_type not in EXAMPLES]
    assert not missing, f"EXAMPLES is missing: {sorted(missing)}"


def test_no_example_is_left_over():
    """A message removed from every union should be removed from the table too."""
    orphaned = [
        message_type.__name__ for message_type in EXAMPLES if message_type not in ALL_TYPES
    ]
    assert not orphaned, f"EXAMPLES has entries in no union: {sorted(orphaned)}"


@pytest.mark.parametrize("message_type", ALL_TYPES, ids=ids(ALL_TYPES))
def test_every_message_is_a_frozen_dataclass(message_type):
    """Frozen because a message is a fact that has already happened.

    Nothing downstream may edit a message in flight - Core forwards the same
    object to the HMI rather than repacking it, so a mutable message would let
    one recipient change what another one sees.
    """
    assert is_dataclass(message_type), f"{message_type.__name__} is not a dataclass"

    instance = EXAMPLES[message_type]
    if fields(message_type):
        first = fields(message_type)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(instance, first, None)


# --------------------------------------------------------------------------
# Pickle safety across the one process boundary
# --------------------------------------------------------------------------

@pytest.mark.parametrize("message_type", BOUNDARY_TYPES, ids=ids(BOUNDARY_TYPES))
def test_every_hmi_core_message_survives_a_pickle_round_trip(message_type):
    """The HMI is a separate process in GUI mode, so every message is pickled.

    Equality after the round trip is the real assertion: a message that
    survives pickling but comes back different would be worse than one that
    fails outright.
    """
    original = EXAMPLES[message_type]

    restored = pickle.loads(pickle.dumps(original))

    assert restored == original
    assert type(restored) is type(original)


#: What a message may be built out of. Anything else is either unpicklable or
#: carries identity that does not survive a process boundary.
ALLOWED_FIELD_TYPES = (str, int, float, bool, bytes, UUID, Enum, type(None))


def assert_field_value_is_transferable(value, path):
    """Recursively assert one field value is safe to send between processes."""
    if isinstance(value, ALLOWED_FIELD_TYPES):
        return
    if isinstance(value, tuple):
        for index, item in enumerate(value):
            assert_field_value_is_transferable(item, f"{path}[{index}]")
        return
    if is_dataclass(value):
        for field in fields(value):
            assert_field_value_is_transferable(getattr(value, field.name), f"{path}.{field.name}")
        return
    raise AssertionError(f"{path} is a {type(value).__name__}, which cannot cross a process boundary")


@pytest.mark.parametrize("message_type", BOUNDARY_TYPES, ids=ids(BOUNDARY_TYPES))
def test_no_message_payload_carries_a_live_queue_or_handle(message_type):
    """The old user-interaction trick put a live SimpleQueue inside an event.

    It worked only because both ends were threads in one process. Across a
    process boundary it cannot work at all, which is why prompts are now a
    request/response pair joined by a request_id. Lists and dicts are rejected
    along with queues: both are mutable, and a message is a fact.
    """
    instance = EXAMPLES[message_type]
    for field in fields(message_type):
        assert_field_value_is_transferable(
            getattr(instance, field.name), f"{message_type.__name__}.{field.name}"
        )


# --------------------------------------------------------------------------
# Channel
# --------------------------------------------------------------------------

def test_channel_receive_on_an_empty_queue_yields_nothing():
    channel = Channel(queue.Queue())

    assert list(channel.receive()) == []
    assert channel.received == 0


def test_channel_receive_yields_a_burst_in_one_call():
    """The old helper took exactly one message per 10 ms tick.

    That capped every link at about 100 messages a second, so a run streaming
    step results would build latency it could never work off.
    """
    channel = Channel(queue.Queue())
    for index in range(10):
        channel.send(StatusChanged(text=str(index)))

    handled = list(channel.receive())

    assert [message.text for message in handled] == [str(index) for index in range(10)]


def test_channel_receive_stops_at_its_limit():
    """Bounded, so one busy link cannot starve the other queues in an event loop."""
    channel = Channel(queue.Queue())
    for index in range(10):
        channel.send(StatusChanged(text=str(index)))

    assert len(list(channel.receive(limit=4))) == 4
    # The rest stayed queued rather than being thrown away.
    assert len(list(channel.receive())) == 6


def test_channel_receive_leaves_the_rest_queued_when_the_caller_stops_early():
    """A generator, so stopping early does not pay to dequeue the remainder."""
    channel = Channel(queue.Queue())
    for index in range(10):
        channel.send(StatusChanged(text=str(index)))

    first = next(channel.receive())

    assert first == StatusChanged(text="0")
    assert channel.received == 1
    assert len(list(channel.receive())) == 9


def test_channel_receive_does_not_drop_a_falsy_message():
    """The old helper guarded with `if event:` and would have dropped this one."""

    class FalsyMessage:
        def __bool__(self):
            return False

    channel = Channel(queue.Queue())
    message = FalsyMessage()
    channel.send(message)

    assert list(channel.receive()) == [message]


def test_channel_counts_what_it_carries():
    """
    The counters are the channel's own, so anything holding it can read them -
    which a return value from receive() could only have given to the caller
    driving the loop.
    """
    channel = Channel(queue.Queue())
    for index in range(7):
        channel.send(StatusChanged(text=str(index)))

    assert (channel.sent, channel.received) == (7, 0)

    list(channel.receive())

    assert (channel.sent, channel.received) == (7, 7)


# --------------------------------------------------------------------------
# Handler coverage: every message reaches a branch
# --------------------------------------------------------------------------

def unwrapped(instance, method_name):
    """The undecorated handler of `instance`, bound to it.

    @catch_and_report_errors() turns an exception into a ModuleError on the
    module's outbox, which would hide the very failure these tests look for.
    functools.wraps leaves the original behind as __wrapped__ - but only on the
    function, so it has to be looked up on the class and re-bound by hand.
    """
    method = getattr(type(instance), method_name)
    raw = getattr(method, "__wrapped__", method)
    return lambda message: raw(instance, message)


@pytest.fixture
def core():
    """A Core wired to plain queues, so it spawns nothing."""
    return Core(
        to_hmi=Channel(queue.Queue()),
        from_hmi=Channel(queue.Queue()),
        log_queue=queue.Queue(),
        queue_factory=queue.Queue,
    )


@pytest.fixture
def sequencer():
    return Sequencer(to_core=Channel(queue.Queue()), from_core=Channel(queue.Queue()))


@pytest.fixture
def report():
    return Report(to_core=Channel(queue.Queue()), from_core=Channel(queue.Queue()))


@pytest.fixture
def hmi_client():
    return HmiClient(to_core=Channel(queue.Queue()), from_core=Channel(queue.Queue()))


@pytest.fixture
def logger(tmp_path):
    instance = Logger(queue.Queue(), str(tmp_path / "run.log"), stdout_enabled=False)
    yield instance
    instance.close()


def recipients(core, sequencer, report, hmi_client, logger):
    """Every (link, handler) pair in the framework."""
    return {
        "HmiToCore": unwrapped(core, "handle_hmi_message"),
        "SequencerToCore": unwrapped(core, "handle_sequencer_message"),
        "ReportToCore": unwrapped(core, "handle_report_message"),
        "CoreToSequencer": unwrapped(sequencer, "handle_core_message"),
        "CoreToReport": unwrapped(report, "handle_core_message"),
        "CoreToHmi": unwrapped(hmi_client, "handle_core_message"),
        "LoggerControl": unwrapped(logger, "handle_control_message"),
    }


@pytest.mark.parametrize("link_name", list(LINKS), ids=list(LINKS))
def test_every_message_in_a_link_is_handled_by_its_recipient(
    link_name, core, sequencer, report, hmi_client, logger
):
    """No message may reach unhandled().

    Both of the defects this replaces were of exactly this shape: a message
    declared on a link with no branch on the receiving side, invisible because
    the handler ended in `case _: pass`.
    """
    handler = recipients(core, sequencer, report, hmi_client, logger)[link_name]

    for message_type in get_args(LINKS[link_name]):
        message = EXAMPLES[message_type]
        try:
            handler(message)
        except UnhandledMessage as exc:
            pytest.fail(f"{link_name}: {message_type.__name__} reached unhandled() - {exc}")


def test_unhandled_is_raised_for_a_message_off_the_link(core):
    """The safety net itself works.

    Without this, a handler that silently accepted anything would pass the test
    above for the wrong reason.
    """
    with pytest.raises(UnhandledMessage):
        unwrapped(core, "handle_report_message")(StatusChanged(text="not a report message"))


# --------------------------------------------------------------------------
# Both frontends answer the protocol identically
# --------------------------------------------------------------------------

#: The protocol half of a frontend. A subclass that overrides any of these is
#: reintroducing the divergence this base class exists to prevent.
SHARED_PROTOCOL_METHODS = (
    "handle_core_message",
    "stop",
    "request_shutdown",
    "answer_user_prompt",
    "answer_serial_number",
)


def frontend_classes():
    """Both frontends, imported lazily so a missing PySide6 skips only the GUI."""
    from pypts.hmi.cli.cli import CLI

    classes = [CLI]
    try:
        from pypts.hmi.gui.gui import GUI

        classes.append(GUI)
    except ImportError:  # pragma: no cover - PySide6 is an optional extra
        pass
    return classes


@pytest.mark.parametrize("frontend", frontend_classes(), ids=lambda cls: cls.__name__)
@pytest.mark.parametrize("method_name", SHARED_PROTOCOL_METHODS)
def test_frontends_do_not_override_the_shared_protocol(frontend, method_name):
    """Presentation is overridden; protocol is not.

    The CLI used to treat StopHmi as "set a flag" while the GUI completed the
    handshake, so Core could never learn that the frontend had stopped in CLI
    mode. Keeping the handler in one place is the fix; this is what stops it
    being undone.
    """
    assert getattr(frontend, method_name) is getattr(HmiClient, method_name), (
        f"{frontend.__name__} overrides {method_name}, which both frontends must share"
    )


def test_frontends_are_hmi_clients():
    """Anything else would have its own copy of the protocol by definition."""
    for frontend in frontend_classes():
        assert issubclass(frontend, HmiClient)


def test_stop_from_core_is_acknowledged(hmi_client):
    """The handshake Core waits for before it may exit.

    Core clears its `hmi` flag only on HmiStopped; without this reply it waits
    for a module that has already gone and is killed by the launcher instead.
    """
    outbox = queue.Queue()
    hmi_client.core = Channel(outbox)

    hmi_client.handle_core_message(StopHmi())

    assert hmi_client.running is False
    assert isinstance(outbox.get_nowait(), HmiStopped)


def test_requesting_shutdown_asks_core_rather_than_leaving(hmi_client):
    """A frontend never stops itself - it asks, and Core brings everything down
    in order. Leaving on its own is what orphaned the Sequencer and the Report.
    """
    outbox = queue.Queue()
    hmi_client.core = Channel(outbox)

    hmi_client.request_shutdown()

    assert isinstance(outbox.get_nowait(), ShutdownRequested)
    assert hmi_client.running is True
