# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The launcher - the thin supervisor.

It owns the process tree: it starts the Logger, CORE and (in GUI mode) the
frontend, and it is the parent of all of them. It must stay the simplest
component in the system, because it is the one that has to survive anything the
others do.

It also builds the HMI <-> CORE channels. Which queue type they wrap is decided
here and nowhere else, which is what makes the roadmap's thread migration a
change to this file alone.
"""

import argparse
from multiprocessing import Process, Queue

from pypts.config_handler.config_handler import read_config_key
from pypts.core.core import core_main
from pypts.hmi.cli.cli import cli_main
from pypts.hmi.debug.console import debug_main
from pypts.hmi.debug.tap import ChannelTap
from pypts.hmi.gui.gui import gui_main
from pypts.logger.log import init_logging, log, logger_main
from pypts.messages import Channel
from pypts.messages.debug_link import CORE_TO_HMI, HMI_TO_CORE
from pypts.messages.hmi_link import CoreToHmi, HmiStopped, HmiToCore, ShutdownRequested
from pypts.messages.logger_link import LoggerControl, StopLogger
from pypts.utilities.local_storage import get_log_file_path

#: How long CORE gets to shut itself down cleanly before it is killed.
CORE_SHUTDOWN_TIMEOUT_S = 5.0

#: How long the Logger gets to drain whatever is still queued.
LOGGER_SHUTDOWN_TIMEOUT_S = 5.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["gui", "cli", "connect", "debug"],
        default="debug",
        # The default is the developer console for the duration of the refactor:
        # the execution engine is a stub, so a bare `python -m pypts` is far more
        # useful showing the message layer than showing an idle status label.
        # This must go back to "gui" before v1.0 - it is a TODO in the roadmap.
        help="Choose the app mode: GUI, CLI, connect, or debug (developer console, default)",
    )
    args = parser.parse_args()
    debugging = args.mode == "debug"

    # Logging is set up before anything else, so that no module has to fall back
    # to an uninitialised logger. The log file path is decided here exactly once
    # and owned by a single writer - the Logger process - which every other
    # process reaches through log_queue. See logger/log.py for the reasoning.
    log_queue = Queue()
    log_file_path = get_log_file_path()

    # The Logger owns the console handler, so this choice applies to every
    # process. Both windowed modes want it: with no terminal of their own, the
    # launcher's console is where their log is read.
    stdout_logging_enabled = args.mode in ("gui", "debug")

    # The debug path exists only under --mode debug. In every other mode `tap`
    # stays None, so Channel.send() takes the same branch it always did and no
    # message pays for tooling nobody asked for.
    tap = None
    tap_records = None
    debug_commands = None
    if debugging:
        tap_records = Queue()
        debug_commands = Queue()
        tap = ChannelTap(tap_records)

    logger_process = Process(
        target=logger_main,
        name="Logger",
        args=(log_queue, log_file_path, stdout_logging_enabled),
    )
    logger_process.start()

    logger_control: Channel[LoggerControl] = Channel(log_queue)
    init_logging(log_queue)

    # The one process boundary in the framework. Swapping Queue() for
    # queue.Queue() here is all it takes to run CORE's submodules as threads;
    # no module below ever learns which one it holds.
    to_core: Channel[HmiToCore] = Channel(Queue(), link=HMI_TO_CORE, observer=tap)
    to_hmi: Channel[CoreToHmi] = Channel(Queue(), link=CORE_TO_HMI, observer=tap)

    core_process = None
    try:
        # OS details come from the config, which fills them in when it is created.
        log.info("os_name: " + read_config_key("OperatingSystem", "name"))
        log.info("os_version: " + read_config_key("OperatingSystem", "version"))

        # `tap` and the debug inbox are None outside --mode debug, and CORE then
        # builds exactly the channels it built before.
        core_process = Process(
            target=core_main,
            name="Core",
            args=(to_hmi, to_core, log_queue, tap, _channel_or_none(debug_commands)),
        )
        core_process.start()

        if args.mode == "gui":
            ui_process = Process(target=gui_main, name="GUI", args=(to_core, to_hmi, log_queue))
            ui_process.start()
            ui_process.join()
        elif debugging:
            # The console reads the tap and writes injections. Neither queue is
            # wrapped in an observed Channel: a tap that recorded its own traffic
            # would feed itself.
            ui_process = Process(
                target=debug_main,
                name="DebugConsole",
                args=(
                    to_core,
                    to_hmi,
                    log_queue,
                    Channel(tap_records),
                    Channel(debug_commands),
                ),
            )
            ui_process.start()
            ui_process.join()
        else:
            # The CLI runs here in the launcher's own process, so there is no
            # third process in CLI mode.
            cli_main(to_core, to_hmi)
    finally:
        # Order matters: CORE first, the Logger last, both in the finally block
        # so that an exception in the UI can neither leave a process behind nor
        # cut the log short before the shutdown was recorded.
        stop_core(core_process, to_core)

        log.info("Stopping logger...")
        # A queued message, so the Logger acts on it only after writing
        # everything already in flight.
        logger_control.send(StopLogger())
        logger_process.join(timeout=LOGGER_SHUTDOWN_TIMEOUT_S)
        if logger_process.is_alive():
            logger_process.terminate()


def _channel_or_none(queue) -> Channel | None:
    """Wrap a queue that may not exist. Saves the caller an if/else that would
    only be about --mode debug."""
    return None if queue is None else Channel(queue)


def stop_core(core_process: Process | None, to_core: Channel[HmiToCore]) -> None:
    """
    Bring CORE down, asking before killing.

    The launcher has just joined the frontend, so it can state as fact that the
    HMI has stopped - CORE would otherwise wait for an acknowledgement from a
    process that no longer exists. It then asks for shutdown on the same
    channel, because CORE having exactly one shutdown path is worth more than
    the launcher having a link of its own.

    terminate() stays, but only as the timeout fallback it should always have
    been. As the primary path it gave CORE no chance to stop its own children,
    which is why they were left orphaned.
    """
    if core_process is None:
        return

    to_core.send(HmiStopped())
    to_core.send(ShutdownRequested())
    core_process.join(timeout=CORE_SHUTDOWN_TIMEOUT_S)

    if core_process.is_alive():
        log.warning("Core did not shut down in time; terminating it.")
        core_process.terminate()
        core_process.join(timeout=CORE_SHUTDOWN_TIMEOUT_S)


if __name__ == "__main__":
    main()
