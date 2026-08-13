# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The launcher - the thin supervisor.

It owns the process tree: it starts the Logger, CORE and (in GUI mode) the
frontend, and it is the parent of all of them. It must stay the simplest
component in the system, because it is the one that has to survive anything the
others do.

The tree is three processes in GUI mode - launcher, Logger, CORE, plus the GUI -
and two in CLI mode, where the CLI runs here in the launcher's own process. The
Sequencer and the Report are not among them: they are threads inside CORE.

It also builds the HMI <-> CORE links, the only pair that still crosses a
process boundary and therefore the only pair whose messages are pickled.

`--debug-monitor` starts the Debug Monitor beside the run. It is the one thing
the launcher starts that is not part of the framework, and it is started the way
you would start it by hand - `subprocess.Popen` on `python -m
pypts.helper_applications.debug_monitor <this run's log>` - so that nothing here
imports the tool and the tool still cannot affect the run. See
`start_debug_monitor()` for what that costs and what it deliberately does not do.
"""

import argparse
import logging
import subprocess
import sys
import time
from multiprocessing import Process, Queue
from pathlib import Path

from pypts.config_handler import ConfigError, ConfigHandler
from pypts.core.core import core_main
from pypts.hmi.cli.cli import cli_main
from pypts.hmi.gui.gui import gui_main
from pypts.logger.log import init_logging, log, logger_main, parse_log_level
from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    ShutdownRequested,
)
from pypts.messages.links import ANY_TO_LOGGER, CORE_TO_HMI, HMI_TO_CORE
from pypts.messages.to_logger_communication import LoggerControl, StopLogger
from pypts.utilities.local_storage import get_log_file_path

#: How long CORE gets to shut itself down cleanly before it is killed.
CORE_SHUTDOWN_TIMEOUT_S = 5.0

#: How long the Logger gets to drain whatever is still queued.
LOGGER_SHUTDOWN_TIMEOUT_S = 5.0

#: Exit code for a configuration pypts cannot work with. Distinct from 1, so a
#: script can tell "your config.ini is wrong" from "the run failed".
CONFIG_EXIT_CODE = 2

#: The Debug Monitor's entry point, spelled as `-m` takes it. A string rather
#: than an import: the launcher must not import the tool. See §1.4.
DEBUG_MONITOR_MODULE = "pypts.helper_applications.debug_monitor"

#: How long the launcher waits for the Logger to create the run log before it
#: gives up on starting the Monitor. The Monitor refuses a path that is not yet
#: a file, and the file is created by the Logger process, not by this one.
MONITOR_LOG_WAIT_S = 5.0

#: How often it looks while waiting. Short enough that the usual case - the file
#: is already there - costs one `exists()` and no sleep at all.
MONITOR_LOG_POLL_S = 0.05


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
    parser.add_argument(
        "--debug-monitor",
        action="store_true",
        help=(
            "Also open the Debug Monitor on this run's log. It is a separate "
            "program that only reads the log file, so it changes nothing about "
            "the run, and it is left open when the run ends. Needs "
            "--log-level DEBUG to have a message trace to show."
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

    logger_control: QueueWrapper[LoggerControl] = QueueWrapper(log_queue, link=ANY_TO_LOGGER)
    init_logging(log_queue, log_level)

    # The one process boundary in the framework, and so the only place a
    # multiprocessing queue is still needed. CORE builds its own links out of
    # queue.Queue, because the modules on the other end are its own threads.
    to_core: QueueWrapper[HmiToCore] = QueueWrapper(Queue(), link=HMI_TO_CORE)
    to_hmi: QueueWrapper[CoreToHmi] = QueueWrapper(Queue(), link=CORE_TO_HMI)

    core_process = None
    #: Held for the lifetime of the run only so that the Popen object is not
    #: collected while its child is alive. The launcher never waits on it and
    #: never kills it - see start_debug_monitor().
    monitor_process = None
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

        # Before CORE, so that the Monitor is already following when the first
        # messages of the run are traced. It reads the file from the beginning
        # in any case, so this only saves it some catching up.
        if args.debug_monitor:
            monitor_process = start_debug_monitor(log_file_path, log_level)

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

        # Deliberately not stopped with the rest. The trace of the run that has
        # just ended is what you want to read *after* it ends, and a reader of a
        # file leaves nothing behind. The last lines it will see are the ones
        # below.
        if monitor_process is not None and monitor_process.poll() is None:
            log.info(
                "Debug Monitor (pid %d) left running; close its window when you are done.",
                monitor_process.pid,
            )

        log.info("Stopping logger...")
        # A queued message, so the Logger acts on it only after writing
        # everything already in flight.
        logger_control.send(StopLogger())
        logger_process.join(timeout=LOGGER_SHUTDOWN_TIMEOUT_S)
        if logger_process.is_alive():
            logger_process.terminate()


def start_debug_monitor(log_file_path: str, log_level: int) -> subprocess.Popen | None:
    """
    Open the Debug Monitor on this run's log, without letting it touch the run.

    Started as a *program*, not as an import: `python -m
    pypts.helper_applications.debug_monitor <log file>`, through the same
    interpreter that is running pypts. That spelling is the whole point. The
    tool reads the run log and nothing else (roadmap §1.4), and keeping it
    behind `subprocess` means `startup.py` has no import of it, no message from
    it and no way for it to raise into the launcher - the framework still has no
    idea it exists, it is merely started at the same time.

    The log file is passed explicitly rather than letting the Monitor pick the
    newest one. Its default is "the most recently modified pypts_*.log", which is
    this run right up until someone starts a second one, and being pointed at the
    wrong run is exactly the kind of confusion a debug tool must not create.

    Nothing here can stop a run. Every failure - no log file, no PySide6, no
    interpreter - is a warning in the log and a `None` return, because the run
    the operator asked for matters more than the window they also asked for.

    Args:
        log_file_path: the run log the Monitor is to follow. It may not exist
            yet; this waits up to `MONITOR_LOG_WAIT_S` for the Logger to create
            it, since the Monitor exits rather than opening a window onto a path
            that is not a file.
        log_level: the level this run was resolved to, used only to warn when it
            is above DEBUG - the trace is written at DEBUG and nowhere else, so
            the Monitor would open onto an empty table and not say why.

    Returns:
        The child process, or None if it could not be started. The caller holds
        the handle so that it is not collected while the child lives; it is
        never waited on and never killed.
    """
    if log_level > logging.DEBUG:
        log.warning(
            "Debug Monitor asked for, but this run logs at %s: the message trace is "
            "written at DEBUG only, so its Trace tab will stay empty. Use --log-level DEBUG.",
            logging.getLevelName(log_level),
        )

    path = Path(log_file_path)
    deadline = time.monotonic() + MONITOR_LOG_WAIT_S
    while not path.is_file():
        if time.monotonic() >= deadline:
            log.warning(
                "Debug Monitor not started: the Logger did not create %s within %.0f s.",
                path,
                MONITOR_LOG_WAIT_S,
            )
            return None
        time.sleep(MONITOR_LOG_POLL_S)

    try:
        # No shell, and sys.executable is an absolute path decided by the
        # running interpreter, so there is nothing here to inject into.
        monitor_process = subprocess.Popen(
            [sys.executable, "-m", DEBUG_MONITOR_MODULE, str(path)]
        )
    except OSError as error:
        # OSError covers the interpreter being unusable; an ImportError inside
        # the child (no PySide6) cannot reach here at all - it is the child's
        # traceback on the child's stderr, and the run carries on regardless.
        log.warning("Debug Monitor could not be started: %s", error)
        return None

    log.info("Debug Monitor started (pid %d), reading %s", monitor_process.pid, path)
    return monitor_process


def stop_core(core_process: Process | None, to_core: QueueWrapper[HmiToCore]) -> None:
    """
    Bring CORE down, asking before killing.

    The launcher has just joined the frontend, so it can state as fact that the
    HMI has stopped - CORE would otherwise wait for an acknowledgement from a
    process that no longer exists. It then asks for shutdown on the same
    link, because CORE having exactly one shutdown path is worth more than
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
