import logging
import sys
from pypts.utilities.local_storage import get_log_file_path

class NullStream:
    """A stream object that ignores all writes.
    Used here to disable stdout logging by redirecting output to this dummy stream.
    """
    def write(self, msg):
        pass
    def flush(self):
        pass

# Define log message format including timestamp with milliseconds, log level, source file, function, and message
formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Get the root logger and set global minimum log level to DEBUG to capture all levels
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Clear any existing handlers to avoid duplicate logs or conflicts
for hdlr in list(root_logger.handlers):
    root_logger.removeHandler(hdlr)

# Create a stream handler to output logs to stdout (console)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
root_logger.addHandler(stream_handler)

# Get the path for log file from a utility (typically under temp dir with timestamped filename)
log_file_path = get_log_file_path()
print(f"Logging to file: {log_file_path}")

# Create a file handler to log messages into the file with the same formatter
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

def set_stdout_logging_enabled(enabled):
    """
    Enable or disable logging to stdout dynamically by redirecting the stream.
    If disabled, the logs won't appear on console but still get saved to file.
    """
    if enabled:
        stream_handler.stream = sys.stdout
    else:
        stream_handler.stream = NullStream()

# Convenience functions wrapping root logger methods for easy logging usage
def info(msg, *args, **kwargs): root_logger.info(msg, *args, **kwargs)
def debug(msg, *args, **kwargs): root_logger.debug(msg, *args, **kwargs)
def warning(msg, *args, **kwargs): root_logger.warning(msg, *args, **kwargs)
def error(msg, *args, **kwargs): root_logger.error(msg, *args, **kwargs)
def critical(msg, *args, **kwargs): root_logger.critical(msg, *args, **kwargs)

# Export the root logger instance so it can be imported and reused across modules consistently
log = root_logger
