<<<<<<< HEAD
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

=======
# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The launcher - the thin supervisor.

It owns the process tree: it starts the Logger, CORE and (in GUI mode) the
frontend, and it is the parent of all of them. It must stay the simplest
component in the system, because it is the one that has to survive anything the
others do.

The tree is three processes in GUI mode - launcher, Logger, CORE, plus the GUI -1
and two in CLI mode, where the CLI runs here in the launcher's own process. The
Sequencer and the Report are not among them: they are threads inside CORE.

It also builds the HMI <-> CORE links, the only pair that still crosses a
process boundary and therefore the only pair whose messages are pickled.

The Debug Monitor is started beside the run, and it is **on by default**: running
this file with no arguments at all gives you the frontend and the Monitor
together, which is what a developer wants during the refactor and is the only way
to get it without a launcher script or an IDE configuration. `--no-debug-monitor`
turns it off for the runs that cannot use it - a headless bench, CI - and roadmap
§1.4.1 holds the revert TODO for v1.0, where it goes back to opt-in.

It is the one thing the launcher starts that is not part of the framework, and it
is started the way you would start it by hand - `subprocess.Popen` on `python -m
pypts.helper_applications.debug_monitor <this run's log>` - so that nothing here
imports the tool and the tool still cannot affect the run. See
`start_debug_monitor()` for what that costs and what it deliberately does not do.
"""

import argparse
import logging
import subprocess
import sys
import time
from multiprocessing import Process, Queue, get_start_method, set_start_method
from pathlib import Path

from pypts.config_handler import BootstrapOutcome, ConfigHandler
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
    # Children are always spawned, never forked - on every platform. Two
    # reasons. The bootstrap notice below can create a QApplication in this
    # process, and forking a process that holds live Qt state is unsupported
    # (children can abort or hang on the duplicated display connection). And
    # Windows - where all development runs - always spawns, so pinning spawn
    # makes Linux exercise the same code paths instead of quietly different
    # ones. Must happen before the first Queue() below: queues are built from
    # the default context at call time.
    if get_start_method(allow_none=True) != "spawn":
        set_start_method("spawn")

>>>>>>> 04a05cd756975e2dc007fe919cc630e4191643db
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
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Open the Debug Monitor on this run's log. On by default, so plainly "
            "running the launcher gives you the frontend and the Monitor together; "
            "pass --no-debug-monitor for a run without it - a headless bench or CI, "
            "where there is no display to open a window on. It is a separate "
            "program that only reads the log file, so it changes nothing about the "
            "run, and it is left open when the run ends. Needs --log-level DEBUG to "
            "have a message trace to show."
        ),
    )
    args = parser.parse_args()

<<<<<<< HEAD
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

=======
    # Before anything else, including logging: the configuration.
    # This is the one call that either open config.ini or creates it.
    # An existing file is never modified, and every other process only reads
    # it. A broken or version-mismatched file cannot stop the run: bootstrap()
    # discards it and runs on the template defaults, prompting user about it.
    config = ConfigHandler.bootstrap()

    if config.bootstrap_outcome is BootstrapOutcome.CREATED:
        show_config_popup(
            args.mode,
            "pypts configuration created",
            f"No configuration was found; a new one was created with default "
            f"values at:\n{config.config_path}",
            warning=False,
        )
    elif config.bootstrap_outcome is BootstrapOutcome.DISCARDED:
        show_config_popup(
            args.mode,
            "pypts configuration discarded",
            f"The configuration file could not be used:\n\n"
            f"{config.bootstrap_problem}\n\n"
            f"pypts is running on the default template in memory; no parameter "
            f"was taken from the file.\n"
            f"Correct it, or delete it to have it recreated:\n{config.config_path}",
            warning=True,
        )

    # Logging is set up now. The log file path is decided here exactly once
    # and owned by a single writer. The queue is what guarantees that no
    # parallel writes are made to the log file.

    log_queue = Queue()
    log_file_path = get_log_file_path(config.get_parameter("paths.logs_dir"))

    configured_level = args.log_level or config.get_parameter("logging.level")
    log_level = parse_log_level(configured_level)
    # -1 is not a level, so it survives only when the name meant nothing.
    level_was_understood = not configured_level or parse_log_level(configured_level, -1) != -1

    stdout_logging_enabled = args.mode == "gui"

    # Use as a separate pocess instead of standalone import (many writers)
    logger_process = Process(
        target=logger_main,
        name="Logger",
        args=(log_queue, log_file_path, stdout_logging_enabled),
    )
    logger_process.start()

    logger_control: QueueWrapper[LoggerControl] = QueueWrapper(log_queue, link=ANY_TO_LOGGER)
    init_logging(log_queue, log_level)

    # CORE-HMI process links
    to_core: QueueWrapper[HmiToCore] = QueueWrapper(Queue(), link=HMI_TO_CORE)
    to_hmi: QueueWrapper[CoreToHmi] = QueueWrapper(Queue(), link=CORE_TO_HMI)

    #: Held for the lifetime of the run. The launcher never waits on it and never kills it.
    core_process = None
    monitor_process = None
    try:
        # Everything the launcher did before there was a logger: since there is
        # no logging before log_path, the bootstrap actions are replayed and
        # logged now.
        config.replay_bootstrap_log()

        # Basic information about the runtime
        log.info("Run log: %s", log_file_path)
        log.info("Log level: %s", logging.getLevelName(log_level))
        if not level_was_understood:
            log.warning("Unknown log level: %r. Using the default.", configured_level)
        log.info(
            "Operating system: %s %s (%s)",
            config.get_parameter("operating_system.name"),
            config.get_parameter("operating_system.version"),
            config.get_parameter("operating_system.architecture"),
        )

        # Debug monitor is a developer-only helper application to trace and
        # simulate queue communication. To be removed after reaching stable build.
        if args.debug_monitor:
            monitor_process = start_debug_monitor(log_file_path, log_level)

        # Spawning CORE and UI
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
        # In case of shutdown of the launcher (instead of clean exit from the UI)
        stop_core(core_process, to_core)

        # Deliberately not stopped with the rest - for debugging purposes.
        # To be removed after reaching stable build.
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


def show_config_popup(mode: str, title: str, text: str, *, warning: bool) -> None:
    """
    Shows a pop-up if the configuration bootstrap raised any warnings.
    """
    if mode == "gui":
        try:
            _open_message_box(title, text, warning=warning)
            return
        except Exception:  # noqa: BLE001 - no display, no Qt: the banner below is the fallback
            pass
    _print_config_banner(title, text)


def _open_message_box(title: str, text: str, *, warning: bool) -> None:
    """One modal QMessageBox. Separate so tests can make it fail on purpose."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        QApplication([])
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setText(text)
    if warning:
        box.setIcon(QMessageBox.Icon.Warning)
    else:
        box.setIcon(QMessageBox.Icon.Information)
    box.exec()


def _print_config_banner(title: str, text: str) -> None:
    """The console form of the notice, framed so it survives scrollback."""
    line = "=" * 72
    print(line)
    print(title.upper())
    print()
    print(text)
    print(line)


def start_debug_monitor(log_file_path: str, log_level: int) -> subprocess.Popen | None:
    """
    Open the Debug Monitor
    This application is purely used for troubleshooting by the developer.
    To be removed after reaching stable run.

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
        monitor_process = subprocess.Popen(
            [sys.executable, "-m", DEBUG_MONITOR_MODULE, str(path)]
        )
    except OSError as error:
        log.warning("Debug Monitor could not be started: %s", error)
        return None

    log.info("Debug Monitor started (pid %d), reading %s", monitor_process.pid, path)
    return monitor_process


def stop_core(core_process: Process | None, to_core: QueueWrapper[HmiToCore]) -> None:
    """
    Bring CORE down, asking before killing.
    Normally, application is stopped by cleanly prompting it from the UI.
    But in case of closing the lancher, the application would be terminated too

    Like using CTRL+X on the terminal to stop.
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

>>>>>>> 04a05cd756975e2dc007fe919cc630e4191643db

if __name__ == "__main__":
    main()
