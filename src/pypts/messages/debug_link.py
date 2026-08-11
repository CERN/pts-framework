# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The debug console's two links. Present only under `--mode debug`.

This is the one link in the framework that is not part of the product. It exists
so a developer can watch traffic that is otherwise invisible - CORE <-> Sequencer
and CORE <-> Report both live inside the engine process, where no frontend can
see them - and inject messages into links it has no other way of reaching.

Two directions, deliberately asymmetric:

    everything -> console    TapRecord, one per message sent on any tapped
                             channel. Produced by the tap, never by a module.
    console    -> CORE       InjectMessage, asking CORE to put a message on one
                             of the links it owns.

Nothing in `core/`, `sequencer/` or `report/` may import this module for any
purpose other than handling an injection. If a debug type starts appearing in
product logic, the tooling has grown into the framework and that is a defect.
"""

from dataclasses import dataclass
from enum import Enum

# --- Link names ----------------------------------------------------------------
#
# The `link` given to each Channel, and the value shown in the trace. Defined
# here so the launcher, CORE and the console cannot drift apart on spelling.

HMI_TO_CORE = "hmi->core"
CORE_TO_HMI = "core->hmi"
CORE_TO_SEQUENCER = "core->sequencer"
SEQUENCER_TO_CORE = "sequencer->core"
CORE_TO_REPORT = "core->report"
REPORT_TO_CORE = "report->core"

#: Every tapped link, in the order the console lists them.
ALL_LINKS = (
    HMI_TO_CORE,
    CORE_TO_HMI,
    CORE_TO_SEQUENCER,
    SEQUENCER_TO_CORE,
    CORE_TO_REPORT,
    REPORT_TO_CORE,
)


# --- Anything -> console -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TapRecord:
    """
    One message, as it was handed to one channel.

    Carries `payload` as text rather than the message itself, for two reasons.
    A record must always be picklable even when the message it describes is not
    - that is precisely the bug worth seeing rather than crashing on. And the
    console renders it and nothing else: it never needs to reconstruct the
    object, so shipping the object would buy nothing and risk importing engine
    types into the debug process.

    Args:
        timestamp: time.time() at the moment of the send.
        link: which direction, one of the constants above.
        message_type: the message class's name, e.g. "StepFinished".
        payload: repr() of the message.
        injected: True if this send originated from the console rather than
                  from a module doing its job. Keeps a simulated run visibly
                  distinct from a real one in the trace.
    """

    timestamp: float
    link: str
    message_type: str
    payload: str
    injected: bool = False


# --- Console -> CORE -----------------------------------------------------------


class InjectTarget(Enum):
    """
    Which of CORE's links the console wants a message put on.

    Only the five CORE owns. The console is itself the HMI, so it puts messages
    on the hmi->core link by simply sending them, which exercises exactly the
    path a real frontend takes and needs no help from CORE.
    """

    TO_HMI = CORE_TO_HMI
    TO_SEQUENCER = CORE_TO_SEQUENCER
    FROM_SEQUENCER = SEQUENCER_TO_CORE
    TO_REPORT = CORE_TO_REPORT
    FROM_REPORT = REPORT_TO_CORE


@dataclass(frozen=True, slots=True)
class InjectMessage:
    """
    Put `message` on the link named by `target`, as if a module had sent it.

    CORE puts it on the real queue rather than calling the handler directly, so
    an injected message is drained, matched and forwarded by exactly the code a
    real one goes through - which is the point of injecting it. It is also why
    an injection into FROM_SEQUENCER shows up twice in the trace: once inbound,
    and once again when CORE forwards it to the HMI.

    `message` must belong to the union that link carries. Nothing checks that at
    runtime; a message that does not will reach the recipient's `unhandled()`
    and be logged as the error it is, which is a legitimate thing to want to
    test on purpose.
    """

    target: InjectTarget
    message: object


# --- The link ------------------------------------------------------------------

DebugToCore = InjectMessage
