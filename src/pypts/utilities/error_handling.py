# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Reporting a module's failures to CORE.

Two decorators, because a failure means two different things depending on where
it happens - and one decorator that did both was the open item roadmap Phase 0
listed as "harden catch_and_report_errors".

`@catch_and_report_errors()` **reports and continues**. It is for event loop
methods, where the alternative is worse: a module that dies on one bad message
stops answering CORE, stops sending heartbeats, and takes the run with it. The
caller gets None and the loop comes round again.

`@report_and_reraise()` **reports and re-raises**. It is for the execution
layer, where swallowing is wrong: a step that fails has to reach a StepResult
with `ResultType.ERROR`, and the sequence has to decide whether to carry on. A
step whose failure is only a log line and a `None` return is a step the report
will call PASS.

The split is deliberately explicit rather than a flag. Which of the two a piece
of code needs is a property of where it sits, so it should be readable at the
call site without checking an argument.

Both need the decorated method to belong to a class with a `core` attribute -
that module's outbox to CORE - and both survive it being absent, because an
error handler that raises AttributeError while handling an error destroys the
one thing worth keeping: what actually went wrong.
"""

import traceback
from functools import wraps

from pypts.logger.log import log
from pypts.messages.common_messages import ErrorSeverity, ModuleError


def catch_and_report_errors(module_name: str | None = None):
    """
    Report exceptions raised by a method to CORE, then swallow them.

    For event loops and the housekeeping around them. The method returns None
    and the caller carries on.

    Args:
        module_name: value for ModuleError.source. Defaults to the module the
                     decorated function was defined in.
    """

    def decorator(func):
        # Resolved once, at decoration time, from the function itself. Detecting
        # it from the call stack instead made the reported source depend on who
        # happened to call the function first.
        source = module_name or func.__module__

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - catching everything is the point
                report_error(self, source, exc)

        return wrapper

    return decorator


def report_and_reraise(module_name: str | None = None):
    """
    Report exceptions raised by a method to CORE, then let them propagate.

    For the execution layer. The caller sees the original exception, with its
    traceback intact, and is expected to turn it into a result rather than
    treat it as the end of the module.

    Args:
        module_name: value for ModuleError.source. Defaults to the module the
                     decorated function was defined in.
    """

    def decorator(func):
        source = module_name or func.__module__

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:
                report_error(self, source, exc)
                # Bare `raise`, not `raise exc`: the original traceback is the
                # thing a step's result has to carry.
                raise

        return wrapper

    return decorator


def report_error(instance, source: str, exc: Exception) -> None:
    """
    Send one ModuleError to CORE on behalf of `instance`.

    Falls back to the log when the instance has no outbox. A driver, a helper
    or a half-built object under test can be decorated without CORE existing at
    all, and in that case the failure must still be recorded - reporting it is
    what this is for, and raising AttributeError here would replace the real
    exception with a much less interesting one.
    """
    outbox = getattr(instance, "core", None)
    if outbox is None:
        log.error(
            "%s: %s (not reported to CORE: %s has no outbox)\n%s",
            source,
            exc,
            type(instance).__name__,
            traceback.format_exc(),
        )
        return

    outbox.send(
        ModuleError(
            source=source,
            severity=ErrorSeverity.ERROR,
            message=str(exc),
            exception=repr(exc),
            traceback=traceback.format_exc(),
        )
    )
