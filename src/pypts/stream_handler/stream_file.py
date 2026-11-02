"""
One stream's CSV file: the path rule, the header format and the Stream handle.

The file is the contract between the engine (which writes it) and the GUI's
graph (which tails it): `x,y [<unit>]` on the first line, then one `x,y` row per
sample. This module imports nothing of pypts - test code reaches it through
`pypts.stream_handler` and a script of one's own may use it with no PyPTS around.
"""

import csv
import logging
import numbers
import os
import threading
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

#: The folder, inside a run folder, that holds the run's stream files.
STREAMS_FOLDER = "streams"

_MAX_NAME_LENGTH = 60


def _safe_name(name: str) -> str:
    """Alphanumerics kept, every other character an underscore, at most 60 characters."""
    return "".join(c if c.isalnum() else "_" for c in name)[:_MAX_NAME_LENGTH]


def stream_csv_path(folder: str | os.PathLike[str], name: str) -> Path:
    """The CSV file of the stream `name` in the run folder `folder`."""
    return Path(folder) / STREAMS_FOLDER / (_safe_name(name) + ".csv")


def unit_from_header(fields: list[str]) -> str | None:
    """The unit named by a stream file's header row: `["x", "y [V]"]` gives `"V"`."""
    if len(fields) < 2:
        return None
    label = fields[1].strip()
    if label.endswith("]") and "[" in label:
        unit = label[label.index("[") + 1 : -1].strip()
        if unit:
            return unit
    return None


class Stream:
    """
    A named series of (x, y) samples, written to a CSV file as they are pushed.

    Thread-safe: test code may push from threads of its own. A stream with
    `path` None (streams are off for this run) accepts pushes and writes nothing.
    """

    def __init__(self, name: str, path: Path | None, unit: str | None) -> None:
        self.name = name
        self.path = path
        self.unit = unit
        self._lock = threading.Lock()
        self._handle: IO[str] | None = None
        self._writer: Any = None
        self._closed = False
        self._drop_logged = False
        if path is not None:
            self._open(path)

    def _open(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists() or path.stat().st_size == 0
        self._handle = open(path, mode="a", newline="", encoding="utf-8")  # noqa: SIM115
        self._writer = csv.writer(self._handle)
        if is_new:
            if self.unit:
                self._writer.writerow(["x", "y [" + self.unit + "]"])
            else:
                self._writer.writerow(["x", "y"])
            self._handle.flush()

    @property
    def closed(self) -> bool:
        return self._closed

    def push(self, x: Any, y: Any) -> None:
        """
        Add samples: a pair of numbers is one row; two sequences of equal length are many.

        Raises:
            ValueError: the two sequences differ in length.
        """
        if isinstance(x, numbers.Real) and isinstance(y, numbers.Real):
            rows = [(x, y)]
        else:
            if len(x) != len(y):
                raise ValueError(
                    f"Stream '{self.name}': x has {len(x)} samples but y has {len(y)}."
                )
            rows = list(zip(x, y, strict=True))
        with self._lock:
            if self._closed:
                if not self._drop_logged:
                    self._drop_logged = True
                    logger.debug(
                        "Stream '%s' is closed; samples pushed after close are dropped.", self.name
                    )
                return
            if self._writer is None or self._handle is None:
                return
            self._writer.writerows(rows)
            self._handle.flush()

    def close(self) -> None:
        """Close the file. Further pushes are dropped. Calling it again does nothing."""
        with self._lock:
            self._closed = True
            handle = self._handle
            self._handle = None
            self._writer = None
        if handle is not None:
            handle.close()
