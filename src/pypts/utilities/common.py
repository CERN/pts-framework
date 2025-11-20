# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty

def convert_string_to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Cannot convert '{value}' to integer.")
    except TypeError:
        raise TypeError("Input must be a string or number.")


def poll_queue(queue, handler):
    """
    Helper to poll a given queue non-blockingly and call handler on received event.
    Ignores queue.Empty exceptions silently.
    """
    try:
        event = queue.get_nowait()
        if event:
            handler(event)
    except Empty:
        pass

