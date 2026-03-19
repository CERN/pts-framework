# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import numpy as np
import h5py
import os
from datetime import datetime
from pypts.XYGraph.StreamContainer import Stream, GlobalContainer, container
from pypts.XYGraph.simulated_signals import Simulated_sine_wave
import time
logger = logging.getLogger(__name__)


def load_existing_graph(stream_name = "", stream_hook = ""):
    stream = Stream(name=stream_name, hook=stream_hook)
    streamlist = container.get_all_streams()
    time.sleep(10)
    stream.kill()
    pass


def simulate_sine_wave(stream_name = ""):
    my_signal = Simulated_sine_wave(name=stream_name)
    my_signal.start_acquisition()
    streamlist = container.get_all_streams()
    for stream in streamlist:
        print(f"Retrieved registered stream {stream.name}. Stream is tied with {stream.hook} hook.")
    time.sleep(10)
    my_signal.stop_acquisition()

    pass

def generate_sinewave(frequency=60, duration=1.0, tolerance=1.0, serial_number=None):
    """
    Generate a sinewave and validate its frequency content using FFT analysis.

    Args:
        frequency: Expected frequency of the sinewave in Hz (default: 60)
        duration: Duration of the signal in seconds (default: 1.0)
        tolerance: Frequency tolerance in Hz for pass/fail (default: 1.0)
        serial_number: Serial number for this test run (default: None)

    Returns:
        dict: Contains validation results and signal data
    """
    sampling_rate = frequency * 10  # 10x for Nyquist theorem

    # Generate time vector
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)

    # Generate sinewave
    data = np.sin(2 * np.pi * frequency * t)

    # Analyze frequency content using FFT FIRST
    fft_result = np.fft.fft(data)
    fft_freq = np.fft.fftfreq(len(data), 1 / sampling_rate)

    # Get magnitude spectrum (only positive frequencies)
    magnitude = np.abs(fft_result[:len(fft_result) // 2])
    freq_bins = fft_freq[:len(fft_freq) // 2]

    # Find the peak frequency
    peak_index = np.argmax(magnitude)
    detected_frequency = abs(freq_bins[peak_index])

    # Check if detected frequency matches expected frequency within tolerance
    frequency_error = abs(detected_frequency - frequency)
    test_passed = frequency_error <= tolerance

    # Save data to HDF5 file in reports directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Include serial number in filename if provided
    if serial_number:
        h5_filename = f"sinewave_{frequency}Hz_{serial_number}_{timestamp}.h5"
    else:
        h5_filename = f"sinewave_{frequency}Hz_{timestamp}.h5"
    h5_filepath = os.path.join("pts_reports", h5_filename)

    # Ensure the directory exists
    os.makedirs("pts_reports", exist_ok=True)

    # Create HDF5 file with sinewave data
    with h5py.File(h5_filepath, 'w') as f:
        # File-level attributes (replaces Root properties)
        f.attrs["Test_Name"] = "Sinewave Generation and Validation"
        f.attrs["Expected_Frequency_Hz"] = frequency
        f.attrs["Detected_Frequency_Hz"] = detected_frequency
        f.attrs["Frequency_Error_Hz"] = frequency_error
        f.attrs["Test_Passed"] = test_passed
        f.attrs["Tolerance_Hz"] = tolerance
        if serial_number:
            f.attrs["Serial_Number"] = serial_number

        # Group (replaces TDMS Group)
        grp = f.create_group("Sinewave_Test")
        grp.attrs["Sampling_Rate_Hz"] = sampling_rate
        grp.attrs["Duration_s"] = duration
        grp.attrs["Num_Samples"] = len(data)

        # Datasets (replaces TDMS Channels)
        ds_time = grp.create_dataset("Time", data=t)
        ds_time.attrs["unit_string"] = "s"
        ds_time.attrs["wf_increment"] = 1.0 / sampling_rate

        ds_amp = grp.create_dataset("Amplitude", data=data)
        ds_amp.attrs["unit_string"] = "V"
        ds_amp.attrs["wf_increment"] = 1.0 / sampling_rate

    return {
        "compare": test_passed,  # Pass/fail result for the test framework
        "expected_frequency": frequency,
        "detected_frequency": detected_frequency,
        "frequency_error": frequency_error,
        "tolerance": tolerance,
        "sampling_rate": sampling_rate,
        "duration": duration,
        "num_samples": len(data),
        "hdf5_file": h5_filepath
    }
