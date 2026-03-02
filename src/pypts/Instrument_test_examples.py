# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
from time import sleep

'''
This file contains a collection of example Instrument uses that can be used to develop the PTS framework.
'''
logger = logging.getLogger(__name__)

def run_cnt91(device_name,gate_times = 0.1, samples = 100, channels = 1):
    
    from .HAL.parameters import  FloatParameter, IntegerParameter
    from .HAL.Supported_instruments.pendulum.cnt91 import CNT91

    #These parameters help explain the variables and will raise and value error if the inserted value is too high or too low.
    gate_time = FloatParameter(
        "Gate Time",
        units="s",
        default=0.1,
        minimum=2e-8,
        maximum=1000,
    )

    n_samples = IntegerParameter(
        "Number of Samples",
        default=100,
        minimum=4,
        maximum=10000,
    )

    channel = IntegerParameter(
        "Channel (A=1, B=2)",
        default=1,
        minimum=1,
        maximum=2,
    )

    gate_time = gate_times
    n_samples = samples
    channel = channels
    channel_map = {1: "A", 2: "B"}
    channel = channel_map[channel]
    #"USB0::0x14EB::0x0091::205575::INSTR"
    logger.info("Initializing CNT-91")
    counter = CNT91(device_name)

    #This command line will replace everything else commented below.
    counter.buffer_frequency_time_series(channel=channel, n_samples=n_samples, gate_time=gate_time, trigger_level=2.4)

    # counter.clear()
    # counter.format = "ASCII"
    # counter.continuous = False
    # counter.gate_time = gate_time

    # print("Instrument ID: %s", counter.id)
    # sleep(0.2)

    # logger.info("Starting frequency buffer measurement")

    # # Map numeric channel to CNT-91 channel name
    
    # # Configure buffered frequency measurement
    # counter.configure_frequency_array_measurement(
    #     n_samples=n_samples,
    #     channel=channel,
    #     back_to_back=True,
    # )
    # # Start measurement
    # counter.write(":INIT")

    frequencies = counter.read_buffer(n_samples)

    measured_data = []
    for i, freq in enumerate(frequencies):
        data = {
            "Index": i,
            "Frequency (Hz)": freq,
        }
        measured_data.append(data)
    
    logger.info("Shutting down CNT-91")
    try:
        counter.shutdown()
    except Exception:
        pass

    return{"output":True, "data": measured_data}


def ping_instrument(device_name):
    from .HAL.instrument import Instrument

    logger.info(f"Initializing device {device_name}")
    #Initialization of an instrument. It requires the device location in the form of the device name AND an actual name. The name "test" is only used for logging purposes.
    equipment = Instrument(adapter=device_name, name="test")
    equipment.clear()
    equipment.format = "ASCII"

    found_id = equipment.id
    print("Instrument ID: %s", found_id)

    if found_id:
        return {"output": True, "details": found_id }
    else:
        return {"output": False, "details": found_id }



