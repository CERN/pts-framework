# import logging
# import sys
# import os
#
# formatter = logging.Formatter(
#     "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
# )
#
# # Setup root logger
# root_logger = logging.getLogger()
# root_logger.setLevel(logging.DEBUG)
#
# # Remove old handlers if any
# for hdlr in list(root_logger.handlers):
#     root_logger.removeHandler(hdlr)
#
# # Add StreamHandler to output logs to stdout
# stream_handler = logging.StreamHandler(sys.stdout)
# stream_handler.setFormatter(formatter)
# root_logger.addHandler(stream_handler)
#
# # Add file handler to root logger
# file_handler = logging.FileHandler("pypts.log")
# file_handler.setFormatter(formatter)
# root_logger.addHandler(file_handler)
#
# # For convenience, define wrappers around root logger
# def info(msg, *args, **kwargs): root_logger.info(msg, *args, **kwargs)
# def debug(msg, *args, **kwargs): root_logger.debug(msg, *args, **kwargs)
# def warning(msg, *args, **kwargs): root_logger.warning(msg, *args, **kwargs)
# def error(msg, *args, **kwargs): root_logger.error(msg, *args, **kwargs)
# def critical(msg, *args, **kwargs): root_logger.critical(msg, *args, **kwargs)
#
# log = root_logger
#
#
# # todo - logger is broken, need to figure out whats going on, but not today



import logging
import sys
import os

class NullStream:
    """A stream object that ignores all writes."""
    def write(self, msg):
        pass
    def flush(self):
        pass

formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Setup root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Remove old handlers if any
for hdlr in list(root_logger.handlers):
    root_logger.removeHandler(hdlr)

# Create StreamHandler targeting stdout initially
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
root_logger.addHandler(stream_handler)

# Add file handler to root logger
file_handler = logging.FileHandler("pypts.log")
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

def set_stdout_logging_enabled(enabled):
    """Enable or disable stdout logging by swapping stream."""
    if enabled:
        stream_handler.stream = sys.stdout
    else:
        stream_handler.stream = NullStream()

# For convenience, define wrappers around root logger
def info(msg, *args, **kwargs): root_logger.info(msg, *args, **kwargs)
def debug(msg, *args, **kwargs): root_logger.debug(msg, *args, **kwargs)
def warning(msg, *args, **kwargs): root_logger.warning(msg, *args, **kwargs)
def error(msg, *args, **kwargs): root_logger.error(msg, *args, **kwargs)
def critical(msg, *args, **kwargs): root_logger.critical(msg, *args, **kwargs)

log = root_logger
