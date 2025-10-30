# gui.py
import time
from hmi import QueueHMI

def gui(gui_to_hmi, core_to_hmi):
    hmi = QueueHMI(gui_to_hmi, core_to_hmi)

    while True:
        hmi.send_command_to_core("Hello core :)")
        msg = hmi.receive_core_command()
        print(f"GUI received: {msg}")
        time.sleep(1)



# hmi.load_recipe("/path/to/recipe.yml")