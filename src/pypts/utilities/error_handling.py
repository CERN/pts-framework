# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Reporting a module's failures to CORE.
"""

import traceback
from functools import wraps

from pypts.messages.common import ErrorSeverity, ModuleError


def catch_and_report_errors(module_name: str | None = None):
    """
    Catch exceptions raised by a method and report them to CORE as a ModuleError.

    The decorated method must belong to a class with a `core` attribute holding
    that module's outbox to CORE - every module except CORE itself, which is the
    thing errors are reported *to*.

    Args:
        module_name: value for ModuleError.source. Defaults to the module the
                     decorated function was defined in.

    Note the exception is swallowed: the method returns None and the caller
    carries on. That is survivable for an event loop and wrong for a step, whose
    failure has to reach a StepResult as well. Settling that policy per layer is
    an open item in the roadmap.
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
                self.core.send(
                    ModuleError(
                        source=source,
                        severity=ErrorSeverity.ERROR,
                        message=str(exc),
                        exception=repr(exc),
                        traceback=traceback.format_exc(),
                    )
                )

        return wrapper

    return decorator
