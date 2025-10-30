# core.py
from hmi import QueueHMI

def core(hmi_to_core, core_to_hmi):
    hmi = QueueHMI(hmi_to_core, core_to_hmi)

    while True:
        msg = hmi.HMI_to_core.get()
        print(f"Core received: {msg}")
        hmi.core_to_HMI.put("Hey, how are you?")
