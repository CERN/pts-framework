# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Following the run log while the Logger is still writing it.

Two jobs, both small and both about files rather than about pypts: find the log
of the run you meant, and hand out its lines as they appear.

Reading a file another process holds open works on both platforms here. The
Logger opens it through `logging.FileHandler(mode="a", encoding="utf-8")`, which
on Windows leaves the default share mode in place, so a reader is allowed. This
is a plain read - nothing here writes, locks, or truncates, and closing the
Monitor cannot affect the run.

The one thing that needs care is the tail of the file. A record is written by one
`write()` followed by a flush, but a read can still land between them and return
half a line. Anything not ending in a newline is therefore held back until the
rest of it arrives, which is why `read_lines()` returns complete lines only and
never a torn record.
"""

from pathlib import Path

from pypts.utilities.local_storage import LOG_FILE_PREFIX

#: The run logs, as `local_storage.get_log_file_path()` names them:
#: `pypts_YYYYmmdd_HHMMSS.log`. The timestamp is fixed-width, so sorting by name
#: sorts by time - but mtime is used anyway, because a log that is still being
#: written is the interesting one whatever it is called.
LOG_GLOB = f"{LOG_FILE_PREFIX}_*.log"


def default_logs_dir() -> Path:
    """
    Where the framework puts run logs, according to the configuration.

    Read through `ConfigHandler` like any other process would. Reading is pure -
    only the launcher's `bootstrap()` may create or repair the file - so asking
    from a separate tool cannot disturb a run in progress, and a Monitor started
    before pypts has ever run raises rather than quietly inventing a path.

    Imported inside the function rather than at module scope so that the parser
    and the liveness fold stay importable without touching the configuration,
    which is what keeps their tests free of it.
    """
    from pypts.config_handler.config_handler import ConfigHandler

    return Path(ConfigHandler().get_parameter("paths.logs_dir"))


def find_latest_log(logs_dir: Path) -> Path | None:
    """
    The most recently modified run log in a directory, or None if there is none.

    Modification time rather than name: the newest file by name is the newest
    run that *started*, which is the same thing right up until someone opens two.
    """
    logs = list(Path(logs_dir).glob(LOG_GLOB))
    if not logs:
        return None
    return max(logs, key=lambda path: path.stat().st_mtime)


class LogFollower:
    """
    A file, read forwards, repeatedly.

    Open it once and call `read_lines()` as often as you like; each call returns
    whatever whole lines have appeared since the last one. An idle call costs one
    read that returns nothing.

    It does not poll on its own - the caller owns the timer. In the Monitor that
    is the window's QTimer, so the follower never needs a thread and the GUI
    never waits on a file.
    """

    def __init__(self, path) -> None:
        self.path = Path(path)
        self._handle = None
        #: The tail of the file that is not yet a whole line.
        self._partial = ""

    def open(self) -> None:
        """
        Open the file for reading, positioned at the start.

        `errors="replace"` rather than the default: the Logger pins UTF-8 when it
        writes, but a log that was truncated mid-character, or one written by an
        older build on a machine with a different locale, must still be readable.
        A tool that refuses to open a broken log is useless exactly when it is
        needed.
        """
        self.close()
        self._handle = self.path.open("r", encoding="utf-8", errors="replace")
        self._partial = ""

    def read_lines(self) -> list[str]:
        """
        Every whole line that has appeared since the last call.

        Returns:
            The lines, without their terminators. A partial trailing line is kept
            for next time rather than returned, so a caller never sees half a
            record.
        """
        if self._handle is None:
            return []

        text = self._partial + self._handle.read()
        if not text:
            return []

        lines = text.split("\n")
        # The last element is whatever followed the final newline: "" when the
        # file ends cleanly, the start of the next record when it does not.
        self._partial = lines.pop()

        return [line.rstrip("\r") for line in lines]

    def close(self) -> None:
        """Release the file. Safe to call twice, and safe to call before open()."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None
