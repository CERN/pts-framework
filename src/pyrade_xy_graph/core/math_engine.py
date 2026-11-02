"""
Headless numerical analysis: no Qt/pyqtgraph imports anywhere in this
module, so it's usable (and testable) independent of the GUI.
"""

import numpy as np


DECIMATION_METHODS = ('peak', 'mean', 'subsample')


def _bin_layout(n: int, n_bins: int) -> tuple[int, int, int]:
    """
    Shared bin-boundary math for every decimation method below. Ceil
    division for bin_size guarantees the total bin count never exceeds
    n_bins (floor division could let a non-round n spill into an extra
    bin, overshooting the caller's point budget). Returns (bin_size,
    n_full_bins, remainder); remainder samples form one shorter final
    bin, still within n_bins total.
    """
    bin_size = -(-n // n_bins)  # ceil division
    n_full_bins = n // bin_size
    remainder = n - n_full_bins * bin_size
    return bin_size, n_full_bins, remainder


def _decimate_peak(x: np.ndarray, y: np.ndarray, n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Keeps the min and max sample (in original order) of each bin, so
    transients survive - two output points per bin. Vectorized via
    reshape + argmin/argmax per bin."""
    n = len(x)
    bin_size, n_full_bins, remainder = _bin_layout(n, n_bins)
    x_parts, y_parts = [], []

    if n_full_bins > 0:
        main_n = n_full_bins * bin_size
        y_grid = y[:main_n].reshape(n_full_bins, bin_size)
        x_grid = x[:main_n].reshape(n_full_bins, bin_size)
        argmin = np.argmin(y_grid, axis=1)
        argmax = np.argmax(y_grid, axis=1)
        lo_idx = np.minimum(argmin, argmax)
        hi_idx = np.maximum(argmin, argmax)
        rows = np.arange(n_full_bins)
        pair_x = np.empty(n_full_bins * 2, dtype=x.dtype)
        pair_y = np.empty(n_full_bins * 2, dtype=y.dtype)
        pair_x[0::2], pair_x[1::2] = x_grid[rows, lo_idx], x_grid[rows, hi_idx]
        pair_y[0::2], pair_y[1::2] = y_grid[rows, lo_idx], y_grid[rows, hi_idx]
        x_parts.append(pair_x)
        y_parts.append(pair_y)

    if remainder > 0:
        x_tail, y_tail = x[-remainder:], y[-remainder:]
        i_min, i_max = int(np.argmin(y_tail)), int(np.argmax(y_tail))
        lo, hi = (i_min, i_max) if i_min <= i_max else (i_max, i_min)
        x_parts.append(np.array([x_tail[lo], x_tail[hi]], dtype=x.dtype))
        y_parts.append(np.array([y_tail[lo], y_tail[hi]], dtype=y.dtype))

    return np.concatenate(x_parts), np.concatenate(y_parts)


def _decimate_mean(x: np.ndarray, y: np.ndarray, n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Averages each bin to one output point - smoother, hides spikes."""
    n = len(x)
    bin_size, n_full_bins, remainder = _bin_layout(n, n_bins)
    x_parts, y_parts = [], []

    if n_full_bins > 0:
        main_n = n_full_bins * bin_size
        x_parts.append(x[:main_n].reshape(n_full_bins, bin_size).mean(axis=1))
        y_parts.append(y[:main_n].reshape(n_full_bins, bin_size).mean(axis=1))

    if remainder > 0:
        x_parts.append(np.array([x[-remainder:].mean()], dtype=x.dtype))
        y_parts.append(np.array([y[-remainder:].mean()], dtype=y.dtype))

    return np.concatenate(x_parts), np.concatenate(y_parts)


def _decimate_subsample(x: np.ndarray, y: np.ndarray, n_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Keeps every Nth raw sample - cheapest, can alias (a transient can
    fall entirely between kept samples). .copy() matters: a bare
    strided slice is a view into the source buffer, which would keep a
    large source array resident in memory for as long as the small
    decimated result is held."""
    n = len(x)
    stride, _, _ = _bin_layout(n, n_bins)
    return x[::stride].copy(), y[::stride].copy()


_DECIMATE_FUNCS = {'peak': _decimate_peak, 'mean': _decimate_mean, 'subsample': _decimate_subsample}


def decimate(x: np.ndarray, y: np.ndarray, target_points: int, method: str = 'peak',
              ) -> tuple[np.ndarray, np.ndarray]:
    """
    Reduces (x, y) to at most ~target_points samples. Returns (x, y)
    unchanged if there's nothing to gain from decimating.

    method uses the same vocabulary as ScopePlotWidget.downsample_method
    (ui/plot_widget.py), so file-load decimation and render-time
    downsampling mean the same thing:

      'peak'      - min and max sample per bin (default). A bin
                    contributes two output points, so target_points // 2
                    bins are used.
      'mean'      - one averaged output point per bin.
      'subsample' - every Nth raw sample, one output point per bin.

    Used by FileLoadWorker to keep RAM bounded when reading a large
    file.
    """
    if method not in _DECIMATE_FUNCS:
        raise ValueError(f"Unknown decimation method: {method!r} (expected one of {DECIMATION_METHODS})")

    n = len(x)
    target_points = max(2, target_points)
    if n <= target_points:
        return x, y

    n_bins = max(1, target_points // 2) if method == 'peak' else max(1, target_points)
    return _DECIMATE_FUNCS[method](x, y, n_bins)


def decimate_minmax(x: np.ndarray, y: np.ndarray, target_points: int) -> tuple[np.ndarray, np.ndarray]:
    """decimate(x, y, target_points, method='peak')."""
    return decimate(x, y, target_points, method='peak')


def needs_decimation(n_samples: int, target_points: int) -> bool:
    return n_samples > max(2, target_points)


def summary_stats(y: np.ndarray) -> dict:
    """Min/max/average/median/peak-to-peak over a signal slice."""
    if len(y) == 0:
        return {'min': None, 'max': None, 'average': None, 'median': None, 'peak_to_peak': None}
    y_min = float(np.min(y))
    y_max = float(np.max(y))
    return {
        'min': y_min,
        'max': y_max,
        'average': float(np.mean(y)),
        'median': float(np.median(y)),
        'peak_to_peak': y_max - y_min,
    }


def fft(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Windowed FFT of a (roughly) uniformly-sampled slice. Returns
    (freqs, magnitude) for the positive-frequency half of the spectrum.
    """
    n = len(y)
    if n < 2:
        return np.array([]), np.array([])

    dt = float(np.mean(np.diff(x)))
    if dt <= 0:
        return np.array([]), np.array([])

    window = np.hanning(n)
    spectrum = np.fft.rfft(y * window)
    freqs = np.fft.rfftfreq(n, d=dt)
    magnitude = np.abs(spectrum) * 2.0 / np.sum(window)
    return freqs, magnitude
