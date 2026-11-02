import logging

import numpy as np
from PySide6.QtCore import QObject, Signal

from pyrade_xy_graph.core import trace_level  # noqa: F401  (registers Logger.trace())

log = logging.getLogger(__name__)


class _RingColumn:
    """
    Amortized-growth column buffer backing one DataStore column.

    Over-allocates capacity and only compacts (dropping the oldest
    samples down to max_len) once that slack is used up - the same
    doubling trick behind Python's own list/str growth. Appending is
    O(1) amortized; a plain concatenate-and-trim on every append would
    be O(max_len) per call once a column is near capacity.
    """

    _MIN_CAPACITY = 64

    def __init__(self, max_len: int | None, dtype=np.float64):
        self.max_len = max_len
        self._dtype = dtype
        self._buf = np.empty(0, dtype=dtype)
        self._len = 0
        # Slack retained beyond max_len before compaction is forced -
        # 12.5% of max_len (min 4096 samples).
        self._slack = max(max_len // 8, 4096) if max_len is not None else 0

    @property
    def array(self) -> np.ndarray:
        """View of the retained samples, capped at max_len. The
        physical buffer can run ahead of max_len into the slack margin
        between reallocations (see append/_grow); this always windows
        down to the last max_len samples regardless."""
        if self.max_len is not None and self._len > self.max_len:
            return self._buf[self._len - self.max_len:self._len]
        return self._buf[:self._len]

    def __len__(self) -> int:
        if self.max_len is not None:
            return min(self._len, self.max_len)
        return self._len

    def append(self, values: np.ndarray):
        values = np.asarray(values, dtype=self._dtype)
        n = len(values)
        if n == 0:
            return

        if self._len + n > len(self._buf):
            self._grow(self._len + n)

        self._buf[self._len:self._len + n] = values
        self._len += n
        # No drop-oldest step here: array()/__len__ already cap what
        # callers see at max_len, so _len can run past it into the
        # slack _grow reserved - that's what makes the amortized cost
        # O(1) per append instead of O(max_len) every time.

    def replace(self, values: np.ndarray):
        """Discards existing content and adopts values wholesale (used
        by DataStore.set_data/replace_signal)."""
        self._buf = np.array(values, dtype=self._dtype, copy=True)
        self._len = len(self._buf)

    def _grow(self, min_capacity: int):
        if self.max_len is not None and self._len > self.max_len:
            # Already over max_len: drop everything before the retained
            # window (already unreachable via array()/__len__) and size
            # the replacement for both that drop and fresh slack in one
            # allocation.
            start = self._len - self.max_len
            target = max(self.max_len + self._slack, min_capacity - start, self._MIN_CAPACITY)
            new_buf = np.empty(target, dtype=self._dtype)
            new_buf[:self.max_len] = self._buf[start:self._len]
            self._buf = new_buf
            self._len = self.max_len
            return

        capacity = max(len(self._buf), self._MIN_CAPACITY)
        while capacity < min_capacity:
            capacity *= 2
        if self.max_len is not None:
            # Clamp doubling once it would overshoot max_len + slack, so
            # a long-running live session's capacity stays bounded.
            capped = self.max_len + self._slack
            if capacity > capped:
                capacity = max(capped, min_capacity)

        new_buf = np.empty(capacity, dtype=self._dtype)
        new_buf[:self._len] = self._buf[:self._len]
        self._buf = new_buf


class DataStore(QObject):
    """
    Central in-memory buffer for signal data. Every column is either a
    plottable signal or someone's x-axis - see set_x_key/is_x_column.
    UI code reacts to data_updated and never touches acquisition or
    file-loading internals directly.
    """
    data_updated = Signal()
    buffer_cleared = Signal()

    def __init__(self, parent=None, max_len: int | None = None):
        super().__init__(parent)
        self._data: dict[str, _RingColumn] = {}
        self._units = {}
        # Ring-buffer cap per column, in samples. None = unbounded -
        # fine for a file (already decimated on load); a live session
        # needs this set or RAM grows for the life of the acquisition.
        self.max_len = max_len
        # Per-signal x-axis column name, default 'Time' - matches the
        # live pipeline, where every channel in a record shares one
        # time base. File-loaded channels with independent timebases
        # (e.g. differing TDMS sample rates) register their own x-key
        # instead of being assumed to align with 'Time'.
        self._x_key = {}

    @property
    def columns(self) -> list:
        """Active channel names."""
        return list(self._data.keys())

    def append(self, record: dict):
        """
        Appends a record (dict of floats or dict of 1D arrays).

        Example: {'Time': 0.1, 'Voltage': 3.14}
             or  {'Time': [0.1, 0.2], 'Voltage': [3.14, 3.15]}
        """
        if not record:
            return

        added = 0
        for col, val in record.items():
            new_val = np.atleast_1d(val)
            added = len(new_val)
            if col not in self._data:
                self._data[col] = _RingColumn(self.max_len)
            self._data[col].append(new_val)

        log.trace("append: columns=%s +%d samples each (%d total buffered)",
                   list(record.keys()), added, len(self))
        self.data_updated.emit()

    def set_unit(self, col: str, unit: str):
        """Records the engineering unit string for a channel (for axis labels)."""
        self._units[col] = unit

    def get_unit(self, col: str) -> str:
        return self._units.get(col, '')

    def set_x_key(self, col: str, x_key: str):
        """Registers which column holds col's x-axis values (default 'Time')."""
        self._x_key[col] = x_key

    def get_x_key(self, col: str) -> str:
        return self._x_key.get(col, 'Time')

    def is_x_column(self, col: str) -> bool:
        """True if col is used as someone's x-axis rather than a plottable signal."""
        return col == 'Time' or col in self._x_key.values()

    def get_signal(self, col: str) -> tuple:
        """Returns (x_array, y_array) for col, using its registered x-key."""
        x_key = self.get_x_key(col)
        if x_key not in self._data or col not in self._data:
            return np.array([]), np.array([])
        return self._data[x_key].array, self._data[col].array

    def set_data(self, data: dict):
        """
        Replaces the internal buffer entirely (loading a file).

        Example: {'Time': np.array([...]), 'Voltage': np.array([...])}
        """
        self._data = {}
        for col, arr in data.items():
            column = _RingColumn(self.max_len)
            column.replace(arr)
            self._data[col] = column
        self.data_updated.emit()

    def replace_signal(self, col: str, x_key: str, x_values, y_values):
        """
        Replaces one column's data and its x-key column wholesale,
        without touching any other column - unlike append() (grows a
        column incrementally) or set_data() (replaces everything).

        Used by the "load detail for visible region" action
        (core.binary_results.RangeLoadWorker) to splice a higher-
        resolution read into a file-loaded channel's decimated
        overview. Only safe when x_key belongs exclusively to col
        (never shared, the way live-acquisition columns default to
        sharing 'Time') - every file-loaded channel satisfies this
        since FileLoadWorker gives each channel its own x-key
        (f"{name}#x"). Replacing a shared x-key this way would desync
        every other column that shares it.
        """
        if x_key not in self._data:
            self._data[x_key] = _RingColumn(self.max_len)
        self._data[x_key].replace(x_values)
        if col not in self._data:
            self._data[col] = _RingColumn(self.max_len)
        self._data[col].replace(y_values)
        self._x_key[col] = x_key
        self.data_updated.emit()

    def get_roi(self, x_min: float, x_max: float, x_col: str = 'Time') -> dict:
        """Zero-copy sliced dict of array views within [x_min, x_max],
        via binary search. Assumes x_col is sorted ascending."""
        if x_col not in self._data or len(self._data[x_col]) == 0:
            return {}

        x_array = self._data[x_col].array
        idx_start = np.searchsorted(x_array, x_min, side='left')
        idx_end = np.searchsorted(x_array, x_max, side='right')

        return {
            col: column.array[idx_start:idx_end]
            for col, column in self._data.items()
        }

    def clear(self):
        """Clears all stored data arrays."""
        log.debug("clear: dropping columns %s", list(self._data.keys()))
        self._data.clear()
        self._units.clear()
        self._x_key.clear()
        self.buffer_cleared.emit()
        self.data_updated.emit()

    def __getitem__(self, col: str) -> np.ndarray:
        """Allows direct array access via datastore['Voltage']."""
        return self._data[col].array

    def __contains__(self, col: str) -> bool:
        return col in self._data

    def __len__(self) -> int:
        if not self._data:
            return 0
        first_col = next(iter(self._data))
        return len(self._data[first_col])
