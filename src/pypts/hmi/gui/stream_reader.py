"""
Reading a stream CSV back, for the XY graph. No Qt.

CORE writes `<folder>/streams/<name>.csv` (see `pypts.stream_handler`): a header
`x,y [<unit>]` or `x,y`, then one `x,y` row per sample. The GUI follows that file
with `StreamReader`, which returns only the rows that are new since the last
poll, or reads it in one go with `read_whole_stream()` for a look-back.
"""

from __future__ import annotations

import csv
import logging
import math
from pathlib import Path

import numpy as np

from pypts.hmi.gui.line_tail import LineTail
from pypts.stream_handler import unit_from_header

logger = logging.getLogger(__name__)


def _empty() -> tuple[np.ndarray, np.ndarray]:
    return np.empty(0, dtype=float), np.empty(0, dtype=float)


class StreamReader:
    """
    One stream CSV, followed as it grows.

    Call `poll()` as often as you like; each call returns the rows completed
    since the last one. The file may not exist yet - the first poll that finds it
    opens it.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        #: The unit named by the header, None until the header is read or when it has none.
        self.unit: str | None = None
        self._tail = LineTail(self.path)
        self._header_read = False

    @property
    def exists(self) -> bool:
        """Whether the file has been found and opened."""
        return self._tail.is_open

    def poll(self) -> tuple[np.ndarray, np.ndarray]:
        """
        The new complete rows as float arrays `(x, y)`; both empty when none.

        A row that does not parse is skipped, with a DEBUG line.
        """
        if not self._tail.is_open:
            try:
                self._tail.open()
            except OSError:
                return _empty()

        xs: list[float] = []
        ys: list[float] = []
        for line in self._tail.whole_lines():
            if not self._header_read:
                self._header_read = True
                self._read_header(line)
                continue
            row = self._parse_row(line)
            if row is not None:
                xs.append(row[0])
                ys.append(row[1])
        return np.array(xs, dtype=float), np.array(ys, dtype=float)

    def _read_header(self, line: str) -> None:
        for fields in csv.reader([line]):
            self.unit = unit_from_header(fields)

    def _parse_row(self, line: str) -> tuple[float, float] | None:
        fields = line.split(",")
        if len(fields) != 2:
            logger.debug("Stream %s: skipping row %r, not two fields", self.path.name, line)
            return None
        try:
            x = float(fields[0])
            y = float(fields[1])
        except ValueError:
            logger.debug("Stream %s: skipping row %r, not numbers", self.path.name, line)
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            logger.debug("Stream %s: skipping row %r, not finite numbers", self.path.name, line)
            return None
        return x, y

    def close(self) -> None:
        """Release the file. Safe to call twice."""
        self._tail.close()


def read_whole_stream(path: Path) -> tuple[str | None, np.ndarray, np.ndarray] | None:
    """
    The whole stream file in one read: `(unit, x, y)`, or None if it does not exist.

    For a look-back at a finished step; a stream still being written is read to
    the last complete row.
    """
    reader = StreamReader(path)
    try:
        x, y = reader.poll()
        if not reader.exists:
            return None
        return reader.unit, x, y
    finally:
        reader.close()
