# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Example instrument routines that can be called from pypts recipe steps.

These functions demonstrate how to use the pymeasure-based instrument layer
from within the pts-framework.  They are intended as working reference
implementations rather than production code.
"""

import logging

from pymeasure.experiment import FloatParameter, IntegerParameter
from pymeasure.instruments import Instrument, SCPIMixin

from pypts.instruments.pendulum import CNT91

logger = logging.getLogger(__name__)


def run_cnt91(device_name, gate_times=0.1, samples=100, channels=1):
    """Perform a buffered frequency measurement on the Pendulum CNT-91.

    :param str device_name: VISA resource string (e.g.
        ``"USB0::0x14EB::0x0091::205575::INSTR"``).
    :param float gate_times: Gate time per sample in seconds.
    :param int samples: Number of frequency samples to acquire (4 – 10 000).
    :param int channels: Physical input channel: 1 for A, 2 for B.
    :returns: ``{"output": True, "data": [{"Index": i, "Frequency (Hz)": f}, …]}``
    """
    # Parameters document the valid ranges and units; they raise ValueError
    # if a value falls outside the declared bounds.
    gate_time_param = FloatParameter(
        "Gate Time",
        units="s",
        default=0.1,
        minimum=2e-8,
        maximum=1000,
    )
    n_samples_param = IntegerParameter(
        "Number of Samples",
        default=100,
        minimum=4,
        maximum=10000,
    )
    channel_param = IntegerParameter(
        "Channel (A=1, B=2)",
        default=1,
        minimum=1,
        maximum=2,
    )
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

    measured_data = [
        {"Index": i, "Frequency (Hz)": freq}
        for i, freq in enumerate(frequencies)
    ]

    logger.info("Shutting down CNT-91")
    try:
        counter.shutdown()
    except Exception:
        pass

    return {"output": True, "data": measured_data}


class _GenericSCPIDevice(SCPIMixin, Instrument):
    """Minimal SCPI-capable instrument used only for probing."""


def ping_instrument(device_name):
    """Query the ``*IDN?`` string of any SCPI-compatible instrument.

    :param str device_name: VISA resource string.
    :returns: ``{"output": True, "details": "<id string>"}`` on success,
              ``{"output": False, "details": None}`` otherwise.
    """
    logger.info("Probing device at %s", device_name)
    equipment = _GenericSCPIDevice(adapter=device_name, name="probe")
    equipment.clear()

    found_id = equipment.id
    logger.info("Instrument ID: %s", found_id)

    return {"output": bool(found_id), "details": found_id}
