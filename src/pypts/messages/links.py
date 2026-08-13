# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The name of every direction in the framework.

One string per link, defined once so that the launcher, CORE and anyone reading
a log cannot drift apart on spelling. They are given to `QueueWrapper(link=...)` by
whoever builds the QueueWrapper, and they are what a trace line is identified by:

    ...;DEBUG;Core;queue_wrapper.py:send;send core->sequencer RunSequence(...)

so `grep 'sequencer->core' pypts_*.log` is the whole-system view of one link.

Deliberately plain strings and nothing else. This module imports nothing, which
is what lets both `messages` and `logger` use it without a cycle.
"""

HMI_TO_CORE = "hmi->core"
CORE_TO_HMI = "core->hmi"
CORE_TO_SEQUENCER = "core->sequencer"
SEQUENCER_TO_CORE = "sequencer->core"
CORE_TO_REPORT = "core->report"
REPORT_TO_CORE = "report->core"

#: Not a link between two modules but the one path out of every process, so it
#: is named here with the rest rather than being the one anonymous QueueWrapper.
ANY_TO_LOGGER = "any->logger"
