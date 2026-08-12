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
import logging
import sys
from multiprocessing import Process, Queue

from pypts.config_handler import ConfigError, ConfigHandler
from pypts.core.core import core_main
from pypts.hmi.cli.cli import cli_main
from pypts.hmi.gui.gui import gui_main
from pypts.logger.log import init_logging, log, logger_main, parse_log_level
from pypts.messages import Channel
from pypts.messages.hmi_link import CoreToHmi, HmiStopped, HmiToCore, ShutdownRequested
from pypts.messages.links import ANY_TO_LOGGER, CORE_TO_HMI, HMI_TO_CORE
from pypts.messages.logger_link import LoggerControl, StopLogger
from pypts.utilities.local_storage import get_log_file_path

#: How long CORE gets to shut itself down cleanly before it is killed.
CORE_SHUTDOWN_TIMEOUT_S = 5.0

#: How long the Logger gets to drain whatever is still queued.
LOGGER_SHUTDOWN_TIMEOUT_S = 5.0

#: Exit code for a configuration pypts cannot work with. Distinct from 1, so a
#: script can tell "your config.ini is wrong" from "the run failed".
CONFIG_EXIT_CODE = 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["gui", "cli", "connect"],
        default="gui",
        help="Choose the app mode: GUI (default), CLI, or connect",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help=(
            "Minimum level written to the run log. DEBUG adds the message trace: "
            "every message on every link, as it is sent and as it is received. "
            "Overrides [logging] level in config.ini."
        ),
    )
    args = parser.parse_args()

    # Before anything else, including logging: the configuration is what says
    # where the log file goes. This is the one call that may create or migrate
    # config.ini - every other process only reads it. Nothing here can be
    # logged yet, so the handler buffers its own messages and they are replayed
    # below, once there is somewhere to put them.
    try:
        config = ConfigHandler.bootstrap()
    except ConfigError as error:
        # The file is meant to be edited by hand, so the likeliest cause is a
        # typo in it. There is no log yet and never will be on this path, so the
        # message goes to stderr and the traceback is suppressed: it would only
        # bury the one line that says what to fix.
        print(f"pypts cannot start: {error}", file=sys.stderr)
        raise SystemExit(CONFIG_EXIT_CODE) from None

    # Logging is set up before anything else, so that no module has to fall back
    # to an uninitialised logger. The log file path is decided here exactly once
    # and owned by a single writer - the Logger process - which every other
    # process reaches through log_queue. See logger/log.py for the reasoning.
    log_queue = Queue()
    log_file_path = get_log_file_path(config.get_parameter("paths.logs_dir"))

    # Resolved once, here, and passed to every process, so that one run is
    # captured at one level throughout - a child reading the config for itself
    # would not know about --log-level, and half the run would be at the other
    # level.
    #
    # parse_log_level() falls back rather than raising, so an unusable name
    # cannot stop the application from starting; the warning comes below.
    configured_level = args.log_level or config.get_parameter("logging.level")
    log_level = parse_log_level(configured_level)
    # -1 is not a level, so it survives only when the name meant nothing.
    level_was_understood = not configured_level or parse_log_level(configured_level, -1) != -1

    # The Logger owns the console handler, so this choice applies to every
    # process. The GUI wants it: with no terminal of its own, the launcher's
    # console is where its log is read. The CLI does not, because its own
    # print()-based shell shares that console.
    stdout_logging_enabled = args.mode == "gui"

    logger_process = Process(
        target=logger_main,
        name="Logger",
        args=(log_queue, log_file_path, stdout_logging_enabled),
    )
    logger_process.start()

    logger_control: Channel[LoggerControl] = Channel(log_queue, link=ANY_TO_LOGGER)
    init_logging(log_queue, log_level)

    # The one process boundary in the framework. Swapping Queue() for
    # queue.Queue() here is all it takes to run CORE's submodules as threads;
    # no module below ever learns which one it holds.
    to_core: Channel[HmiToCore] = Channel(Queue(), link=HMI_TO_CORE)
    to_hmi: Channel[CoreToHmi] = Channel(Queue(), link=CORE_TO_HMI)

    core_process = None
    try:
        # Everything the configuration did before there was a logger: which file
        # it used, whether it had to create or migrate it, and any section it
        # did not recognise. Replayed first, because it explains the paths the
        # rest of this run is about to use.
        config.replay_bootstrap_log()

        # The log file names itself. The Logger announces this on the console
        # too, but it has to: it is the one component that cannot log about
        # logging. That leaves the file itself silent about where it lives,
        # which matters as soon as a log is copied off the machine that wrote
        # it - and it is the proof that paths.logs_dir was actually honoured.
        log.info("Run log: %s", log_file_path)

        # Recorded next, so the log always says what it was configured to
        # capture - the answer to "why is the trace missing from this file".
        log.info("Log level: %s", logging.getLevelName(log_level))
        if not level_was_understood:
            log.warning("Unknown log level: %r. Using the default.", configured_level)

        # Recorded once per run, so a report can say which machine produced it.
        log.info(
            "Operating system: %s %s (%s)",
            config.get_parameter("operating_system.name"),
            config.get_parameter("operating_system.version"),
            config.get_parameter("operating_system.architecture"),
        )

        core_process = Process(
            target=core_main,
            name="Core",
            args=(to_hmi, to_core, log_queue, log_level),
        )
        core_process.start()

        if args.mode == "gui":
            ui_process = Process(
                target=gui_main, name="GUI", args=(to_core, to_hmi, log_queue, log_level)
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
