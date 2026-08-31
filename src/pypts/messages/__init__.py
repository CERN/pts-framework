# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Everything the modules say to each other. One module per link, both directions;
see messages.md for the catalogue.

Almost nothing is re-exported: import a message from the link module that owns
it, so a reader can tell which contract a name belongs to.
"""

from pypts.messages.queue_wrapper import QueueWrapper, UnhandledMessage, unhandled

__all__ = ["QueueWrapper", "UnhandledMessage", "unhandled"]
