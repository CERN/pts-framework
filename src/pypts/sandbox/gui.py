# gui.py
import time
from hmi import QueueHMI

def gui(gui_to_core, core_to_gui):
    hmi = QueueHMI(gui_to_core, core_to_gui)

    while True:
        hmi.send_command_to_core("Hello core :)")
        msg = hmi.receive_core_command()
        print(f"GUI received: {msg}")
        time.sleep(1)
