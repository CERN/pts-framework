from hmi import *
import time

def cli_main(hmi: HMIInterface):
    while True:
        time.sleep(1)
        hmi.send_command_to_core("Hello core, from CLI")
        print(f"CLI received: {hmi.receive_command_from_core()}")
