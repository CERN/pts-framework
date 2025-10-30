import threading
import time
import numpy as np
from datetime import datetime
import csv
import random 

# framework related imports
from pypts.XYGraph.StreamContainer import *

class Simulated_sine_wave(threading.Thread):
    def __init__(self, name, randomize=False, frequency=2, sampling_rate=100, amplitude=1):
        super().__init__()
        #stop event and thread to be registered at start
        self.randomize = randomize
        if self.randomize:
            self.frequency = random.randint(1, 2) #higher frequencies require optimization/hardware support or running in the different thread
            self.sampling_rate = self.frequency * 10
            self.noise = random.uniform(0.01, 0.2)
            self.amplitude = amplitude
        else:
            self.frequency = frequency
            self.sampling_rate = self.frequency * 10
            self.noise = 0.02
            self.amplitude = amplitude
        self.name = name
        self.file_name = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{self.name}.csv"
        self.stop_event = None
        self.thread = None
        self.stream = None

    def run(self):
        print("Signal generation starting...")
        dt = 1 / self.sampling_rate
        # Open the CSV file for writing

        with open(self.file_name, mode='w', newline='', buffering=1) as csv_file:
            writer = csv.writer(csv_file)
            # Write the header row
            writer.writerow(["Timestamp", "Signal"])

            # Generate and write data to the CSV file
            while not self.stop_event.is_set():
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # Human-readable format
                sine_wave = self.amplitude*(np.sin(2 * np.pi * self.frequency * (time.time())))
                sine_wave = sine_wave + random.uniform(-1*self.noise, self.noise)
                # Write the data (timestamp and sine wave value)
                writer.writerow([timestamp, sine_wave])
                # print("data point: " + str(sine_wave))
                # flush the file to refresh it
                csv_file.flush()
                # Sleep to simulate sampling rate
                time.sleep(dt)

        print("Signal generation stopped.")
        return

    def start_acquisition(self):
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run)  # Create a thread for the `run` method
        self.thread.start()
        self.stream = Stream(name = self.name, hook=self.file_name, frequency=self.frequency)
        print(f"Signal generator {self.name} has been spawned")
        return
    
    def stop_acquisition(self):
        self.stop_event.set()
        self.thread.join()
        # container.remove_stream(self.stream)
        self.stream.kill()
        print(f"Signal generator {self.name} has been terminated")
        del(self)
        return
#
#
# if __name__ == "__main__":
#     my_signal = Simulated_sine_wave(name="hehe")
#     my_signal.start_acquisition()
#     streamlist = container.get_all_streams()
#     for stream in streamlist:
#         print(f"Retrieved registered stream {stream.name}. Stream is tied with {stream.hook} hook.")
#
#     time.sleep(3)
#     my_signal.stop_acquisition()