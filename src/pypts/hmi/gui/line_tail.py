"""
Whole lines out of a file that is still being written.

The reading `LogTail` and `StreamReader` share: keep the file open between calls
(the open handle is the offset, so nothing is ever re-read from the start) and
hand back only lines that ended in a newline. A write can be seen half done; the
unfinished tail is held back until the rest arrives.

Read-only: nothing here writes, locks or truncates. The caller owns the timer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TextIO


class LineTail:
    """One file, read forwards, repeatedly, a whole line at a time."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._handle: TextIO | None = None
        #: The tail of the file that is not yet a whole line.
        self._partial = ""

    @property
    def is_open(self) -> bool:
        """Whether `open()` has succeeded and `close()` has not been called since."""
        return self._handle is not None

    def open(self) -> None:
        """
        Open the file for reading, positioned at its start.

        `errors="replace"` rather than the default: a file truncated mid-character
        must still be readable. A reader that goes blank on one bad byte is
        useless exactly when it is needed.

        Raises:
            OSError: if the file cannot be opened. The caller decides what that
                means.
        """
        self.close()
        self._handle = self.path.open("r", encoding="utf-8", errors="replace")
        self._partial = ""

    def whole_lines(self) -> list[str]:
        """
        Every complete line that appeared since the last call.

        Returns:
            The lines with their terminators stripped, `\r` included. A trailing
            partial line is held back. Empty when nothing new arrived, or the
            file is not open.
        """
        if self._handle is None:
            return []

        text = self._partial + self._handle.read()
        if not text:
            return []

        lines = text.split("\n")
        # The last element is whatever followed the final newline: "" when the
        # file ends cleanly, the start of the next line when it does not.
        self._partial = lines.pop()
        return [line.rstrip("\r") for line in lines]

    def close(self) -> None:
        """Release the file. Safe to call twice, and safe to call before open()."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None
