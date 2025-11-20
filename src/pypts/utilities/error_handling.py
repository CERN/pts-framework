import traceback
import inspect
from pypts.common.COMMON_MESSAGES import ModuleErrorEvent, ErrorSeverity
from pypts.logger.log import log
from functools import wraps

def catch_and_report_errors(module_name=None):
    """
    Decorator to catch and report exceptions to Core module.
    If no module_name is provided, automatically detect it from the caller's module.

    This decorator wraps the decorated function, executing it inside a try-except block.
    If an exception occurs, it captures and logs detailed traceback information,
    then creates a ModuleErrorEvent reporting this exception and sends it to Core via 'self.core.report_error'.

    Args:
      module_name (str, optional): Name of the module using the decorator.
                                   If not provided, it is detected from the caller's context.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            nonlocal module_name
            # Infer module name automatically if not explicitly provided
            if module_name is None:
                # Inspect the call stack; index 1 gives caller of the wrapper
                frame = inspect.stack()[1]
                module = inspect.getmodule(frame[0])
                if module and module.__name__:
                    module_name = module.__name__
                else:
                    # Fallback to filename if module name unavailable
                    module_name = frame.filename

            try:
                # Call the original function with all arguments
                return func(self, *args, **kwargs)
            except Exception as e:
                # Capture full traceback as a string
                tb = traceback.format_exc()

                # Log the error with traceback for diagnostics
                # log.error(f"Exception in {module_name}: {e}\n{tb}")

                # Create an error event encapsulating all relevant info
                error_event = ModuleErrorEvent(
                    source=module_name,
                    severity=ErrorSeverity.ERROR,
                    message=str(e),
                    exception=repr(e),
                    traceback=tb
                )

                # Send the error event to Core for centralized handling
                self.core.report_error(error_event)
        return wrapper
    return decorator
