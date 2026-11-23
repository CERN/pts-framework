"""
The HAL server's own log file (spec §9, D16): plain Python logging, standard library only.

One record per line, `;`-separated: the time to the millisecond, the level name, the logger
name, the message. A record whose message runs over several lines (a traceback) continues on
lines that do not match RECORD_START, so a reader can tell the next record from the rest of
this one. The file is flushed after every record, so a reader of the growing file never waits
for a buffer.

start_log_file() puts one handler on the root logger and returns the file's path;
stop_log_file(path) takes it off again and restores the root level (the HAL keeps its file
for its whole life; tests and a second server in one process need the stop).
"""

import logging
import os
import re
import sys
import time
from pathlib import Path

LOG_FORMAT = "%(asctime)s.%(msecs)03d;%(levelname)s;%(name)s;%(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Below DEBUG (10), as PyPTS defines it in `pypts/logger/levels.py`; registered on import.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

#: The start of a record's first line; any other line continues the record before it.
RECORD_START = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3};")

#: The handlers start_log_file() installed, by file path, with the root level before them.
_installed: dict[Path, tuple[logging.Handler, int]] = {}


def default_log_dir() -> Path:
    r"""
    Where the HAL writes its log when no `--log-dir` is given: `%LOCALAPPDATA%\pyhal\logs` on
    Windows, else `$XDG_STATE_HOME/pyhal/logs`, falling back to `~/.local/state/pyhal/logs`.
    """
    if sys.platform == "win32":
        base_text = os.environ.get("LOCALAPPDATA", "")
        if base_text:
            base = Path(base_text)
        else:
            base = Path.home() / "AppData" / "Local"
    else:
        base_text = os.environ.get("XDG_STATE_HOME", "")
        if base_text:
            base = Path(base_text)
        else:
            base = Path.home() / ".local" / "state"
    return base / "pyhal" / "logs"


def start_log_file(log_dir: Path, level: int) -> Path:
    """
    Start a new log file `hal_<YYYYmmdd_HHMMSS>_<pid>.log` in `log_dir` (created if missing):
    a handler on the root logger, flushed per record, and the root logger set to `level`.
    A second file started in the same second gets `_2`, `_3` ... before `.log`; the name is
    claimed by creating the file, so two starts never share one.

    Returns:
        The absolute path of the file.
    """
    folder = Path(log_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"hal_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    path = folder / f"{stem}.log"
    number = 1
    while True:
        try:
            with open(path, "x", encoding="utf-8"):
                pass
            break
        except FileExistsError:
            number = number + 1
            path = folder / f"{stem}_{number}.log"
    # A FileHandler is a StreamHandler, which flushes after every record it writes.
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root = logging.getLogger()
    _installed[path] = (handler, root.level)
    root.addHandler(handler)
    root.setLevel(level)
    return path


def stop_log_file(path: Path) -> None:
    """
    Take the handler of a file start_log_file() started off the root logger, close it, and
    set the root level back to what it was when that file started. `path` may be given in
    any spelling of the file: it is resolved before it is looked up.
    """
    entry = _installed.pop(Path(path).resolve(), None)
    if entry is None:
        return
    handler, previous_level = entry
    root = logging.getLogger()
    root.removeHandler(handler)
    handler.close()
    root.setLevel(previous_level)
