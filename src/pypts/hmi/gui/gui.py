# gui.py
from time import sleep
from queue import Queue
from pypts.core.CoreInterface import HMIToCoreInterface

def gui_main(coreInterface: HMIToCoreInterface, core_to_hmi_queue: Queue):
    while True:
        # GUI sends commands TO core
        coreInterface.start_sequence("Test sequence")

        # GUI receives messages FROM core
        event = core_to_hmi_queue.get_nowait()
        if event:
            print("[GUI] Received:", event)

        sleep(1)