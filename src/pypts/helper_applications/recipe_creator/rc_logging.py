"""
The Recipe Creator's own log file, and what happens to an error nobody caught.

The Creator is a separate program from pypts: it has no Logger process and no
run log. It writes `recipe_creator_<YYYYmmdd_HHMMSS>.log` into the reports
folder pypts uses (`paths.reports_dir`), at DEBUG, so a crash can be traced
afterwards:

- an exception that escapes a Qt slot or the start-up code is logged with its
  traceback, and a dialog tells the user the Creator is still running and
  where the details are, instead of the error vanishing into a console;
- a hard crash inside Qt (no Python exception at all) is written to the same
  file by `faulthandler`, with the Python stack of every thread.
"""

from __future__ import annotations

import faulthandler
import logging
import sys
from pathlib import Path
from types import TracebackType
from typing import IO

from PySide6.QtWidgets import QApplication, QMessageBox

from pypts.config_handler import ConfigError, ConfigHandler, file_locations
from pypts.logger.log import build_formatter, init_logging
from pypts.utilities.local_storage import get_log_file_path

log = logging.getLogger(__name__)

#: The start of the Creator's log file name; pypts' own logs start with "pypts".
LOG_FILE_PREFIX = "recipe_creator"

# Kept open for the whole life of the program: faulthandler writes to it at the
# moment of a crash, when nothing can be opened any more.
_fault_file: IO[str] | None = None

# Where the log is, and which program this is, for the error dialog.
_log_path = ""
_program_name = "The Recipe Creator"


def start_logging(
    prefix: str = LOG_FILE_PREFIX, program_name: str = "The Recipe Creator"
) -> str:
    """
    Log to the program's own file (and stdout), and catch what nobody caught.

    Called once, first thing in main(). `prefix` starts the file name: the
    Creator keeps the default, the Recipe Editor v2 passes "recipe_editor".
    `program_name` is how the log and the error dialog name the program.
    Returns the log file's path.
    """
    global _fault_file, _log_path, _program_name

    _program_name = program_name

    _log_path = get_log_file_path(_reports_dir(), prefix=prefix)

    root = init_logging(level=logging.DEBUG)
    file_handler = logging.FileHandler(_log_path, encoding="utf-8")
    file_handler.setFormatter(build_formatter())
    root.addHandler(file_handler)

    _fault_file = open(_log_path, "a", encoding="utf-8")  # noqa: SIM115 - open until exit
    faulthandler.enable(file=_fault_file, all_threads=True)

    sys.excepthook = _report_uncaught_error
    return _log_path


def _reports_dir() -> Path:
    """`paths.reports_dir`, or the default one when there is no configuration to read."""
    try:
        return Path(ConfigHandler().get_parameter("paths.reports_dir"))
    except ConfigError:
        return file_locations.default_data_dir() / "reports"


def _report_uncaught_error(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    """
    sys.excepthook: log an error nobody caught and tell the user.

    PySide hands an exception raised in a slot here and then carries on, so
    the window stays open; the dialog says so.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    log.error("%s hit an unexpected error: %s", _program_name, exc_value)
    log.debug(
        "Traceback for the unexpected error:",
        exc_info=(exc_type, exc_value, exc_traceback),
    )

    if QApplication.instance() is None:
        return
    try:
        QMessageBox.critical(
            QApplication.activeWindow(),
            "Unexpected error",
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"{_program_name} is still running, but save your work under a new "
            "name to be safe.\n\n"
            f"The details are in:\n{_log_path}",
        )
    except Exception:
        # The dialog itself failed; the error is in the log already.
        log.debug("The unexpected-error dialog could not be shown.", exc_info=True)
