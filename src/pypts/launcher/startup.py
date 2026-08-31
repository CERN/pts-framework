import argparse
from multiprocessing import Process, Queue, set_start_method

from pypts.core.core import core_main
from pypts.hmi.gui.gui import gui_main
from pypts.hmi.cli.cli import cli_main
from pypts.hmi.core_to_HMI_interface import CoreToHMIQueue
from pypts.core.HMI_to_core_interface import HMIToCoreQueue
from pypts.logger.log import log, set_stdout_logging_enabled
from pypts.config_handler.config_handler import read_config_key


def main():
    # Force "spawn" on every platform so Linux and Windows exercise the same
    # process-startup path. Without this, Linux defaults to "fork" (pre-3.14)
    # and hides bugs that surface only under Windows spawn.
    try:
        set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gui", "cli", "connect"], default="gui",
                        help="Choose the app mode: GUI, CLI, or connect")
    args = parser.parse_args()

    log.info("os_name: " + read_config_key("OperatingSystem", "name"))
    log.info("os_version: " + read_config_key("OperatingSystem", "version"))

    hmi_to_core_queue = Queue()
    core_to_hmi_queue = Queue()

    hmi_interface = HMIToCoreQueue(hmi_to_core_queue)
    core_interface = CoreToHMIQueue(core_to_hmi_queue)

    set_stdout_logging_enabled(args.mode == "gui")

    p_core = Process(target=core_main, args=(core_interface, hmi_to_core_queue))
    p_core.start()

    if args.mode == "gui":
        p_ui = Process(target=gui_main, args=(hmi_interface, core_to_hmi_queue))
        p_ui.start()
        p_ui.join()
    else:
        cli_main(hmi_interface, core_to_hmi_queue)

    # UI is expected to send EXIT to Core before shutting down, so Core should
    # be draining. Give it time to close cleanly; only kill if it stalls.
    p_core.join(timeout=10)
    if p_core.is_alive():
        log.warning("Core did not exit gracefully within 10s, terminating.")
        p_core.terminate()
        p_core.join(timeout=5)
        if p_core.is_alive():
            p_core.kill()


if __name__ == "__main__":
    main()
