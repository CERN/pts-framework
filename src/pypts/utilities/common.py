# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Small helpers with no home of their own.
"""

import contextlib
import signal
from collections.abc import Mapping
from typing import Any

#: The exit code the GUI process ends with when it wants pypts started again -
#: after Settings > Advanced > Restore default settings deleted config.ini, so
#: that a fresh start recreates it from the template. The launcher reads it
#: once the GUI process has ended
#: (`startup.run_gui()`). Here rather than in either of them because the launcher
#: must not import Qt and the GUI has no business importing the launcher. 75 is
#: EX_TEMPFAIL in sysexits.h - "try again" - and no other pypts exit code.
RESTART_EXIT_CODE = 75


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


#: Words that mark a configuration key as a secret. A key that contains one of
#: them - `password`, `ssh_password`, `key_passphrase` - is never written to a log.
SECRET_KEY_WORDS = ("password", "passphrase", "secret", "token")

#: What a log shows in place of a secret.
MASK = "******"


def is_secret_key(key: str) -> bool:
    """Whether a configuration key holds a secret, by its name."""
    lowered = key.lower()
    return any(word in lowered for word in SECRET_KEY_WORDS)


def masked(settings: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `settings` fit for a log: every secret value replaced by MASK."""
    result: dict[str, Any] = {}
    for key, value in settings.items():
        if is_secret_key(key):
            result[key] = MASK
        else:
            result[key] = value
    return result
