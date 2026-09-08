# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Small helpers with no home of their own.
"""

import contextlib
import signal


def ignore_keyboard_interrupt() -> None:
    """
    Take this child process out of Ctrl+C's reach.

    Ctrl+C at a terminal raises SIGINT in *every* process of the foreground
    group, not just the one the operator is looking at. Each child therefore
    used to die on its own, at the moment the launcher was starting the orderly
    shutdown it owns - so CORE was gone before it could pass StopSequencer and
    StopReport on, and its submodule threads were orphaned. The CLI's own Ctrl+C
    handling (`cli.py`) was already correct and was simply beaten to it.

    The rule this restores is the one already written into the Logger's event
    loop: *the launcher decides when we stop*. It asks through
    `ShutdownRequested`, every module answers, and that handshake stays the only
    way the application ends. A child that cannot hear Ctrl+C cannot short-cut
    it.

    `SIG_IGN` rather than a handler that logs: a Python signal handler runs in
    the main thread between bytecodes, and `logging` takes locks, so a handler
    that logged could deadlock against a log call the same thread was already
    making. Ignoring is the only async-signal-safe answer.

    The launcher itself deliberately does **not** call this - it is the process
    that must still hear Ctrl+C. Nor does this leave a wedged child
    unkillable: `stop_core()` terminates after its timeout, and SIGTERM and
    SIGKILL are untouched.

    Best effort: `signal.signal()` only works on the main thread of the main
    interpreter, and every caller is a process entry point. A caller that is not
    keeps the default handling rather than failing.
    """
    # ValueError means this is not the main thread, so there is no handler to
    # install. Nothing to do, and nothing worth failing a run over.
    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def convert_string_to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        # `from None` rather than bare `raise`: the message below says everything
        # the original did, so chaining would only add "During handling of the
        # above exception..." to what the caller sees.
        raise ValueError(f"Cannot convert '{value}' to integer.") from None
    except TypeError:
        raise TypeError("Input must be a string or number.") from None
