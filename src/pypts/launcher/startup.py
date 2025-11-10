from multiprocessing import Process, Queue
from pypts.core.core import core_main
from pypts.core.core_interface import HMIToCoreQueue
from pypts.hmi.HMIInterface import CoreToHMIQueue
from pypts.hmi.gui.gui import gui_main
from pypts.hmi.cli.cli import cli_main
from pypts.logger.log import log

import argparse


def main():
    parser = argparse.ArgumentParser(description="System launcher")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode instead of GUI")
    parser.add_argument("--gui", action="store_true", help="Run in GUI mode (default)")
    args = parser.parse_args()

    # initialize the CORE - HMI queues
    hmi_to_core_queue = Queue()
    core_to_hmi_queue = Queue()
    CoreToHmiInterface = CoreToHMIQueue(core_to_hmi_queue)
    HMIToCoreInterface = HMIToCoreQueue(hmi_to_core_queue)

    # hmiInterface: CoreToHMIQueue
    # hmi_to_core_queue: Queue

    # --- Determine which UI to run ---
    if args.cli:
        ui_target = cli_main
        ui_name = "CLI"
    elif args.gui or not (args.cli or args.gui):
        # default to GUI if nothing specified
        ui_target = gui_main
        ui_name = "GUI"
    else:
        raise ValueError("Invalid mode selected. Use --cli or --gui.")

    # spawn the CORE main -> it will create the object and spawn necessary submodules
    p_core = Process(target=core_main, args=(CoreToHmiInterface, hmi_to_core_queue))
    p_core.start()
    log.info(f"[launcher] CORE started.")

    # spawn the GUI/CLI main
    p_ui = Process(target=ui_target, args=(HMIToCoreInterface, core_to_hmi_queue))
    p_ui.start()
    log.info(f"[launcher] {ui_name} started.")

    p_core.join()
    p_ui.join()


if __name__ == "__main__":
    main()
