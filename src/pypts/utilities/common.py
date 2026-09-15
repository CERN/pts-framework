# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Small helpers with no home of their own.
"""

import contextlib
import signal
from collections.abc import Mapping


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


def describe_value(name: str, value: str, expectation: str = "") -> str:
    """`voltage = 12.1`, or `voltage = 12.1 (range 11 .. 13)` when there is a check."""
    if expectation:
        return f"{name} = {value} ({expectation})"
    return f"{name} = {value}"


def describe_step_values(
    inputs: Mapping[str, str], outputs: Mapping[str, str], expectations: Mapping[str, str]
) -> list[str]:
    """
    A step's values as the console and the step table's tooltip show them.

    At most two lines - `inputs: a = 2, b = 3` and `outputs: sum = 5 (equals 5)` -
    and none for a step with no values. The values are already text: they come
    from StepOutcome, rendered by the step layer.
    """
    lines = []
    if inputs:
        described = [describe_value(name, value) for name, value in inputs.items()]
        lines.append("inputs: " + ", ".join(described))
    if outputs:
        described = [
            describe_value(name, value, expectations.get(name, ""))
            for name, value in outputs.items()
        ]
        lines.append("outputs: " + ", ".join(described))
    return lines
