"""
Static file loading (CSV/HDF5/TDMS) and writing/recording of the same
three formats, for both exports and live recording.

Recording goes through one shared mechanism regardless of format: a
small backend per format (_CSVRecorderBackend/_HDF5RecorderBackend/
_TDMSRecorderBackend, each just store()/close()) driven by
RecorderThread, a QThread that drains a queue.Queue - see its docstring
for why recording runs on its own thread.

HDF5 files written by these backends use one resizable float64 dataset
per channel under a top-level "data" group, so reads and writes agree
on layout by construction. An externally-produced HDF5 file without a
"data" group falls back to treating every top-level dataset as a
channel.
"""

import csv
import logging
import os
import queue as queue_module
from math import ceil
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from PySide6.QtCore import QThread, Signal

from pyrade_xy_graph.core import trace_level  # noqa: F401  (registers Logger.trace())
from pyrade_xy_graph.core.math_engine import decimate, needs_decimation

log = logging.getLogger(__name__)

X_COLUMN_CANDIDATES = ('time', 't')


def _guess_x_column(columns: list[str]) -> str:
    for col in columns:
        if col.lower() in X_COLUMN_CANDIDATES:
            return col
    return columns[0]


class FileLoadWorker(QThread):
    """
    Reads a CSV/HDF5/TDMS file chunk-by-chunk on a background thread,
    decimating each chunk against a per-channel point budget so opening a
    multi-GB file never materializes it whole in RAM or floods the GUI
    thread with more points than the screen can show.
    """

    chunk_loaded = Signal(str, object, object)   # channel, x_chunk, y_chunk
    channel_unit = Signal(str, str)               # channel, unit
    error = Signal(str)
    finished_all = Signal()

    def __init__(self, path: str, target_points_per_channel: int = 4000,
                 chunk_rows: int = 200_000, decimation_method: str = 'peak', parent=None):
        super().__init__(parent)
        self.path = path
        self.target_points_per_channel = target_points_per_channel
        self.chunk_rows = chunk_rows
        # 'peak' (default), 'mean', or 'subsample' - see
        # core.math_engine.decimate. Same vocabulary
        # ScopePlotWidget.downsample_method uses at render time, applied
        # here at load time instead.
        self.decimation_method = decimation_method
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        ext = Path(self.path).suffix.lower()
        log.debug("FileLoadWorker starting: %s (target_points_per_channel=%d, chunk_rows=%d)",
                  self.path, self.target_points_per_channel, self.chunk_rows)
        try:
            if ext in ('.csv', '.txt'):
                self._load_csv()
            elif ext in ('.h5', '.hdf5'):
                self._load_hdf5()
            elif ext == '.tdms':
                self._load_tdms()
            else:
                log.error("Unsupported file format: %s", ext)
                self.error.emit(f"Unsupported file format: {ext}")
                return
        except Exception as exc:
            log.exception("FileLoadWorker failed loading %s", self.path)
            self.error.emit(str(exc))
            return
        log.debug("FileLoadWorker finished: %s", self.path)
        self.finished_all.emit()

    def _load_csv(self):
        # Two passes: first just to get the row count cheaply (for the
        # per-chunk decimation budget), then the chunked read itself.
        total_rows = sum(1 for _ in open(self.path, 'rb')) - 1
        n_chunks = max(1, -(-total_rows // self.chunk_rows))
        log.debug("CSV: %d rows across %d chunks", total_rows, n_chunks)
        budget_remaining = {}
        chunks_remaining = n_chunks

        for chunk in pd.read_csv(self.path, chunksize=self.chunk_rows):
            if self._stop_requested:
                return
            x_col = _guess_x_column(list(chunk.columns))
            x = chunk[x_col].to_numpy(dtype=np.float64)
            for col in chunk.columns:
                if col == x_col:
                    continue
                if col not in budget_remaining:
                    budget_remaining[col] = self.target_points_per_channel
                per_chunk_budget = max(2, budget_remaining[col] // chunks_remaining)
                y = chunk[col].to_numpy(dtype=np.float64)
                x_out, y_out = decimate(x, y, per_chunk_budget, method=self.decimation_method)
                budget_remaining[col] = max(0, budget_remaining[col] - len(x_out))
                log.trace("CSV chunk: %s -> %d points (chunks_remaining=%d)", col, len(x_out), chunks_remaining)
                self.chunk_loaded.emit(col, x_out, y_out)
            chunks_remaining -= 1

    def _load_hdf5(self):
        with h5py.File(self.path, 'r') as f:
            group = f['data'] if 'data' in f else f
            channel_names = [name for name in group.keys()
                              if isinstance(group[name], h5py.Dataset)]
            if not channel_names:
                self.error.emit("HDF5 file has no channel datasets")
                return

            x_name = _guess_x_column(channel_names)
            x_dataset = group[x_name]
            n = x_dataset.shape[0]
            n_chunks = max(1, -(-n // self.chunk_rows))
            log.debug("HDF5: %d channels, %d samples, %d chunks (x=%r)",
                      len(channel_names) - 1, n, n_chunks, x_name)

            for name in channel_names:
                if name == x_name:
                    continue
                if self._stop_requested:
                    return
                unit = group[name].attrs.get('unit', '')
                if unit:
                    self.channel_unit.emit(name, str(unit))

                y_dataset = group[name]
                budget_remaining = self.target_points_per_channel
                chunks_remaining = n_chunks
                for start in range(0, n, self.chunk_rows):
                    if self._stop_requested:
                        return
                    end = min(start + self.chunk_rows, n)
                    x_chunk = np.asarray(x_dataset[start:end], dtype=np.float64)
                    y_chunk = np.asarray(y_dataset[start:end], dtype=np.float64)
                    per_chunk_budget = max(2, budget_remaining // chunks_remaining)
                    x_out, y_out = decimate(x_chunk, y_chunk, per_chunk_budget, method=self.decimation_method)
                    budget_remaining = max(0, budget_remaining - len(x_out))
                    chunks_remaining -= 1
                    log.trace("HDF5 chunk: %s -> %d points (chunks_remaining=%d)", name, len(x_out), chunks_remaining)
                    self.chunk_loaded.emit(name, x_out, y_out)

    def _load_tdms(self):
        from nptdms import TdmsFile

        with TdmsFile.open(self.path) as tdms:
            channels = []
            for group in tdms.groups():
                for channel in group.channels():
                    channels.append(channel)

            if not channels:
                self.error.emit("TDMS file has no channels")
                return

            names = [ch.name for ch in channels]
            x_name = _guess_x_column(names) if names else None
            x_channel = next((ch for ch in channels if ch.name == x_name), channels[0])
            log.debug("TDMS: %d channels %s (x=%r)", len(names), names, x_name)

            for channel in channels:
                if channel is x_channel:
                    continue
                if self._stop_requested:
                    return
                unit = channel.properties.get('unit_string', '')
                if unit:
                    self.channel_unit.emit(channel.name, str(unit))

                n = len(channel)
                n_chunks = max(1, -(-n // self.chunk_rows))
                budget_remaining = self.target_points_per_channel
                chunks_remaining = n_chunks
                for start in range(0, n, self.chunk_rows):
                    if self._stop_requested:
                        return
                    end = min(start + self.chunk_rows, n)
                    y_chunk = np.asarray(channel[start:end], dtype=np.float64)
                    if x_channel is channel:
                        x_chunk = np.arange(start, end, dtype=np.float64)
                    else:
                        x_len = len(x_channel)
                        x_chunk = (np.asarray(x_channel[start:min(end, x_len)], dtype=np.float64)
                                   if start < x_len else np.arange(start, end, dtype=np.float64))
                        if len(x_chunk) != len(y_chunk):
                            x_chunk = np.arange(start, end, dtype=np.float64)
                    per_chunk_budget = max(2, budget_remaining // chunks_remaining)
                    x_out, y_out = decimate(x_chunk, y_chunk, per_chunk_budget, method=self.decimation_method)
                    budget_remaining = max(0, budget_remaining - len(x_out))
                    chunks_remaining -= 1
                    log.trace("TDMS chunk: %s -> %d points (chunks_remaining=%d)",
                              channel.name, len(x_out), chunks_remaining)
                    self.chunk_loaded.emit(channel.name, x_out, y_out)


def _binary_search_indexable(dataset, value: float) -> int:
    """
    np.searchsorted(dataset, value, side='left'), against an open h5py
    Dataset or nptdms TdmsChannel directly instead of a loaded numpy
    array - reads O(log n) elements from disk instead of the whole
    dataset. Works against either type since both support len() and
    integer indexing. Assumes the dataset is sorted ascending, same as
    DataStore.get_roi.
    """
    lo, hi = 0, len(dataset)
    while lo < hi:
        mid = (lo + hi) // 2
        if dataset[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


class RangeLoadWorker(QThread):
    """
    Reads one channel's data within an x-range directly from disk, at a
    finer resolution than FileLoadWorker's load-time decimation left in
    DataStore - drives the "Load Detail for Visible Region" action (see
    ui/graph_widget.py's PyradeXYGraphWidget._on_load_visible_detail_dialog,
    which splices the result into the cached overview via
    DataStore.replace_signal rather than replacing the signal outright,
    so zooming back out still shows the complete x-range).

    HDF5 and TDMS get random-access reads (_binary_search_indexable).
    CSV has no index, so it's a bounded sequential scan instead
    (_read_csv_range) that stops once a chunk's x passes x_max, assuming
    x is sorted ascending.

    percentage (1-100) controls how much of the raw samples inside
    [x_min, x_max] to keep, decimated down from there - always capped at
    HARD_CAP_POINTS regardless, so a 100% request against a dense or
    wide window can't hand an unbounded number of points to a curve.
    """

    # Per-channel ceiling on points a single "load detail" action can
    # hand to DataStore/pyqtgraph, independent of percentage - well
    # above the load-time overview's default (4000 points/channel), well
    # below "the whole raw file".
    HARD_CAP_POINTS = 500_000

    range_loaded = Signal(str, object, object)  # channel, x, y
    error = Signal(str)

    def __init__(self, path: str, channel: str, x_min: float, x_max: float,
                 percentage: float = 100.0, parent=None):
        super().__init__(parent)
        self.path = path
        self.channel = channel
        self.x_min = x_min
        self.x_max = x_max
        self.percentage = max(1.0, min(100.0, percentage))

    def run(self):
        try:
            ext = Path(self.path).suffix.lower()
            if ext in ('.h5', '.hdf5'):
                x, y = self._read_hdf5_range()
            elif ext == '.tdms':
                x, y = self._read_tdms_range()
            elif ext in ('.csv', '.txt'):
                x, y = self._read_csv_range()
            else:
                self.error.emit(f"Unsupported file format for detail loading: {ext}")
                return

            n_raw = len(x)
            if n_raw == 0:
                self.range_loaded.emit(self.channel, x, y)
                return

            target_points = max(2, min(self.HARD_CAP_POINTS, ceil(n_raw * self.percentage / 100.0)))
            if needs_decimation(n_raw, target_points):
                x, y = decimate(x, y, target_points, method='peak')

            log.trace("RangeLoadWorker: %s [%.6g, %.6g] -> %d raw rows -> %d points (%.0f%%)",
                       self.channel, self.x_min, self.x_max, n_raw, len(x), self.percentage)
            self.range_loaded.emit(self.channel, x, y)
        except Exception as exc:
            log.exception("RangeLoadWorker failed for %s", self.channel)
            self.error.emit(str(exc))

    def _read_hdf5_range(self):
        with h5py.File(self.path, 'r') as f:
            group = f['data'] if 'data' in f else f
            channel_names = [name for name in group.keys()
                              if isinstance(group[name], h5py.Dataset)]
            x_name = _guess_x_column(channel_names)
            x_dataset = group[x_name]
            y_dataset = group[self.channel]

            idx_start = _binary_search_indexable(x_dataset, self.x_min)
            idx_end = _binary_search_indexable(x_dataset, self.x_max)
            idx_end = min(idx_end + 1, len(x_dataset))  # include the sample at/just past x_max
            if idx_end <= idx_start:
                return np.array([]), np.array([])

            x = np.asarray(x_dataset[idx_start:idx_end], dtype=np.float64)
            y = np.asarray(y_dataset[idx_start:idx_end], dtype=np.float64)
            return x, y

    def _read_tdms_range(self):
        from nptdms import TdmsFile

        with TdmsFile.open(self.path) as tdms:
            channels = [ch for group in tdms.groups() for ch in group.channels()]
            names = [ch.name for ch in channels]
            x_name = _guess_x_column(names)
            x_channel = next(ch for ch in channels if ch.name == x_name)
            y_channel = next(ch for ch in channels if ch.name == self.channel)

            idx_start = _binary_search_indexable(x_channel, self.x_min)
            idx_end = _binary_search_indexable(x_channel, self.x_max)
            idx_end = min(idx_end + 1, len(x_channel))
            if idx_end <= idx_start:
                return np.array([]), np.array([])

            x = np.asarray(x_channel[idx_start:idx_end], dtype=np.float64)
            y = np.asarray(y_channel[idx_start:idx_end], dtype=np.float64)
            return x, y

    def _read_csv_range(self, chunk_rows: int = 200_000):
        x_parts, y_parts = [], []
        for chunk in pd.read_csv(self.path, chunksize=chunk_rows):
            x_col = _guess_x_column(list(chunk.columns))
            x_chunk = chunk[x_col].to_numpy(dtype=np.float64)
            if x_chunk.size == 0:
                continue
            if x_chunk[-1] < self.x_min:
                continue  # entirely before the window - keep scanning
            if x_chunk[0] > self.x_max:
                break  # entirely after the window - x is ascending, nothing further can match
            mask = (x_chunk >= self.x_min) & (x_chunk <= self.x_max)
            if mask.any():
                x_parts.append(x_chunk[mask])
                y_parts.append(chunk[self.channel].to_numpy(dtype=np.float64)[mask])

        if not x_parts:
            return np.array([]), np.array([])
        return np.concatenate(x_parts), np.concatenate(y_parts)


def _make_recorder_backend(path: str):
    ext = Path(path).suffix.lower()
    if ext in ('.csv', '.txt'):
        return _CSVRecorderBackend(path)
    elif ext in ('.h5', '.hdf5'):
        return _HDF5RecorderBackend(path)
    elif ext == '.tdms':
        return _TDMSRecorderBackend(path)
    else:
        raise ValueError(f"Unsupported recording format: {ext} (expected .csv/.txt/.h5/.hdf5/.tdms)")


class _CSVRecorderBackend:
    """One row per sample. A batch (dict of equal-length arrays) unrolls
    into one row per array index, written in a single writerows()
    call."""

    def __init__(self, path: str):
        self._file = open(path, 'w', newline='')
        self._writer = None  # csv.DictWriter - built once columns are known, from the first record

    def store(self, record: dict):
        columns = {col: np.atleast_1d(val) for col, val in record.items()}
        if self._writer is None:
            self._writer = csv.DictWriter(self._file, fieldnames=list(columns))
            self._writer.writeheader()
        n = max((len(arr) for arr in columns.values()), default=0)
        rows = [{col: arr[i] for col, arr in columns.items()} for i in range(n)]
        self._writer.writerows(rows)
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None


class _HDF5RecorderBackend:
    def __init__(self, path: str):
        self._file = h5py.File(path, 'a')
        self._group = self._file.require_group('data')

    def store(self, record: dict):
        for col, val in record.items():
            arr = np.atleast_1d(val).astype(np.float64)
            if col not in self._group:
                self._group.create_dataset(col, data=arr, maxshape=(None,), chunks=True)
            else:
                dataset = self._group[col]
                old_len = dataset.shape[0]
                dataset.resize(old_len + len(arr), axis=0)
                dataset[old_len:] = arr
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None


class _TDMSRecorderBackend:
    def __init__(self, path: str):
        from nptdms import TdmsWriter
        self._writer = TdmsWriter(path, mode='a' if os.path.exists(path) else 'w')
        self._writer.__enter__()

    def store(self, record: dict):
        from nptdms import ChannelObject
        channels = [
            ChannelObject('DataGroup', col, np.atleast_1d(val).astype(np.float64))
            for col, val in record.items()
        ]
        self._writer.write_segment(channels)

    def close(self):
        # Guard against a second call: unlike h5py, TdmsWriter isn't
        # safe to close twice - a second __exit__() raises AttributeError.
        if self._writer is not None:
            self._writer.__exit__(None, None, None)
            self._writer = None


class RecorderThread(QThread):
    """
    Writes queued records to disk (CSV/HDF5/TDMS, via
    _make_recorder_backend) on its own thread, separate from whatever
    is draining the live DAQ queue (core/live_worker.py's
    AcquisitionWorker) - a slow disk throttles this thread's writes,
    never live ingestion.

    AcquisitionWorker calls enqueue() from its own thread; run() drains
    the queue here and calls backend.store().

    The backend is opened lazily, inside run() - not __init__, which
    runs on whichever thread constructs this object - since h5py/nptdms
    file handles aren't safe to open on one OS thread and use from
    another.
    """

    error = Signal(str)

    _STOP_SENTINEL = object()

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self._queue = queue_module.Queue()

    def enqueue(self, record: dict):
        self._queue.put(record)

    def stop(self):
        """Signals no more records are coming. run() drains whatever's
        already queued (FIFO-ordered ahead of the sentinel) before
        exiting."""
        self._queue.put(self._STOP_SENTINEL)

    def run(self):
        try:
            backend = _make_recorder_backend(self.path)
        except Exception as exc:
            log.exception("RecorderThread failed to open %s", self.path)
            self.error.emit(str(exc))
            return

        try:
            while True:
                record = self._queue.get()
                if record is self._STOP_SENTINEL:
                    break
                backend.store(record)
        except Exception as exc:
            log.exception("RecorderThread failed writing %s", self.path)
            self.error.emit(str(exc))
        finally:
            backend.close()


