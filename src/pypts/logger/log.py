import logging
import os
import sys
from pypts.utilities.local_storage import get_log_file_path

# Env var used to propagate the chosen log file path to all child processes
# (multiprocessing spawn re-imports this module, so without a shared path each
# subprocess would create its own timestamped log file).
LOG_FILE_ENV_VAR = "PYPTS_LOG_FILE"


class NullStream:
    """A stream object that ignores all writes. Used to disable stdout logging."""
    def write(self, msg):
        pass
    def flush(self):
        pass


_formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger()
log.setLevel(logging.DEBUG)

for _hdlr in list(log.handlers):
    log.removeHandler(_hdlr)

_log_file_path = os.environ.get(LOG_FILE_ENV_VAR)
if _log_file_path is None:
    _log_file_path = get_log_file_path()
    os.environ[LOG_FILE_ENV_VAR] = _log_file_path

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_formatter)
log.addHandler(_stream_handler)

_file_handler = logging.FileHandler(_log_file_path, encoding="utf-8")
_file_handler.setFormatter(_formatter)
log.addHandler(_file_handler)


def set_stdout_logging_enabled(enabled: bool) -> None:
    """Enable or disable logging to stdout by redirecting the stream handler."""
    _stream_handler.stream = sys.stdout if enabled else NullStream()


def info(msg, *args, **kwargs): log.info(msg, *args, **kwargs)
def debug(msg, *args, **kwargs): log.debug(msg, *args, **kwargs)
def warning(msg, *args, **kwargs): log.warning(msg, *args, **kwargs)
def error(msg, *args, **kwargs): log.error(msg, *args, **kwargs)
def critical(msg, *args, **kwargs): log.critical(msg, *args, **kwargs)
