# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Everything the modules say to each other.

One module per *link*, holding both directions of that link, so a whole contract
fits on one screen:

    queuewrapper.py         the single transport: QueueWrapper, unhandled()
    common.py               vocabulary shared by more than one link
    run_events.py           what the engine reports while a recipe runs
    core_hmi_link.py        CORE <-> HMI        (the only process boundary)
    core_sequencer_link.py  CORE <-> Sequencer  (thread of the Core process)
    core_report_link.py     CORE <-> Report     (thread of the Core process)
    to_logger_link.py       any   -> Logger     (deliberately not CORE-mediated)
    requests.py             the waiting half of a request/response pair

A link module is named after the two ends it joins, `<a>_<b>_link.py`, and holds
*both* directions - the union CORE sends and the union it receives. The one
exception is the Logger, which is named for its single direction: nothing is
ever sent back.

Adding a message takes two edits: declare the dataclass in the link module and
add it to that link's union, then add a `case` to the recipient's handler. The
type checker finds every other place that has to change - which is the point.

This package intentionally re-exports almost nothing. Import the message you
need from the link module that owns it, so a reader can always tell which
contract a name belongs to:

    from pypts.messages.core_hmi_link import LoadRecipe, StartSequence
"""

from pypts.messages.queuewrapper import QueueWrapper, UnhandledMessage, unhandled

__all__ = ["QueueWrapper", "UnhandledMessage", "unhandled"]
