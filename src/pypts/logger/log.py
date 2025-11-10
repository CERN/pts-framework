import logging
import sys

_logger = logging.getLogger("myapp")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:  # prevent multiple handlers on reload
    handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d;%(levelname)s;%(filename)s:%(funcName)s;%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    _logger.addHandler(handler)

# Available functions
def runtime(msg, *a, **kw):     _logger.debug(msg, *a, **kw)
def debug(msg, *a, **kw):     _logger.debug(msg, *a, **kw)
def info(msg, *a, **kw):      _logger.info(msg, *a, **kw)
def warning(msg, *a, **kw):   _logger.warning(msg, *a, **kw)
def error(msg, *a, **kw):     _logger.error(msg, *a, **kw)
def critical(msg, *a, **kw):  _logger.critical(msg, *a, **kw)

log = _logger
