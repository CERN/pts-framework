from multiprocessing import Process, Queue
from pypts.core.core import core_main
from pypts.hmi.gui.gui import gui_main
from pypts.hmi.cli.cli import cli_main
from pypts.hmi.core_to_HMI_interface import CoreToHMIQueue
from pypts.core.HMI_to_core_interface import HMIToCoreQueue
import argparse
from pypts.logger.log import log, set_stdout_logging_enabled
from pypts.config_handler.config_handler import read_config_key

def main():
    # Parse command-line argument for selecting mode of operation
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gui", "cli", "connect"], default="gui",
                        help="Choose the app mode: GUI, CLI, or connect")
    args = parser.parse_args()

    # Log operating system details retrieved from config (auto-updated on config creation)
    log.info("os_name: " + read_config_key("OperatingSystem", "name"))
    log.info("os_version: " + read_config_key("OperatingSystem", "version"))

    # Setup inter-process communication queues for interaction between UI and core process
    # For scalability, consider Manager or external IPC when extending to multi-client
    hmi_to_core_queue = Queue()
    core_to_hmi_queue = Queue()

    # Create interface objects wrapping the queues for HMI (UI) to Core communication and vice versa
    hmi_interface = HMIToCoreQueue(hmi_to_core_queue)
    core_interface = CoreToHMIQueue(core_to_hmi_queue)

    # Enable or disable stdout logging based on UI mode (enable for GUI for verbose output)
    if args.mode == "gui":
        set_stdout_logging_enabled(True)
    else:
        set_stdout_logging_enabled(False)

    # Spawn the Core process with communication interfaces
    p_core = Process(target=core_main, args=(core_interface, hmi_to_core_queue))
    p_core.start()

    # Depending on mode, spawn GUI process or run CLI interface in the main process
    if args.mode == "gui":
        p_ui = Process(target=gui_main, args=(hmi_interface, core_to_hmi_queue))
        p_ui.start()
        # Wait for GUI process to complete (blocking)
        p_ui.join()
    else:
        # Run CLI interface directly (blocking)
        cli_main(hmi_interface, core_to_hmi_queue)

    # Terminate core process when UI/CLI ends
    p_core.terminate()

if __name__ == "__main__":
    main()
