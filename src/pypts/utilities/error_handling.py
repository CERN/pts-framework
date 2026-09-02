# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Reporting a module's failures to CORE.

Two decorators and two functions, and the split between them is the design:
**the decorators are the net for what nobody expected; the functions are how a
method handles a failure it recognised.**

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

## Handling a specific error where it happens

Everything the decorators send is, by definition, a surprise: they cannot know
what the failure meant, so it is always an ERROR with a traceback attached. A
method that *does* know catches it itself and says so:

    try:
        reading = self.instrument.measure()
    except TimeoutError as exc:
        # The DUT is slow, not broken. Worth recording, not worth alarming
        # the operator with.
        report_error(self, exc, severity=ErrorSeverity.WARNING)
        reading = self.retry_measurement()

`report_error()` is for a live exception; `report_problem()` is for a failure
with no exception behind it - a refused command, an instrument answering
nonsense - which has no traceback worth sending and gains nothing from being
raised only to be caught again one frame later.

Anything the method does not recognise falls through to its decorator, which is
what the decorator is for. Neither function raises, so the raise site keeps
control of what happens next; that decision belongs to it and not here.

All four need the decorated method to belong to a class with a `core` attribute
- that module's outbox to CORE - and all four survive it being absent, because
an error handler that raises AttributeError while handling an error destroys the
one thing worth keeping: what actually went wrong.

## What reaches the log, and at which level

Nothing here writes the operator's line: the ModuleError goes to CORE, and CORE
logs it as two records - one the operator can read, one at DEBUG with the
traceback (logger.md section 7). The only exception is the fallback below, for
an object with no outbox, which has to write both records itself because there
is nobody to send them to.

`message` is therefore operator-facing text. `report_error()` fills it from
`str(exc)`, which is as friendly as an arbitrary exception gets; CORE frames it
with the name of the module that failed. `report_problem()` writes it by hand,
so a refusal should be phrased for the technician reading the panel, not for the
developer who wrote the check.
"""

import traceback
from functools import wraps

from pypts.logger.log import log
from pypts.messages.common_messages import ErrorSeverity, ModuleError


def catch_and_report_errors(
    module_name: str | None = None, severity: ErrorSeverity = ErrorSeverity.ERROR
):
    """
    Report exceptions raised by a method to CORE, then swallow them.

    For event loops and the housekeeping around them. The method returns None
    and the caller carries on.

    Args:
        module_name: value for ModuleError.source. Defaults to the module the
                     decorated function was defined in.
        severity: how bad an unexpected failure in this method is. The default
                  suits almost everything; a method whose failure is routine can
                  say so once, here, instead of at every raise site inside it.
    """

    def decorator(func):
        # Resolved once, at decoration time, from the function itself. Detecting
        # it from the call stack instead made the reported source depend on who
        # happened to call the function first.
        source = module_name or func.__module__
        operation = func.__qualname__

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - catching everything is the point
                report_error(
                    self, exc, severity=severity, source=source, operation=operation
                )

        return wrapper

    return decorator


def report_and_reraise(
    module_name: str | None = None, severity: ErrorSeverity = ErrorSeverity.ERROR
):
    """
    Report exceptions raised by a method to CORE, then let them propagate.

    For the execution layer. The caller sees the original exception, with its
    traceback intact, and is expected to turn it into a result rather than
    treat it as the end of the module.

    Args:
        module_name: value for ModuleError.source. Defaults to the module the
                     decorated function was defined in.
        severity: how bad an unexpected failure in this method is.
    """

    def decorator(func):
        source = module_name or func.__module__
        operation = func.__qualname__

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:
                report_error(
                    self, exc, severity=severity, source=source, operation=operation
                )
                # Bare `raise`, not `raise exc`: the original traceback is the
                # thing a step's result has to carry.
                raise

        return wrapper

    return decorator


def report_error(
    instance,
    exc: Exception,
    *,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    source: str | None = None,
    operation: str = "",
) -> None:
    """
    Send one ModuleError describing `exc` to CORE, on behalf of `instance`.

    Called by both decorators, and by a method that caught something it
    recognised. It reports and returns; it never raises and never re-raises, so
    what happens to the failure afterwards stays the raise site's decision.

    Must be called from inside the `except` block - the traceback comes from
    traceback.format_exc(), which is empty outside one.

    Args:
        instance: the module reporting, i.e. whatever holds the outbox to CORE.
        exc: the exception being reported.
        severity: how the sender rates it. CORE logs at the matching level and
                  shows the operator anything above WARNING.
        source: dotted module name. Defaults to the module `instance`'s class
                was defined in - no call-stack inspection, deliberately.
        operation: qualified name of the failing method. The decorators fill it
                   in; a raise site passes it when the method is worth naming.
    """
    send_module_error(
        instance,
        ModuleError(
            source=source or type(instance).__module__,
            severity=severity,
            message=str(exc),
            exception=repr(exc),
            traceback=traceback.format_exc(),
            operation=operation,
            error_type=type(exc).__name__,
        ),
    )


def report_problem(
    instance,
    message: str,
    *,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    source: str | None = None,
    operation: str = "",
) -> None:
    """
    Send one ModuleError to CORE for a failure with no exception behind it.

    A command the module refuses, a device answering something impossible: a
    fact worth reporting that nothing raised. Raising an exception purely to
    catch it one frame later would only attach a traceback through the
    framework's own guard, which tells the reader nothing.

    Args:
        message: the one-line summary. There is no exception to take it from.
        instance, severity, source, operation: as report_error().
    """
    send_module_error(
        instance,
        ModuleError(
            source=source or type(instance).__module__,
            severity=severity,
            message=message,
            operation=operation,
        ),
    )


def send_module_error(instance, error: ModuleError) -> None:
    """
    Put one ModuleError on `instance`'s outbox to CORE.

    Falls back to the log when the instance has no outbox. A driver, a helper
    or a half-built object under test can be decorated without CORE existing at
    all, and in that case the failure must still be recorded - reporting it is
    what this is for, and raising AttributeError here would replace the real
    exception with a much less interesting one.
    """
    outbox = getattr(instance, "core", None)
    if outbox is None:
        # Nobody to report to, so this is the one place in the module that has
        # to write the operator's record itself - and the DEBUG one under it,
        # the same two CORE would have written.
        log.error("A problem occurred in the software: %s", error.message)
        log.debug(
            "Not reported to CORE: %s has no outbox. Raised in '%s' (%s).",
            type(instance).__name__,
            error.operation or error.source,
            error.error_type or "no exception",
        )
        if error.traceback:
            log.debug("Traceback:\n%s", error.traceback)
        return

    outbox.send(error)
