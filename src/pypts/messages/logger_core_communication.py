# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""
The Logger -> CORE link: the Logger's heartbeat, and nothing else.

The Logger is a process of its own, so this link crosses a process boundary and
is built by the launcher out of `multiprocessing.Queue`, like HMI <-> CORE.
There is no CORE -> Logger half: what CORE has to say to the Logger is a log
record, and the shared log queue carries those (to_logger_communication.py).

Sender: log.py Logger.main_loop(), through a HeartbeatManager. Receiver:
core.py handle_logger_message(), which feeds CORE's watchdog - a Logger silent
past HEARTBEAT_FATAL_S ends the run like any other module.
"""

from pypts.messages.common_messages import Heartbeat

# --- The link ------------------------------------------------------------------

LoggerToCore = Heartbeat
