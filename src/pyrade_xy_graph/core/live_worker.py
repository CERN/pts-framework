"""
Live acquisition: drains a queue.Queue of DAQ records on its own
background thread, delivering them to the GUI thread via a Qt signal
and, if recording, to a RecorderThread (core/binary_results.py) via its
own internal queue - kept decoupled from this loop so a slow disk never
stalls live ingestion.

Instrument drivers (pymeasure.instruments) have no dependency on any
particular acquisition framework - they're plain objects with
.ask()/.write()/property-style control, constructed and called directly
from wherever the acquisition loop lives (see AcquisitionWorker.startup()
below).
"""

import logging
import queue as queue_module
from collections import defaultdict

import numpy as np
from PySide6.QtCore import QThread, Signal

from pyrade_xy_graph.core import trace_level  # noqa: F401  (registers Logger.trace())
from pyrade_xy_graph.core.binary_results import RecorderThread

log = logging.getLogger(__name__)


class AcquisitionWorker(QThread):
    """
    Drains data_queue on its own background thread. Every item on
    data_queue must be either STOP_SENTINEL or a dict mapping column
    name -> a scalar (one sample) or an array-like (a pre-batched
    chunk) - anything else raises TypeError, caught by run() and
    reported via the error signal. A dict covers both shapes uniformly
    via np.atleast_1d, so a pandas DataFrame chunk should convert first:
    {col: df[col].to_numpy() for col in df.columns}.

    Scalar records are buffered and flushed as a batch at batch_size,
    or whenever the queue goes momentarily empty (keeps the live view
    responsive during low throughput instead of waiting for batch_size
    scalars to accumulate). Chunk records are emitted straight through.

    For hardware-specific setup/teardown, subclass and override
    startup()/shutdown():

        class MyDaqWorker(AcquisitionWorker):
            def startup(self):
                self.device = SomeVendorInstrument(...)
                self.device.open()

            def shutdown(self):
                self.device.close()

    Both run on this thread, bracketing the drain loop.
    """

    data_received = Signal(dict)
    error = Signal(str)
    status_changed = Signal(str)
    finished_all = Signal()

    # A sentinel object rather than a string - `is` identity avoids any
    # chance of colliding with a producer's own payload.
    STOP_SENTINEL = object()

    def __init__(self, data_queue: queue_module.Queue, record_path: str | None = None,
                 batch_size: int = 200, poll_timeout: float = 0.02, parent=None):
        """
        poll_timeout: how long each data_queue.get() waits before
        checking should-stop and flushing pending scalars - bounds how
        quickly stop() takes effect and how quickly a slow trickle of
        scalars reaches the live view. Lower is more responsive at the
        cost of more idle wakeups; tune for your data rate.
        """
        super().__init__(parent)
        self.data_queue = data_queue
        self.batch_size = batch_size
        self.poll_timeout = poll_timeout
        self._stop_requested = False
        self.recorder: RecorderThread | None = None
        if record_path:
            self.recorder = RecorderThread(record_path)
            self.recorder.error.connect(self._on_recorder_error)

    def stop(self):
        self._stop_requested = True

    def startup(self):
        """Override in a subclass for hardware-specific setup - runs on
        this thread, before the drain loop starts. No-op by default."""

    def shutdown(self):
        """Override in a subclass for hardware-specific teardown - runs
        on this thread, always (even after an error or stop()), before
        the recorder is stopped. No-op by default."""

    def run(self):
        if self.recorder is not None:
            self.recorder.start()

        self.status_changed.emit('running')
        try:
            self.startup()
            self._drain_loop()
        except Exception as exc:
            log.exception("AcquisitionWorker failed")
            self.error.emit(str(exc))
            self.status_changed.emit('failed')
        else:
            self.status_changed.emit('finished')
        finally:
            try:
                self.shutdown()
            except Exception:
                log.exception("AcquisitionWorker.shutdown() failed")
            if self.recorder is not None:
                self.recorder.stop()
                self.recorder.wait()
            self.finished_all.emit()

    def _on_recorder_error(self, message: str):
        # A broken recording (disk full, permissions) stops the whole
        # acquisition instead of silently recording nothing further
        # while the live view still looks fine.
        log.error("Recording failed - stopping acquisition: %s", message)
        self.error.emit(f"Recording failed: {message}")
        self.stop()

    def _drain_loop(self):
        buffers = defaultdict(list)
        count = 0

        def flush():
            nonlocal count
            if count == 0:
                return
            batch = {key: np.array(vals) for key, vals in buffers.items()}
            self._emit(batch)
            buffers.clear()
            count = 0

        while not self._stop_requested:
            try:
                item = self.data_queue.get(timeout=self.poll_timeout)
            except queue_module.Empty:
                # Flush so the live view stays current during low
                # throughput instead of waiting for batch_size to fill.
                flush()
                continue

            if item is self.STOP_SENTINEL:
                flush()
                break

            if not isinstance(item, dict):
                raise TypeError(
                    f"AcquisitionWorker.data_queue items must be dict or STOP_SENTINEL, got {type(item)!r}")

            # np.atleast_1d normalizes single-element lists (a common
            # DAQ API shape) to the same rank as a plain scalar, so they
            # don't get treated as a batched column by mistake.
            normalized = {key: np.atleast_1d(val) for key, val in item.items()}
            if all(arr.size == 1 for arr in normalized.values()):
                for key, arr in normalized.items():
                    buffers[key].append(arr.item())
                count += 1
            else:
                flush()
                self._emit(normalized)
                continue

            if count >= self.batch_size:
                flush()

        flush()

    def _emit(self, batch: dict):
        self.data_received.emit(batch)
        if self.recorder is not None:
            self.recorder.enqueue(batch)
