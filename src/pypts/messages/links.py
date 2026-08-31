# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The name of every direction, passed to `QueueWrapper(link=...)` and printed in
every trace line. Imports nothing, so `messages` and `logger` share it freely.
"""

HMI_TO_CORE = "hmi->core"
CORE_TO_HMI = "core->hmi"
CORE_TO_SEQUENCER = "core->sequencer"
SEQUENCER_TO_CORE = "sequencer->core"
CORE_TO_REPORT = "core->report"
REPORT_TO_CORE = "report->core"

#: Not a link between two modules, but named here so no QueueWrapper is anonymous.
ANY_TO_LOGGER = "any->logger"
