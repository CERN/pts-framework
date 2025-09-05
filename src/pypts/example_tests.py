# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import numpy as np
from nptdms import TdmsWriter, RootObject, GroupObject, ChannelObject
import os
from datetime import datetime

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
    return {"compare": value}

def generate_error():
    raise AttributeError

def simple_output(value):
    return {"my_output":value + 1}

def is_PSU_disconnected():
    return (True)

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
    fft_freq = np.fft.fftfreq(len(data), 1/sampling_rate)
    
    # Get magnitude spectrum (only positive frequencies)
    magnitude = np.abs(fft_result[:len(fft_result)//2])
    freq_bins = fft_freq[:len(fft_freq)//2]
    
    # Find the peak frequency
    peak_index = np.argmax(magnitude)
    detected_frequency = abs(freq_bins[peak_index])
    
    # Check if detected frequency matches expected frequency within tolerance
    frequency_error = abs(detected_frequency - frequency)
    test_passed = frequency_error <= tolerance
   
    # Save data to TDMS file in reports directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Include serial number in filename if provided
    if serial_number:
        tdms_filename = f"sinewave_{frequency}Hz_{serial_number}_{timestamp}.tdms"
    else:
        tdms_filename = f"sinewave_{frequency}Hz_{timestamp}.tdms"
    tdms_filepath = os.path.join("pts_reports", tdms_filename)
    
    # Ensure the directory exists
    os.makedirs("pts_reports", exist_ok=True)
    
    # Create TDMS file with sinewave data
    with TdmsWriter(tdms_filepath) as tdms_writer:
        # Create root object with test metadata
        root_properties = {
            "Test_Name": "Sinewave Generation and Validation",
            "Expected_Frequency_Hz": frequency,
            "Detected_Frequency_Hz": detected_frequency,
            "Frequency_Error_Hz": frequency_error,
            "Test_Passed": test_passed,
            "Tolerance_Hz": tolerance,
        }
        # Add serial number to TDMS properties if provided
        if serial_number:
            root_properties["Serial_Number"] = serial_number
        
        root_object = RootObject(properties=root_properties)
        
        # Create group object with measurement info
        group_object = GroupObject("Sinewave_Test", properties={
            "Sampling_Rate_Hz": sampling_rate,
            "Duration_s": duration,
            "Num_Samples": len(data),
        })
        
        # Create channel objects with data and properties
        time_channel = ChannelObject("Sinewave_Test", "Time", t, properties={
            "unit_string": "s",
            "wf_increment": 1.0/sampling_rate,
        })
        
        data_channel = ChannelObject("Sinewave_Test", "Amplitude", data, properties={
            "unit_string": "V",
            "wf_increment": 1.0/sampling_rate,
        })
        
        # Write segment to file
        tdms_writer.write_segment([
            root_object,
            group_object,
            time_channel,
            data_channel
        ])
 
    
    return {
        "compare": test_passed,  # Pass/fail result for the test framework
        "expected_frequency": frequency,
        "detected_frequency": detected_frequency,
        "frequency_error": frequency_error,
        "tolerance": tolerance,
        "sampling_rate": sampling_rate,
        "duration": duration,
        "num_samples": len(data),
        "tdms_file": tdms_filepath
    }

def loadconfigFile(file= None):
    print("We went into config function")
    if file:
        print("we properly found the file.")
        return True
    else:
        return False