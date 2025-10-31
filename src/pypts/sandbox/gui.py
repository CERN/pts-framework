from hmi import *
import time

def gui_main(hmi: HMIInterface):
    while True:
        time.sleep(1)
        hmi.send_command_to_core("Hello core, from GUI")
