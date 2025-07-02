# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from nptdms import TdmsFile
import numpy as np
import os

# Example TDMS file path - update this to your actual file
tdms_file_path = "pts_reports/sinewave_60Hz_20250617_162348.tdms"  # Example filename
group_name = "Sinewave_Test"
channel_name = "Amplitude"

# Check if file exists
if not os.path.exists(tdms_file_path):
    print(f"TDMS file not found: {tdms_file_path}")
    print("Please update the tdms_file_path variable with a valid file path")
else:
    print(f"Reading TDMS file: {tdms_file_path}")
    
    # Method 1: Read data in chunks (efficient for large files)
    channel_sum = 0.0
    channel_length = 0
    with TdmsFile.open(tdms_file_path) as tdms_file:
        for chunk in tdms_file.data_chunks():
            channel_chunk = chunk[group_name][channel_name]
            channel_length += len(channel_chunk)
            channel_sum += channel_chunk[:].sum()
    channel_mean = channel_sum / channel_length
    
    print(f"Channel mean (chunked reading): {channel_mean}")
    print(f"Total samples: {channel_length}")
    
    # Method 2: Read all data at once (simpler but uses more memory)
    with TdmsFile.read(tdms_file_path) as tdms_file:
        # Read root properties
        print("\n=== Root Properties ===")
        for prop_name, prop_value in tdms_file.properties.items():
            print(f"{prop_name}: {prop_value}")
        
        # Read group properties
        group = tdms_file[group_name]
        print(f"\n=== Group '{group_name}' Properties ===")
        for prop_name, prop_value in group.properties.items():
            print(f"{prop_name}: {prop_value}")
        
        # Read channel data and properties
        amplitude_channel = group["Amplitude"]
        time_channel = group["Time"]
        
        print(f"\n=== Channel 'Amplitude' Properties ===")
        for prop_name, prop_value in amplitude_channel.properties.items():
            print(f"{prop_name}: {prop_value}")
        
        print(f"\n=== Channel 'Time' Properties ===")
        for prop_name, prop_value in time_channel.properties.items():
            print(f"{prop_name}: {prop_value}")
        
        # Get the actual data
        amplitude_data = amplitude_channel[:]
        time_data = time_channel[:]
        
        print(f"\n=== Data Analysis ===")
        print(f"Amplitude data shape: {amplitude_data.shape}")
        print(f"Time data shape: {time_data.shape}")
        print(f"Amplitude min: {np.min(amplitude_data):.6f}")
        print(f"Amplitude max: {np.max(amplitude_data):.6f}")
        print(f"Amplitude mean: {np.mean(amplitude_data):.6f}")
        print(f"Amplitude RMS: {np.sqrt(np.mean(amplitude_data**2)):.6f}")
        print(f"Time range: {time_data[0]:.6f} to {time_data[-1]:.6f} seconds")
        
        # Basic frequency analysis
        if len(amplitude_data) > 1:
            sample_rate = 1.0 / (time_data[1] - time_data[0])
            fft_result = np.fft.fft(amplitude_data)
            fft_freq = np.fft.fftfreq(len(amplitude_data), 1/sample_rate)
            
            # Find peak frequency
            magnitude = np.abs(fft_result[:len(fft_result)//2])
            freq_bins = fft_freq[:len(fft_freq)//2]
            peak_index = np.argmax(magnitude)
            detected_frequency = abs(freq_bins[peak_index])
            
            print(f"Calculated sample rate: {sample_rate:.2f} Hz")
            print(f"Detected peak frequency: {detected_frequency:.2f} Hz")