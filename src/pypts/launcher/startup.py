# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The launcher - the thin supervisor.

It owns the process tree: it starts the Logger, CORE and (in GUI mode) the
frontend, and it is the parent of all of them. It must stay the simplest
component in the system, because it is the one that has to survive anything the
others do.

The tree is four processes in GUI mode - launcher, Logger, CORE and the GUI - and
three in CLI mode, where the CLI runs here in the launcher's own process. The
Sequencer and the Report are not among them: they are threads inside CORE.

It also builds the HMI <-> CORE links, the only pair that still crosses a
process boundary and therefore the only pair whose messages are pickled.

The engine half - configuration, Logger, CORE and the links - is start_engine()
and stop_engine(), separate from main() so that pypts.api can start the very
same engine under code instead of under a frontend. run_gui() is the GUI half,
shared the same way.

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
import getpass
import importlib
import logging
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from multiprocessing import Process, Queue, get_start_method, set_start_method
from pathlib import Path
from typing import Any, NoReturn

from pypts._version import __version__
from pypts.config_handler import BootstrapOutcome, ConfigHandler
from pypts.core.core import core_main
from pypts.hmi.cli.cli import cli_main
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

#: The exit code of a command line argparse rejects. argparse's own is 2, which
#: headless mode already uses for a run that ended in ERROR or STOP, so a bad
#: argument exits with headless mode's "there was no run" instead
#: (pypts.api.headless.EXIT_NOT_RUN - not imported, see main()).
USAGE_EXIT_CODE = 3


@dataclass
class Engine:
    """
    One running pypts session without its frontend: the Logger and CORE
    processes, and the two links a frontend talks to CORE on.

    Built by start_engine() and ended by stop_engine(). The launcher puts the
    GUI or the CLI on top of it; pypts.api puts code on top of it.
    """

    mode: str
    log_queue: Any
    log_level: int
    log_file_path: str
    logger_process: Process
    logger_control: QueueWrapper[LoggerControl]
    to_core: QueueWrapper[HmiToCore]
    to_hmi: QueueWrapper[CoreToHmi]
    #: Held for the lifetime of the run. Nothing waits on it but stop_engine().
    core_process: Process | None = None
    monitor_process: subprocess.Popen | None = None


class ArgumentParser(argparse.ArgumentParser):
    """argparse, exiting with USAGE_EXIT_CODE on a bad command line."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(USAGE_EXIT_CODE, f"{self.prog}: error: {message}\n")


def main() -> None:
    parser = ArgumentParser(prog="python -m pypts")
    parser.add_argument(
        "--mode",
        choices=["gui", "cli", "headless"],
        default="gui",
        help=(
            "Choose the app mode: GUI (default), CLI, or headless - run one recipe "
            "with nobody at the keyboard and exit with a code a CI pipeline can check"
        ),
    )
    parser.add_argument(
        "--recipe",
        default=None,
        help="Headless mode only, and required there: the recipe file to run.",
    )
    parser.add_argument(
        "--sequence",
        default=None,
        help="Headless mode only: the sequence to run. Default: the recipe's main sequence.",
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
        default=None,
        help=(
            "Open the Debug Monitor on this run's log. On by default in gui and cli "
            "mode, so plainly running the launcher gives you the frontend and the "
            "Monitor together; off by default in headless mode. Pass "
            "--no-debug-monitor for a run without it - a headless bench or CI, "
            "where there is no display to open a window on. It is a separate "
            "program that only reads the log file, so it changes nothing about the "
            "run, and it is left open when the run ends. Needs --log-level DEBUG to "
            "have a message trace to show."
        ),
    )
    args = parser.parse_args()

    if args.mode == "headless":
        if args.recipe is None:
            parser.error("--mode headless needs --recipe")
    elif args.recipe is not None or args.sequence is not None:
        parser.error("--recipe and --sequence are for --mode headless only")

    # None means the flag was not given: the Monitor is a window, and a
    # headless run is the one kind that has nobody to look at it.
    debug_monitor = args.debug_monitor
    if debug_monitor is None:
        debug_monitor = args.mode != "headless"

    # Headless mode is pypts.api.Pts with a console, and Pts starts the engine
    # itself. Imported here, not at the top: pypts.api imports this module.
    if args.mode == "headless":
        from pypts.api.headless import headless_main

        sys.exit(headless_main(args.recipe, args.sequence, args.log_level, debug_monitor))

    # The GUI is imported only when one is going to be started. PySide6 is the
    # one heavy dependency in the tree and `pypts.hmi.gui.gui` is the only door
    # to it - nothing in CORE, the Logger, the messages or the engine imports Qt
    # at all. As a module-level import this line made `--mode cli` fail outright
    # on a headless bench with no Qt system libraries, for a frontend that run
    # was never going to open. That bench is exactly what --no-debug-monitor
    # exists for, so it has to be able to run.
    #
    # Nothing has been created yet at this point, so a missing PySide6 is a
    # plain message and an exit rather than a traceback over a half-built run.
    if args.mode == "gui":
        try:
            importlib.import_module("pypts.hmi.gui.gui")
        except ImportError as error:
            # There is no logger yet, which is why this prints - the same reason
            # _print_config_banner() does.
            print(
                "GUI mode needs PySide6, which cannot be loaded on this machine:\n"
                f"  {error}\n"
                "Install it, or start pypts with --mode cli instead.",
                file=sys.stderr,
            )
            sys.exit(1)

    engine = start_engine(args.mode, args.log_level, debug_monitor)
    try:
        if args.mode == "gui":
            run_gui(engine)
        else:
            # The CLI runs here in the launcher's own process, so there is no
            # fourth process in CLI mode.
            log.debug("Running the CLI in the launcher process.")
            cli_main(engine.to_core, engine.to_hmi)
    finally:
        # In case of shutdown of the launcher (instead of clean exit from the UI)
        stop_engine(engine)


def pin_spawn_start_method() -> None:
    """
    Children are always spawned, never forked - on every platform.

    Two reasons. The bootstrap notice can create a QApplication in this process,
    and forking a process that holds live Qt state is unsupported (children can
    abort or hang on the duplicated display connection). And Windows - where all
    development runs - always spawns, so pinning spawn makes Linux exercise the
    same code paths instead of quietly different ones. Must happen before the
    first Queue(): queues are built from the default context at call time.

    Pinning twice is a RuntimeError, so the guard - not force=True - is what
    makes a second call harmless.
    """
    if get_start_method(allow_none=True) != "spawn":
        set_start_method("spawn")


def start_engine(
    mode: str, log_level_name: str | None = None, debug_monitor: bool = False
) -> Engine:
    """
    Bring up everything a frontend talks to: configuration, Logger, CORE.

    Args:
        mode: "gui", "cli", "api" or "headless". It decides how a configuration
            notice is shown (a popup only in GUI mode) and whether the Logger also
            writes to stdout (only in GUI mode - the others have their own console
            output), and it names the mode in the run log's first line.
        log_level_name: overrides [logging] level in config.ini, as --log-level.
        debug_monitor: open the Debug Monitor on this run's log.

    If anything fails after the Logger is up, what was started is stopped again
    before the exception leaves.
    """
    pin_spawn_start_method()

    # Before anything else, including logging: the configuration.
    # This is the one call that either open config.ini or creates it.
    # An existing file is never modified, and every other process only reads
    # it. A broken or version-mismatched file cannot stop the run: bootstrap()
    # discards it and runs on the template defaults, prompting user about it.
    config = ConfigHandler.bootstrap()

    if config.bootstrap_outcome is BootstrapOutcome.CREATED:
        show_config_popup(
            mode,
            "pypts configuration created",
            f"No configuration was found; a new one was created with default "
            f"values at:\n{config.config_path}",
            warning=False,
        )
    elif config.bootstrap_outcome is BootstrapOutcome.DISCARDED:
        show_config_popup(
            mode,
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

    configured_level = log_level_name or config.get_parameter("logging.level")
    log_level = parse_log_level(configured_level)
    # -1 is not a level, so it survives only when the name meant nothing.
    level_was_understood = not configured_level or parse_log_level(configured_level, -1) != -1

    stdout_logging_enabled = mode == "gui"

    # Use as a separate pocess instead of standalone import (many writers)
    logger_process = Process(
        target=logger_main,
        name="Logger",
        args=(log_queue, log_file_path, stdout_logging_enabled),
    )
    logger_process.start()

    logger_control: QueueWrapper[LoggerControl] = QueueWrapper(log_queue, link=ANY_TO_LOGGER)
    init_logging(log_queue, log_level, log_file_path)

    # CORE-HMI process links
    engine = Engine(
        mode=mode,
        log_queue=log_queue,
        log_level=log_level,
        log_file_path=log_file_path,
        logger_process=logger_process,
        logger_control=logger_control,
        to_core=QueueWrapper(Queue(), link=HMI_TO_CORE),
        to_hmi=QueueWrapper(Queue(), link=CORE_TO_HMI),
    )
    try:
        # Everything the launcher did before there was a logger: since there is
        # no logging before log_path, the bootstrap actions are replayed and
        # logged now.
        config.replay_bootstrap_log()

        # The first three lines of every run log: what this is, who ran it,
        # and where the file they are reading lives. A log taken out of context
        # for a support ticket still answers all three - logging_rules.md section 6.
        log.info("PyPTS %s started in %s mode.", __version__, mode.upper())
        log.info("Started by %s on %s.", describe_operator(), platform.node() or "an unknown host")
        log.info("Run log: %s", log_file_path)

        log.debug("Logging at %s.", logging.getLevelName(log_level))
        if not level_was_understood:
            log.warning(
                "The logging level in the settings file is not one this software "
                "knows, so the usual level is being used instead."
            )
            log.debug("The unrecognised level was %r.", configured_level)
        log.debug(
            "Operating system: %s %s (%s).",
            config.get_parameter("operating_system.name"),
            config.get_parameter("operating_system.version"),
            config.get_parameter("operating_system.architecture"),
        )

        # Debug monitor is a developer-only helper application to trace and
        # simulate queue communication. To be removed after reaching stable build.
        if debug_monitor:
            engine.monitor_process = start_debug_monitor(log_file_path, log_level)

        engine.core_process = Process(
            target=core_main,
            name="Core",
            args=(engine.to_hmi, engine.to_core, log_queue, log_level),
        )
        engine.core_process.start()
        log.debug("Core process started (pid %s).", engine.core_process.pid)
    except BaseException:
        stop_engine(engine)
        raise
    return engine


def run_gui(
    engine: Engine,
    recipe_path: str | None = None,
    start: bool = False,
    sequence_name: str | None = None,
) -> None:
    """
    Start the GUI process on a running engine and wait until it has ended.

    Args:
        recipe_path: a recipe the window opens as soon as it is up, as if the
            operator had picked it. None opens an empty window.
        start: start a sequence of that recipe once CORE has loaded it.
        sequence_name: which one; None means the recipe's main sequence.
    """
    # Imported here and not at the top, for the reason main() checks the import
    # before anything is created: the launcher must load without Qt.
    from pypts.hmi.gui.gui import gui_main

    # The GUI is given the log path as well as the queue: it tails the
    # run log into its LOG OUTPUT panel, and the launcher is the only
    # one that knows which file this run writes to.
    ui_process = Process(
        target=gui_main,
        name="GUI",
        args=(
            engine.to_core,
            engine.to_hmi,
            engine.log_queue,
            engine.log_level,
            engine.log_file_path,
            recipe_path,
            start,
            sequence_name,
        ),
    )
    ui_process.start()
    log.debug("GUI process started (pid %s).", ui_process.pid)
    ui_process.join()
    log.debug("The GUI process has ended.")


def stop_engine(engine: Engine) -> None:
    """CORE first, then the Logger - so the records explaining the shutdown reach the file."""
    stop_core(engine.core_process, engine.to_core)

    # Deliberately not stopped with the rest - for debugging purposes.
    # To be removed after reaching stable build.
    monitor_process = engine.monitor_process
    if monitor_process is not None and monitor_process.poll() is None:
        log.debug(
            "Debug Monitor (pid %d) left running; close its window when you are done.",
            monitor_process.pid,
        )

    log.info("PyPTS has finished.")
    log.debug("Stopping the Logger.")
    # A queued message, so the Logger acts on it only after writing
    # everything already in flight.
    engine.logger_control.send(StopLogger())
    engine.logger_process.join(timeout=LOGGER_SHUTDOWN_TIMEOUT_S)
    if engine.logger_process.is_alive():
        engine.logger_process.terminate()


def describe_operator() -> str:
    """
    Who is running this, for the second line of the run log.

    getpass.getuser() reads the environment before it asks the system, and on a
    machine where none of the usual variables is set it raises rather than
    returning anything: OSError where there is no password database entry, and
    KeyError from the pwd lookup underneath it. A run log that cannot name its
    operator is still a perfectly good run log, so the failure is worth a word
    and nothing more.
    """
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "an unknown user"


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
            "The Debug Monitor was asked for, but this run records at %s: its Trace "
            "tab will stay empty. Start with --log-level DEBUG to fill it.",
            logging.getLevelName(log_level),
        )

    path = Path(log_file_path)
    deadline = time.monotonic() + MONITOR_LOG_WAIT_S
    while not path.is_file():
        if time.monotonic() >= deadline:
            log.warning("The Debug Monitor did not start: the run log was not created in time.")
            log.debug("Waited %.1f s for %s.", MONITOR_LOG_WAIT_S, path)
            return None
        time.sleep(MONITOR_LOG_POLL_S)

    try:
        monitor_process = subprocess.Popen(
            [sys.executable, "-m", DEBUG_MONITOR_MODULE, str(path)]
        )
    except OSError as error:
        log.warning("The Debug Monitor could not be started: %s", error)
        return None

    log.debug("Debug Monitor started (pid %d), reading %s.", monitor_process.pid, path)
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

    log.debug("Asking the Core process to shut down.")
    to_core.send(HmiStopped())
    to_core.send(ShutdownRequested())
    core_process.join(timeout=CORE_SHUTDOWN_TIMEOUT_S)

    if core_process.is_alive():
        log.warning("The engine did not shut down in time and was closed by force.")
        log.debug("Terminating the Core process after %.1f s.", CORE_SHUTDOWN_TIMEOUT_S)
        core_process.terminate()
        core_process.join(timeout=CORE_SHUTDOWN_TIMEOUT_S)
    else:
        log.debug("The Core process has ended.")


if __name__ == "__main__":
    main()
