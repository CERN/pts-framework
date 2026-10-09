# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The one log level pypts adds to the standard ones: TRACE, below DEBUG.

TRACE carries the message trace - every message on every link, as it is sent and
as it is received (`messages/queue_wrapper.py`). DEBUG keeps the developer
detail without it, so a run at DEBUG is not buried under heartbeats.

A module of its own, importing nothing of pypts, because `queue_wrapper.py`
needs the level and cannot import `log.py`, which imports it. The name is
registered on import, so every process that can emit a TRACE record - and
every process that parses "TRACE" from the command line or config.ini - has it.
"""

import logging

#: Below DEBUG (10). 5 is the conventional value for a TRACE level.
TRACE = 5

logging.addLevelName(TRACE, "TRACE")
