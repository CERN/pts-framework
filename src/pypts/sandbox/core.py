# core.py
from hmi import QueueHMI

def core(gui_to_core, core_to_gui):
    hmi = QueueHMI(gui_to_core, core_to_gui)

    while True:
        msg = hmi.HMI_to_core.get()
        print(f"Core received: {msg}")
        hmi.core_to_HMI.put("Hey, how are you?")
