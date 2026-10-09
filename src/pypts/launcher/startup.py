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
"""

import argparse
import importlib
import logging
import subprocess
import sys
from dataclasses import dataclass
from multiprocessing import Process, Queue, get_start_method, set_start_method
from typing import Any, NoReturn

from pypts.config_handler import BootstrapOutcome, ConfigHandler
from pypts.core.core import core_main
from pypts.hmi.cli.cli import cli_main
from pypts.logger.log import (
    init_logging,
    log,
    log_run_log_header,
    logger_main,
    parse_log_level,
)
from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    ShutdownRequested,
)
from pypts.messages.links import ANY_TO_LOGGER, CORE_TO_HMI, HMI_TO_CORE
from pypts.messages.to_logger_communication import LoggerControl, StopLogger
from pypts.utilities.common import RESTART_EXIT_CODE
from pypts.utilities.local_storage import get_log_file_path

#: How long CORE gets to shut itself down cleanly before it is killed.
CORE_SHUTDOWN_TIMEOUT_S = 5.0

#: How long the Logger gets to drain whatever is still queued.
LOGGER_SHUTDOWN_TIMEOUT_S = 5.0

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
        choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help=(
            "Minimum level written to the run log. TRACE adds the message trace: "
            "every message on every link, as it is sent and as it is received. "
            "DEBUG is the developer detail without it. "
            "Overrides [logging] level in config.ini."
        ),
    )
    args = parser.parse_args()

    if args.mode == "headless":
        if args.recipe is None:
            parser.error("--mode headless needs --recipe")
    elif args.recipe is not None or args.sequence is not None:
        parser.error("--recipe and --sequence are for --mode headless only")

    # Headless mode is pypts.api.Pts with a console, and Pts starts the engine
    # itself. Imported here, not at the top: pypts.api imports this module.
    if args.mode == "headless":
        from pypts.api.headless import headless_main

        sys.exit(headless_main(args.recipe, args.sequence, args.log_level))

    # The GUI is imported only when one is going to be started. PySide6 is the
    # one heavy dependency in the tree and `pypts.hmi.gui.gui` is the only door
    # to it - nothing in CORE, the Logger, the messages or the engine imports Qt
    # at all. As a module-level import this line made `--mode cli` fail outright
    # on a headless bench with no Qt system libraries, for a frontend that run
    # was never going to open. A CLI run on such a bench has to be able to start.
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

    engine = start_engine(args.mode, args.log_level)
    restart = False
    try:
        if args.mode == "gui":
            restart = run_gui(engine)
            if restart:
                log.info("pypts is restarting.")
        else:
            # The CLI runs here in the launcher's own process, so there is no
            # fourth process in CLI mode.
            log.debug("Running the CLI in the launcher process.")
            cli_main(engine.to_core, engine.to_hmi)
    finally:
        # In case of shutdown of the launcher (instead of clean exit from the UI)
        stop_engine(engine)

    # Only after everything above has stopped: the new pypts must not meet this
    # one's CORE, Logger or open log file.
    if restart:
        sys.exit(restart_pypts())


def restart_pypts() -> int:
    """
    Start pypts again with the command line this one was started with, and wait.

    Called by main() when the GUI ended asking for it - after Restore default
    settings deleted config.ini. A fresh process rather than a second pass through
    main(): every singleton (the configuration, logging) starts empty, exactly
    as when an operator starts pypts by hand, so config.ini is recreated from
    the template by the bootstrap that already does it, and a new run log comes
    with it.

    Waiting rather than exiting straight away: the console a .bat file opened
    closes when this process ends, and would take the new pypts with it. The
    cost is one idle launcher per restart, which ends when the new pypts does
    and hands on its exit code.

    Returns:
        The restarted pypts' exit code.
    """
    command = [sys.executable, *sys.orig_argv[1:]]
    # print, not log: the Logger was stopped with the rest.
    print("Restarting pypts...", flush=True)
    return subprocess.call(command)


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


def start_engine(mode: str, log_level_name: str | None = None) -> Engine:
    """
    Bring up everything a frontend talks to: configuration, Logger, CORE.

    Args:
        mode: "gui", "cli", "api" or "headless". It decides how a configuration
            notice is shown (a popup only in GUI mode) and whether the Logger also
            writes to stdout (only in GUI mode - the others have their own console
            output), and it names the mode in the run log's first line.
        log_level_name: overrides [logging] level in config.ini, as --log-level.

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
    log_file_path = get_log_file_path(config.get_parameter("paths.reports_dir"))

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
        log_run_log_header(mode, log_file_path)

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
) -> bool:
    """
    Start the GUI process on a running engine and wait until it has ended.

    Args:
        recipe_path: a recipe the window opens as soon as it is up, as if the
            operator had picked it. None opens an empty window.
        start: start a sequence of that recipe once CORE has loaded it.
        sequence_name: which one; None means the recipe's main sequence.

    Returns:
        True if the GUI ended asking for pypts to be started again
        (RESTART_EXIT_CODE), after Restore default settings - main() does that;
        pypts.api.open_gui() ignores it.
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
    log.debug("The GUI process has ended (exit code %s).", ui_process.exitcode)
    return ui_process.exitcode == RESTART_EXIT_CODE


def stop_engine(engine: Engine) -> None:
    """CORE first, then the Logger - so the records explaining the shutdown reach the file."""
    stop_core(engine.core_process, engine.to_core)

    log.info("PyPTS has finished.")
    log.debug("Stopping the Logger.")
    # A queued message, so the Logger acts on it only after writing
    # everything already in flight.
    engine.logger_control.send(StopLogger())
    engine.logger_process.join(timeout=LOGGER_SHUTDOWN_TIMEOUT_S)
    if engine.logger_process.is_alive():
        engine.logger_process.terminate()


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
