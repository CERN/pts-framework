from multiprocessing import Process, Queue
from pypts.hmi.hmi import QueueHMI
from core import core_main
from pypts.hmi.gui.gui import gui_main
from pypts.hmi.cli.cli import cli_main

import argparse
def main():
    parser = argparse.ArgumentParser(description="System launcher")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode instead of GUI")
    parser.add_argument("--gui", action="store_true", help="Run in GUI mode (default)")
    args = parser.parse_args()
    # todo - initialize logger and config singletons
    # todo - add runtime and debug logs showing the status

    # initialize the CORE - HMI queues
    hmi_to_core_queue = Queue()
    core_to_hmi_queue = Queue()
    hmi = QueueHMI(hmi_to_core_queue, core_to_hmi_queue)

    # --- Determine which UI to run ---
    if args.cli:
        ui_target = cli_main
        ui_name = "CLI"
    elif args.gui or not (args.cli or args.gui):
        # default to GUI if nothing specified
        ui_target_main = gui_main
        ui_name = "GUI"
    else:
        raise ValueError("Invalid mode selected. Use --cli or --gui.")

    # spawn the CORE main -> it will create the object and spawn necessary submodules
    p_core = Process(target=core_main, args=(hmi,))
    p_core.start()
    print(f"[launcher] CORE started.")

    # spawn the GUI/CLI main
    p_ui = Process(target=ui_target_main, args=(hmi,))
    p_ui.start()
    print(f"[launcher] {ui_name} started.")

    # todo - add the exit codes and parse -> log them
    p_core.join()
    p_ui.join()


if __name__ == "__main__":
    main()
