# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import tempfile
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

'''
This file contains a collection of example tests that can be used to develop the PTS framework.
'''

logger = logging.getLogger(__name__)

some_value = 5

def test_to_run(target):
    return {"compare": target == 45, "other_output": "abc"}

def other_test():
    return {"some_return": True, "value": 3}

def simple_return():
    return (5, 4)

def range_test(value, min, max):
    return {"compare": value}

def generate_error():
    raise AttributeError

def simple_output(value):
    return {"output": value + 1}

def is_PSU_disconnected():
    return True

def generate_sinewave(frequency=60, duration=1.0, tolerance=1.0):
    """Generate a sinewave, validate its frequency via FFT, and plot the result.

    Args:
        frequency: Expected frequency in Hz (default: 60).
        duration:  Signal duration in seconds (default: 1.0).
        tolerance: Allowed frequency error in Hz for pass/fail (default: 1.0).

    Returns:
        dict with keys:
          ``passed`` (bool) – whether detected frequency is within tolerance;
          ``chart``  (str)  – absolute path of the saved PNG plot.
    """
    sampling_rate = frequency * 10
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)
    data = np.sin(2 * np.pi * frequency * t)

    fft_result = np.fft.fft(data)
    fft_freq = np.fft.fftfreq(len(data), 1 / sampling_rate)
    magnitude = np.abs(fft_result[: len(fft_result) // 2])
    freq_bins = fft_freq[: len(fft_freq) // 2]
    detected_frequency = abs(freq_bins[np.argmax(magnitude)])
    test_passed = abs(detected_frequency - frequency) <= tolerance

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6))
    ax1.plot(t, data, linewidth=0.8)
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Amplitude")
    ax1.set_title(f"Sinewave — {frequency} Hz")
    ax1.grid(True, alpha=0.3)

    ax2.plot(freq_bins, magnitude, linewidth=0.8)
    ax2.axvline(detected_frequency, color="red", linestyle="--",
                label=f"Peak: {detected_frequency:.1f} Hz")
    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("Magnitude")
    ax2.set_title("FFT Spectrum")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    tmp = tempfile.NamedTemporaryFile(suffix="_sinewave.png", delete=False)
    fig.savefig(tmp.name, dpi=100, bbox_inches="tight")
    plt.close(fig)

    return {"passed": test_passed, "chart": tmp.name}
