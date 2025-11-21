import logging
import sys
import os
import tempfile
from datetime import datetime

class NullStream:
    def write(self, msg):
        pass
    def flush(self):
        pass

formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

for hdlr in list(root_logger.handlers):
    root_logger.removeHandler(hdlr)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
root_logger.addHandler(stream_handler)

# Generate timestamp string for log filename
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

temp_dir = tempfile.gettempdir()
log_file_name = f"pypts_{timestamp_str}.log"
log_file_path = os.path.join(temp_dir, log_file_name)

print(f"Logging to file: {log_file_path}")

file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

def set_stdout_logging_enabled(enabled):
    if enabled:
        stream_handler.stream = sys.stdout
    else:
        stream_handler.stream = NullStream()

def info(msg, *args, **kwargs): root_logger.info(msg, *args, **kwargs)
def debug(msg, *args, **kwargs): root_logger.debug(msg, *args, **kwargs)
def warning(msg, *args, **kwargs): root_logger.warning(msg, *args, **kwargs)
def error(msg, *args, **kwargs): root_logger.error(msg, *args, **kwargs)
def critical(msg, *args, **kwargs): root_logger.critical(msg, *args, **kwargs)

log = root_logger
