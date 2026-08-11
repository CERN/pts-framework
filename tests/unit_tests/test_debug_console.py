# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the debug console (src/pypts/hmi/debug/).

Two things are worth pinning down, and they pull in opposite directions.

The tap sits on `Channel.send()` - the path every message in the framework takes
- so the tests that matter most are the ones asserting it costs nothing when it
is absent and breaks nothing when it fails. A debug tool that can take a run
down is worse than no debug tool.

The other is that an injected message is genuinely routed. The whole claim of
this feature is that simulating a StepFinished exercises CORE's real handler and
CORE's real forwarding, rather than drawing a row in a table; if that stopped
being true the console would quietly become a mock, and a mock that looks like
the real thing is how you end up trusting a test that proves nothing.

The form tests need Qt and are skipped without it, as in test_hmi_gui.py.
"""

import queue
from typing import get_args
from uuid import uuid4

import pytest

from pypts.core.core import Core
from pypts.hmi.debug.tap import ChannelTap
from pypts.messages import Channel
from pypts.messages.common import ResultType, StepOutcome
from pypts.messages.debug_link import (
    CORE_TO_HMI,
    HMI_TO_CORE,
    SEQUENCER_TO_CORE,
    InjectMessage,
    InjectTarget,
)
from pypts.messages.hmi_link import StatusChanged
from pypts.messages.run_events import StepFinished


@pytest.fixture
def tap():
    """A ChannelTap over a plain queue, plus the queue to read records from."""
    records: queue.Queue = queue.Queue()
    return ChannelTap(records), records


def collect(records: queue.Queue) -> list:
    out = []
    while True:
        try:
            out.append(records.get_nowait())
        except queue.Empty:
            return out


# --- The tap ------------------------------------------------------------------


def test_channel_is_unobserved_by_default():
    """The normal construction must be exactly what it was before the tap existed."""
    outbox: queue.Queue = queue.Queue()
    channel = Channel(outbox)

    channel.send(StatusChanged("hello"))

    assert channel.link == ""
    assert channel._observer is None
    assert outbox.get_nowait() == StatusChanged("hello")


def test_tap_records_the_link_and_the_message(tap):
    observer, records = tap
    channel = Channel(queue.Queue(), link=CORE_TO_HMI, observer=observer)

    channel.send(StatusChanged("ready"))

    (record,) = collect(records)
    assert record.link == CORE_TO_HMI
    assert record.message_type == "StatusChanged"
    assert "ready" in record.payload
    assert record.injected is False


def test_a_failing_tap_does_not_stop_the_message():
    """
    The property the whole design rests on.

    An observer that raises stands in for a full debug queue, a console that has
    died, or a message that cannot be pickled to reach it. None of those may cost
    the sender anything but a trace line.
    """

    def broken(link, message):
        raise RuntimeError("the console went away")

    outbox: queue.Queue = queue.Queue()
    channel = Channel(outbox, link=CORE_TO_HMI, observer=broken)

    channel.send(StatusChanged("still delivered"))

    assert outbox.get_nowait() == StatusChanged("still delivered")


def test_long_payloads_are_truncated(tap):
    """A RunFinished with hundreds of outcomes must not put a novel in the table."""
    observer, records = tap
    channel = Channel(queue.Queue(), link=CORE_TO_HMI, observer=observer)

    channel.send(StatusChanged("x" * 10_000))

    (record,) = collect(records)
    assert len(record.payload) < 10_000
    assert record.payload.endswith("chars]")


def test_marking_injected_restores_the_previous_value(tap):
    observer, _ = tap

    with observer.marking_injected():
        assert observer.injecting is True
        with observer.marking_injected():
            assert observer.injecting is True
        # The inner block must not clear the outer mark on the way out.
        assert observer.injecting is True

    assert observer.injecting is False


# --- Injection through CORE ----------------------------------------------------


@pytest.fixture
def core_with_debug(tap):
    """
    A CORE that spawns nothing, with the tap on all six links and a debug inbox.

    queue_factory=queue.Queue is the same seam the roadmap's thread migration
    turns, and it is what lets this run in-process.
    """
    observer, records = tap
    to_hmi: queue.Queue = queue.Queue()
    debug: queue.Queue = queue.Queue()

    core = Core(
        to_hmi=Channel(to_hmi, link=CORE_TO_HMI, observer=observer),
        from_hmi=Channel(queue.Queue(), link=HMI_TO_CORE, observer=observer),
        log_queue=None,
        queue_factory=queue.Queue,
        tap=observer,
        debug_inbox=Channel(debug),
    )
    return core, Channel(debug), to_hmi, records


def test_injected_sequencer_event_is_really_routed_to_the_hmi(core_with_debug):
    """
    The claim the feature makes: injection goes through CORE's real routing.

    Two polls are needed and that is not incidental. The first drains the debug
    inbox and puts the message on the sequencer->core queue; the second drains
    that queue and runs handle_sequencer_message, which is the code under test.
    """
    core, debug, to_hmi, _ = core_with_debug
    outcome = StepOutcome(
        step_id=uuid4(), step_name="Measure Vout", result=ResultType.FAIL, error_info="4.31 V"
    )

    debug.send(InjectMessage(target=InjectTarget.FROM_SEQUENCER, message=StepFinished(outcome)))
    core.poll_all_sources()
    core.poll_all_sources()

    assert to_hmi.get_nowait() == StepFinished(outcome)


def test_only_the_injected_send_is_marked(core_with_debug):
    """
    An injection is marked; what CORE does about it is real traffic and is not.

    Without this the trace would brand CORE's genuine forwarding as simulated,
    which is precisely the distinction the flag exists to preserve.
    """
    core, debug, _, records = core_with_debug

    debug.send(
        InjectMessage(
            target=InjectTarget.FROM_SEQUENCER,
            message=StepFinished(
                StepOutcome(step_id=uuid4(), step_name="s", result=ResultType.PASS)
            ),
        )
    )
    core.poll_all_sources()
    core.poll_all_sources()

    by_link = {record.link: record for record in collect(records)}
    assert by_link[SEQUENCER_TO_CORE].injected is True
    assert by_link[CORE_TO_HMI].injected is False


def test_core_without_a_debug_inbox_still_polls(tap):
    """--mode gui builds CORE with debug_inbox=None; that must remain uneventful."""
    core = Core(
        to_hmi=Channel(queue.Queue()),
        from_hmi=Channel(queue.Queue()),
        log_queue=None,
        queue_factory=queue.Queue,
    )

    core.poll_all_sources()

    assert core.debug_inbox is None
    assert core.tap is None


# --- The generic form ----------------------------------------------------------

pytest.importorskip("PySide6", reason="the debug console is an optional extra")


def test_every_message_type_can_be_built_from_the_form(qapp):
    """
    Exhaustive over all six unions, so a message added later cannot quietly
    become unreachable from the console.

    It asserts constructibility, not that every field got an editor: a field
    with a default and no editor - RunFinished.outcomes - is legitimately left
    at its default. What must never happen is a message the panel refuses to
    send at all.
    """
    from pypts.hmi.debug.inject_panel import LINKS
    from pypts.hmi.debug.message_forms import MessageForm

    unbuildable = []
    for link, (union, _target) in LINKS.items():
        for message_type in get_args(union):
            form = MessageForm(message_type)
            if form.problems:
                unbuildable.append(f"{link}/{message_type.__name__}: {form.problems}")
            else:
                form.build()

    assert not unbuildable, f"messages with no usable form: {unbuildable}"
