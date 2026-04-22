# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import tempfile
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pymeasure.experiment import FloatParameter, IntegerParameter
from pymeasure.instruments import Instrument, SCPIMixin

from pypts.instruments.pendulum import CNT91

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

def write_a_simple_filessh(target):
    target.exec_command("echo 'Hello World' > myfile.txt")
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

def loadconfigFile(file=None):
    print("We went into config function")
    if file:
        print("we properly found the file.")
        return True
    else:
        return False

def get_sysmon_temperatures(target) -> dict:
    """Reads sysmon temperature values from the remote system via SSH."""
    temps = {}
    command = (
        "for zone in /sys/class/thermal/thermal_zone*/; do "
        "name=$(cat \"$zone/type\" 2>/dev/null); "
        "temp=$(cat \"$zone/temp\" 2>/dev/null); "
        "if [ -n \"$name\" ] && [ -n \"$temp\" ]; then "
        "echo \"$name $temp\"; fi; done"
    )
    try:
        stdin, stdout, stderr = target.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        if error:
            logger.warning(f"Warning: {error.strip()}")
        for line in output.strip().splitlines():
            parts = line.split()
            if len(parts) == 2:
                name, temp_milli = parts
                try:
                    temps[name] = int(temp_milli) / 1000.0
                except ValueError:
                    continue
    except Exception as e:
        logger.error(f"Failed to get the temperatures: {e}")
    return temps

def get_hwmon(target) -> dict:
    temps = {}
    command_hwmon = """
            for hwmon in /sys/class/hwmon/hwmon*; do
                name=$(cat "$hwmon/name" 2>/dev/null)
                for temp in "$hwmon"/temp*_input; do
                    label_file="${temp%_input}_label"
                    label=$(cat "$label_file" 2>/dev/null || echo "$name")
                    value=$(cat "$temp" 2>/dev/null)
                    if [ -n "$value" ]; then
                        echo "$label $value"
                    fi
                done
            done
            """
    try:
        stdin, stdout, stderr = target.exec_command(command_hwmon)
        output = stdout.read().decode()
        error = stderr.read().decode()
        if error:
            logger.warning(f"Warning: {error.strip()}")
        for line in output.strip().splitlines():
            parts = line.split()
            if len(parts) == 2:
                name, temp_milli = parts
                try:
                    temps[name] = int(temp_milli) / 1000.0
                except ValueError:
                    continue
    except Exception as e:
        logger.error(f"Failed to get hwmon: {e}")
    return {"output": temps}


"""
Example instrument routines that can be called from pypts recipe steps.
"""

def run_cnt91(device_name, gate_times=0.1, samples=100, channels=1):
    """Perform a buffered frequency measurement on the Pendulum CNT-91."""
    gate_time_param = FloatParameter("Gate Time", units="s", default=0.1, minimum=2e-8, maximum=1000)
    n_samples_param = IntegerParameter("Number of Samples", default=100, minimum=4, maximum=10000)
    channel_param = IntegerParameter("Channel (A=1, B=2)", default=1, minimum=1, maximum=2)
    gate_time_param.value = gate_times
    n_samples_param.value = samples
    channel_param.value = channels

    channel_map = {1: "A", 2: "B"}
    channel = channel_map[channel_param.value]

    logger.info("Initializing CNT-91 at %s", device_name)
    counter = CNT91(device_name)
    counter.buffer_frequency_time_series(
        channel=channel,
        n_samples=n_samples_param.value,
        gate_time=gate_time_param.value,
        trigger_level=2.4,
    )
    frequencies = counter.read_buffer(n_samples_param.value)
    measured_data = [{"Index": i, "Frequency (Hz)": freq} for i, freq in enumerate(frequencies)]

    logger.info("Shutting down CNT-91")
    try:
        counter.shutdown()
    except Exception:
        pass

    return {"output": True, "data": measured_data}


class _GenericSCPIDevice(SCPIMixin, Instrument):
    """Minimal SCPI-capable instrument used only for probing."""


def ping_instrument(device_name):
    """Query the ``*IDN?`` string of any SCPI-compatible instrument."""
    logger.info("Probing device at %s", device_name)
    equipment = _GenericSCPIDevice(adapter=device_name, name="probe")
    equipment.clear()
    found_id = equipment.id
    logger.info("Instrument ID: %s", found_id)
    return {"output": bool(found_id), "details": found_id}
