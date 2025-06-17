# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import numpy as np

'''
This file contains a collection of example tests that can be used to develop the PTS framework.
'''

logger = logging.getLogger(__name__)

some_value = 5

def test_to_run(target):
    # with nidmm.Session("Dev1") as session:
    #     print("Measurement: " + str(session.read()))
    # logger.info(f"I received {target}.")
    return {"compare": target == 45, "other_output": "abc"}

def other_test():
    # logger.info("I could also do this.")
    return {"some_return": True, "value": 3}

def simple_return():
    return (5, 4)

def range_test(value, min, max):
    # time.sleep(1)
    return {"compare": min < value < max}

def generate_error():
    raise AttributeError

def simple_output(value):
    return {"my_output": value + 1}

def is_PSU_disconnected():
    return (True)

def generate_sinewave(frequency=60, duration=1.0):
    """
    Generate a sinewave with sampling rate according to Nyquist theorem.
    
    Args:
        frequency: Frequency of the sinewave in Hz (default: 60)
        duration: Duration of the signal in seconds (default: 1.0)
    
    Returns:
        dict: Contains 'data' (numpy array) and 'sampling_rate' (Hz)
    """
    sampling_rate = frequency * 10  # 10x for Nyquist theorem
    
    # Generate time vector
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)
    
    # Generate 60Hz sinewave
    data = np.sin(2 * np.pi * frequency * t)
    
    return {
        "data": data,
        "sampling_rate": sampling_rate,
        "frequency": frequency,
        "duration": duration,
        "num_samples": len(data)
    }

