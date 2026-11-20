# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
CORE - the mediator, and the engine process.

Every message in the framework except log records passes through here. CORE owns
the links to the Sequencer and the Report, holds the link to the HMI that the
launcher built, and is the only module that talks to more than one other.

The Sequencer and the Report are **threads of this process**, not processes of
their own. Only the HMI is still across a process boundary, so that the
operator's window survives an engine crash. What that buys: the four engine
links are plain `queue.Queue`, nothing on them is pickled, and the engine can
hand the Sequencer a live object - a recipe, a device handle - the day the
execution engine lands. What it costs is recorded in the roadmap: a fault in
either thread now takes CORE down with it, and the run log identifies both of
them as "Core", because the format names the process.

The three handlers below are the whole routing table. Each one ends in
unhandled(), so a message nobody thought about raises instead of being dropped.
"""

import logging
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import ClassVar
from uuid import UUID

from pypts.config_handler import ConfigError, ConfigHandler
from pypts.config_handler.configuration_schema import READ_ONLY_SECTIONS
from pypts.logger.log import DEFAULT_LOG_LEVEL, init_logging, log
from pypts.messages import QueueWrapper, UnhandledMessage, unhandled
from pypts.messages.common_messages import ErrorSeverity, Heartbeat, ModuleError
from pypts.messages.core_hmi_communication import (
    ConfigParameterResult,
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    LoadRecipe,
    ModuleErrorReported,
    RecipeUnloaded,
    ReportReady,
    SetConfigParameter,
    ShutdownRequested,
    StartSequence,
    StatusChanged,
    StopHmi,
    UnloadRecipe,
)
from pypts.messages.core_report_communication import (
    CoreToReport,
    GenerateReport,
    ReportExported,
    ReportGenerated,
    ReportStopped,
    ReportToCore,
    StopReport,
)
from pypts.messages.core_sequencer_communication import (
    CoreToSequencer,
    ForgetRecipe,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequencer,
)
from pypts.messages.links import (
    CORE_TO_REPORT,
    CORE_TO_SEQUENCER,
    REPORT_TO_CORE,
    SEQUENCER_TO_CORE,
)
from pypts.messages.run_events import (
    PauseSequence,
    RecipeLoaded,
    ResumeSequence,
    RunFinished,
    RunMetadata,
    RunPaused,
    RunResumed,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    StepExecuted,
    StepFinished,
    StepStarted,
    StopSequence,
    UserPathRequest,
    UserPathResponse,
    UserPromptRequest,
    UserPromptResponse,
    UserTextRequest,
    UserTextResponse,
)
from pypts.recipe.recipe import Recipe, RecipeError
from pypts.report.report import report_main
from pypts.sequencer.sequencer import sequencer_main
from pypts.utilities.common import ignore_keyboard_interrupt

# The heartbeat protocol - the timeout CORE applies and the names it knows the
# modules by - is declared with the sender's half in heartbeat_manager.py, so
# that the two cannot drift and so that a tool needing only the names does not
# have to import the engine to get them.
from pypts.utilities.heartbeat_manager import (
    CORE,
    HEARTBEAT_FATAL_S,
    HEARTBEAT_TIMEOUT_S,
    HMI,
    REPORT,
    SEQUENCER,
    HeartbeatManager,
)

#: What the operator is told each module is. The names above are the protocol's
#: own words and belong in the DEBUG trace; anything at INFO or above is read by
#: a technician, who has no reason to know what a "sequencer" is. See logging_rules.md.
FRIENDLY_MODULE_NAME = {
    HMI: "operator interface",
    SEQUENCER: "test engine",
    REPORT: "report writer",
}

#: The protocol's name for a module written as its ModuleError would spell it.
#: The watchdog reports a *silence* rather than a caught exception, so there is
#: no `self` to take a module path from - only the heartbeat's `source`.
MODULE_SOURCE = {
    HMI: "pypts.hmi.hmi_client",
    SEQUENCER: "pypts.sequencer.sequencer",
    REPORT: "pypts.report.report",
}

#: What a crash close during a run tells the operator. The crash close does not
#: wait for the run's teardown steps or for its devices to close, and the driver
#: processes end with CORE without their teardown().
BENCH_MAY_BE_ENERGISED = (
    "A test was running and was not finished: the devices on the bench may still be energised."
)

#: Like FRIENDLY_MODULE_NAME, for a ModuleError, which names its sender by dotted module. A
#: module missing here is described as "the software" rather than by its import
#: path - an unknown sender is still a failure worth showing the operator.
FRIENDLY_SOURCE_NAME = {
    "pypts.core.core": "the engine",
    "pypts.sequencer.sequencer": "the test engine",
    "pypts.report.report": "the report writer",
    "pypts.recipe.recipe": "the recipe reader",
    "pypts.recipe.recipe_parser": "the recipe reader",
    "pypts.hmi.hmi_client": "the operator interface",
    "pypts.hmi.gui.gui": "the operator interface",
    "pypts.hmi.cli.cli": "the operator interface",
    "pypts.config_handler.config_handler": "the settings file reader",
}


def describe_source(source: str) -> str:
    """
    The operator's name for the module a ModuleError came from.

    Args:
        source: the dotted module name carried by the ModuleError.

    Returns:
        A phrase that fits into "A problem occurred in ...".
    """
    return FRIENDLY_SOURCE_NAME.get(source, "the software")


@dataclass
class _ModuleState:
    """Per-module liveness state tracked by CORE's watchdog."""

    running: bool = True
    last_heartbeat: float | None = None  # None = never heard from
    heartbeat_lost: bool = False
    start_reported: bool = False


def core_main(
    to_hmi: QueueWrapper[CoreToHmi],
    from_hmi: QueueWrapper[HmiToCore],
    log_queue,
    log_level: int = DEFAULT_LOG_LEVEL,
) -> None:
    """
    Entry point for the launcher. Runs in the Core process.

    Routing log records to the Logger has to happen before anything is logged
    and before the submodule threads start, so it is the first thing done here.
    It is also the *only* place it happens in this process: the Sequencer and
    the Report inherit the root logger configured here rather than each
    configuring one of their own.

    Args:
        log_level: the level the launcher resolved for the whole run. Passed
            rather than read from the config here, because --log-level overrides
            the config for one run and a child process has no way to know that.
            Everything else CORE needs it reads from the config itself.
    """
    # Before anything else in this process. Ctrl+C reaches every process in the
    # group, and CORE dying to it takes the orderly shutdown - and the Sequencer
    # and Report threads - with it. The launcher asks through ShutdownRequested;
    # that stays the only way CORE stops.
    ignore_keyboard_interrupt()

    init_logging(log_queue, log_level)
    # CORE is the one process allowed to change config.ini while pypts runs
    # (SetConfigParameter). Opened for writing before Core() is built, because
    # Core's own first read would otherwise make this process a reader - and a
    # reader can never be promoted to writer.
    ConfigHandler.open_for_writing()
    Core(to_hmi, from_hmi).start()


class Core:
    """
    Mediator, and the thread that owns the Sequencer and the Report.

    Naming convention for the six links: `to_x` is what CORE sends to module x,
    `from_x` is what x sends to CORE. CORE builds both halves of its own links
    and hands them to the thread that runs the module, so a module cannot
    construct a link to anyone it has no business talking to.
    """

    def __init__(
        self,
        to_hmi: QueueWrapper[CoreToHmi],
        from_hmi: QueueWrapper[HmiToCore],
    ) -> None:
        self.to_hmi = to_hmi
        self.from_hmi = from_hmi

        # One queue per direction. The QueueWrapper type parameter is the union that
        # queue is allowed to carry, and `link` is the name it goes by in the
        # trace - these four never leave this process, so the log is the only
        # place they can be seen at all. A plain `queue.Queue` is all they need,
        # because the Sequencer and the Report are threads of this process; the
        # one link that does cross a process boundary, HMI<->CORE, is built by
        # the launcher out of `multiprocessing.Queue` and handed in above.
        self.to_sequencer: QueueWrapper[CoreToSequencer] = QueueWrapper(
            Queue(), link=CORE_TO_SEQUENCER
        )
        self.from_sequencer: QueueWrapper[SequencerToCore] = QueueWrapper(
            Queue(), link=SEQUENCER_TO_CORE
        )
        self.to_report: QueueWrapper[CoreToReport] = QueueWrapper(Queue(), link=CORE_TO_REPORT)
        self.from_report: QueueWrapper[ReportToCore] = QueueWrapper(Queue(), link=REPORT_TO_CORE)

        self.running = True

        #: True once a close has begun, orderly or at once.
        self.shutting_down = False

        #: True once the crash close has begun: every module told to stop in
        #: one go, nothing waited for, the submodule threads not joined.
        self.closing_at_once = False

        #: The modules already told to stop, so that each is told exactly once
        #: whichever way the close goes - an orderly close overtaken by a crash
        #: request included.
        self.stop_sent: set[str] = set()

        #: True from RunStarted to RunFinished. A crash close does not wait
        #: for the run's teardown, so with a run open it says the bench may
        #: still be energised.
        self.run_open = False

        #: The loaded recipe, and the only copy of it: CORE owns it, and hands
        #: it to the Sequencer with each RunSequence. None until one is loaded,
        #: and again after UnloadRecipe, which is what makes StartSequence
        #: refusable here.
        self.recipe: Recipe | None = None

        #: Whether the run in progress has a report: the `write_report` of its
        #: RunStarted, back to True when its RunFinished has been routed. False
        #: only for the GUI's engineering-mode retest, whose events then go to
        #: the HMI alone. Taken from the Sequencer's RunStarted rather than from
        #: the StartSequence CORE relayed, because the Sequencer may refuse it.
        self.run_has_report = True

        # Set by start_submodules(). A CORE built by a test may never start
        # them, so join_submodules() has to cope with them being absent.
        self.sequencer_thread: threading.Thread | None = None
        self.report_thread: threading.Thread | None = None

        #: Per-module liveness state. Replaces the five parallel dicts that used
        #: to track the same three keys separately, making do_periodic_tasks
        #: readable in a single pass.
        #:
        #: last_heartbeat starts as None (never heard from), not as time.time().
        #: The old seeding asserted every module had been heard from when CORE
        #: was built - at which point the HMI has not even been spawned. A cold
        #: PySide6 import over a network home directory is seconds of entirely
        #: normal startup, and the fatal countdown must not run against it.
        self.modules: dict[str, _ModuleState] = {
            HMI: _ModuleState(),
            SEQUENCER: _ModuleState(),
            REPORT: _ModuleState(),
        }

        #: When CORE was built, which is the only clock a module that has never
        #: spoken can be measured against.
        self.started_at = time.time()

        #: CORE's own heartbeat, towards the HMI and nowhere else. The Sequencer
        #: and the Report are threads of this process and cannot outlive it, so
        #: watching for a CORE that has gone would be watching for something
        #: that cannot happen - and would double the trace traffic doing it.
        self.hmi_heartbeat = HeartbeatManager(self.to_hmi, CORE)

    # --- Startup --------------------------------------------------------------

    def start(self) -> None:
        log.debug("CORE module starting.")
        # Before start_submodules(), not after: CORE is up once its links are
        # built, and the Sequencer and the Report announce themselves from the
        # threads it is about to start. Logging it afterwards put the children
        # above the parent in the operator's log.
        log.debug("CORE module started.")
        self.start_submodules()
        self.main_loop()
        self.join_submodules()
        log.debug("CORE module stopped.")

    def start_submodules(self) -> None:
        """
        Start the Sequencer and the Report, handing each the two links it needs:
        its outbox to CORE and its inbox from CORE.

        Threads, not processes. They are named, so that anything reading a
        thread dump can tell them apart even though the run log cannot.

        Daemon threads deliberately: a submodule that wedges must not be able to
        keep the process alive after CORE has decided to leave. The clean path
        does not rely on it - join_submodules() waits for both - but the clean
        path is not the one worth designing for here.
        """
        self.sequencer_thread = threading.Thread(
            target=sequencer_main,
            name="Sequencer",
            args=(self.from_sequencer, self.to_sequencer),
            daemon=True,
        )
        self.sequencer_thread.start()
        log.debug("Sequencer thread started.")

        self.report_thread = threading.Thread(
            target=report_main,
            name="Report",
            args=(self.from_report, self.to_report),
            daemon=True,
        )
        self.report_thread.start()
        log.debug("Report thread started.")

    def join_submodules(self) -> None:
        """
        Wait for both submodule threads to return, once the loop has ended.

        After an orderly close both have reported themselves stopped, so a plain
        join returns at once: all that is left is the return from their loops.
        After a crash close nothing is waited for: a Sequencer thread may be
        stuck in a step, and they are daemons, so the process exits without them.
        """
        if self.closing_at_once:
            log.debug("Closing at once: the submodule threads are not waited for.")
            return
        for name, thread in (
            (SEQUENCER, self.sequencer_thread),
            (REPORT, self.report_thread),
        ):
            if thread is None:
                continue
            log.debug("Waiting for the %s thread.", name)
            thread.join()
            log.debug("The %s thread finished.", name)

    # --- Main event loop ------------------------------------------------------

    def main_loop(self) -> None:
        log.debug("CORE entered its main event loop.")
        while self.running:
            self.poll_all_sources()
            # Guarded like poll(), and for the same reason: CORE is the module
            # errors are reported *to*, so an exception out of its own periodic
            # machinery must not kill it without a reason in the log. Unlike a
            # bad message, a broken periodic task repeats every tick, so this
            # does not carry on: the failure is reported once and the ordinary
            # shutdown runs. If it strikes again during that shutdown - the
            # shutdown checker itself is what is broken - leaving is all that
            # is left, because nothing would ever clear self.running.
            try:
                self.do_periodic_tasks()
                self.check_stop_status()
            except Exception as exc:  # noqa: BLE001 - report_own_error() does the logging
                self.report_own_error(exc, "Core.main_loop")
                if self.shutting_down:
                    self.running = False
                else:
                    self.stop_all_modules()
            time.sleep(0.01)
        log.debug("CORE left its main event loop.")

    def poll_all_sources(self) -> None:
        self.poll(self.from_hmi, self.handle_hmi_message)
        self.poll(self.from_sequencer, self.handle_sequencer_message)
        self.poll(self.from_report, self.handle_report_message)

    def poll(self, inbox, handler) -> None:
        """
        Handle what is waiting on one inbox, surviving anything it contains.

        CORE cannot use @catch_and_report_errors(): it is the module errors are
        reported *to*. A message it cannot handle is logged and dropped, because
        the alternative - letting it escape - takes the mediator down and with
        it every other module's only way of being heard.

        The cost of that guarantee is that one bad message abandons the rest of
        the batch: the exception leaves the receive() generator, and the
        remainder stays queued for the next tick. That is the right trade - they
        are not lost, only delayed - but it is why the try wraps the whole loop
        rather than each message, which would be the alternative.
        """
        try:
            for message in inbox.receive():
                handler(message)
        except UnhandledMessage as exc:
            log.error("The engine received an internal update it does not understand.")
            log.debug("Unhandled message on link '%s': %s", inbox.link, exc)
        except Exception as exc:
            log.error("The engine failed while handling an internal update: %s", exc)
            log.debug("Traceback for the failure on link '%s':", inbox.link, exc_info=True)

    # --- Routing --------------------------------------------------------------

    def handle_hmi_message(self, message: HmiToCore) -> None:
        match message:
            case ShutdownRequested(immediate=True):
                self.close_at_once()
            case ShutdownRequested():
                self.stop_all_modules()
            case HmiStopped():
                self.modules[HMI].running = False
            case LoadRecipe(recipe_path=recipe_path):
                self.load_recipe(recipe_path)
            case UnloadRecipe():
                self.unload_recipe()
            case StartSequence(
                sequence_name=sequence_name,
                excluded_step_ids=excluded_step_ids,
                write_report=write_report,
            ):
                self.start_sequence(sequence_name, excluded_step_ids, write_report)
            case StopSequence():
                # The operator's abort. Relayed unchanged; the Sequencer answers
                # with the run's own RunFinished(STOP).
                self.to_sequencer.send(message)
            case PauseSequence() | ResumeSequence():
                # The operator's hold and release. Relayed unchanged, like
                # StopSequence; the Sequencer answers with RunPaused and
                # RunResumed when the hold actually begins and ends.
                self.to_sequencer.send(message)
            case UserPromptResponse() | UserTextResponse() | UserPathResponse():
                # The operator's answer belongs to whoever asked the question.
                self.to_sequencer.send(message)
            case SetConfigParameter(key=key, value=value):
                # CORE is the single runtime writer of config.ini, which is
                # why the message stops here rather than going anywhere else.
                self.set_config_parameter(key, value)
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                # Previously the HMI link had no branch for this at all, so
                # every error a frontend reported was silently discarded.
                self.handle_module_error(message)
            case _:
                unhandled(message)

    def handle_sequencer_message(self, message: SequencerToCore) -> None:
        match message:
            case SequencerStopped():
                self.modules[SEQUENCER].running = False
                # The orderly close's next step: the Report, now that the
                # stopped run's tail is all in its queue.
                if self.shutting_down:
                    self.send_stop(REPORT)
            case RunStarted():
                self.run_open = True
                # Decides the routing of the whole run: an engineering-mode
                # retest has no report, so nothing of it goes to the Report.
                self.run_has_report = message.write_report
                if not self.run_has_report:
                    log.debug("CORE: this run has no report; its events go to the HMI only.")
                self.relay_run_event(message)
            case SequenceStarted():
                self.relay_run_event(message)
            case RunFinished():
                # The Report closes the CSV on RunFinished, then builds the
                # HTML on the GenerateReport sent right behind it - one queue,
                # so the order is guaranteed.
                if self.run_has_report:
                    log.debug("CORE relaying RunFinished and asking for the report.")
                    self.to_report.send(message)
                    self.to_report.send(GenerateReport())
                else:
                    log.debug("CORE relaying RunFinished to the HMI; no report for this run.")
                self.to_hmi.send(message)
                self.run_has_report = True
                self.run_open = False
            case RunMetadata():
                # What the run has learned about the unit on the bench. The
                # Report stamps it on every row; the HMI shows it beside the
                # recipe name so the operator can see which unit this is.
                if self.run_has_report:
                    self.to_report.send(message)
                self.to_hmi.send(message)
            case SequenceFinished() | StepStarted() | StepFinished():
                log.debug("CORE relaying %s to the HMI.", type(message).__name__)
                self.to_hmi.send(message)
            case RunPaused() | RunResumed():
                # HMI only. A hold changes when steps run, not what they
                # produce, so there is nothing for the Report to write: the
                # step rows and their timestamps already tell the story.
                log.debug("CORE relaying %s to the HMI.", type(message).__name__)
                self.to_hmi.send(message)
            case StepExecuted():
                # The rich step record. Report only - the HMI already got the
                # flat StepFinished, and this one must not cross the process
                # boundary (see its docstring). Dropped for a run without a
                # report; RunStarted already logged that once.
                if self.run_has_report:
                    self.to_report.send(message)
            case UserPromptRequest() | UserTextRequest() | UserPathRequest():
                # A step is waiting on the sequence thread for the answer to
                # this. Relayed unchanged; the answer comes back through
                # handle_hmi_message. All three are live: UserInteraction asks
                # the first, UserWrite the second, UserLoading the third.
                self.to_hmi.send(message)
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                self.handle_module_error(message)
            case _:
                unhandled(message)

    def relay_run_event(self, message: RunStarted | SequenceStarted) -> None:
        """
        RunStarted / SequenceStarted: to the HMI, and to the Report when the run has one.

        Progress is the frontend's business, and these two are the Report's as
        well: RunStarted opens the CSV in the run folder, SequenceStarted names
        the rows that follow. The same object is relayed rather than repacked,
        so nothing is lost on the way.
        """
        if self.run_has_report:
            log.debug("CORE relaying %s to the Report and the HMI.", type(message).__name__)
            self.to_report.send(message)
        else:
            log.debug("CORE relaying %s to the HMI.", type(message).__name__)
        self.to_hmi.send(message)

    def handle_report_message(self, message: ReportToCore) -> None:
        match message:
            case ReportStopped():
                self.modules[REPORT].running = False
                # The orderly close's last step: the HMI, which has by now
                # shown everything the Sequencer and the Report said.
                if self.shutting_down:
                    self.send_stop(HMI)
            case ReportGenerated(report_path=path):
                log.debug("CORE relaying the generated report at %s.", path)
                self.to_hmi.send(StatusChanged(f"Report generated: {path}"))
                # The structured sibling of the status line: the paths a
                # frontend can wire an "open report folder" control to.
                self.to_hmi.send(
                    ReportReady(report_path=path, report_dir=str(Path(path).parent))
                )
            # NOT SENT YET - export_report() is still a stub and nothing asks
            # for it either.
            case ReportExported(report_path=path):
                self.to_hmi.send(StatusChanged(f"Report exported: {path}"))
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                self.handle_module_error(message)
            case _:
                unhandled(message)

    # --- Orchestration --------------------------------------------------------

    def load_recipe(self, recipe_path: str) -> None:
        """
        Load and validate a recipe; validation gates execution.

        On success CORE keeps the Recipe and the HMI gets RecipeLoaded. The
        Sequencer is told nothing: loading is not starting, and the recipe
        reaches it with the RunSequence that runs it (roadmap section 1.40).
        On failure nothing is kept and the operator sees the error through the
        ModuleError path.

        A RecipeError is the recipe's fault and the expected failure. Anything
        else escaping the parser is a bug in it, and is caught here too: left
        alone it would reach the event loop's generic "internal update"
        catch-all, which tells the operator nothing about the recipe.
        """
        log.debug("Loading a recipe from '%s'.", recipe_path)
        try:
            recipe = Recipe.from_file(recipe_path)
        except RecipeError as error:
            self.report_own_error(error, operation="Core.load_recipe")
            return
        except Exception as error:  # noqa: BLE001 - a parser bug must not pass as a loop fault
            self.report_own_error(error, operation="Core.load_recipe")
            return
        self.recipe = recipe
        # The parser knows the format and has already logged its verdict;
        # CORE owns the channel to the operator, so the sentences are shown
        # from here. None of them stops a run: a version mismatch or a missing
        # picture loads anyway. Each is sent as ERROR, not WARNING, so it
        # reaches the operator - handle_module_error() only logs a WARNING and
        # never shows it on the HMI.
        for notice in recipe.load_notices:
            self.handle_module_error(
                ModuleError(
                    source="pypts.recipe.recipe_parser",
                    severity=ErrorSeverity.ERROR,
                    message=notice,
                    operation="Recipe.from_file",
                )
            )
        self.to_hmi.send(
            RecipeLoaded(
                recipe_name=recipe.name,
                recipe_version=recipe.version,
                main_sequence=recipe.main_sequence,
                sequences=recipe.to_summary(),
            )
        )
        # The file name rather than the whole path: the operator picked the file
        # and knows where it is, and logging_rules.md keeps the paths at INFO down to
        # the three they actually need - the run log, the run folder and the
        # report. The full path is on the DEBUG line at the top of this method.
        log.info(
            "Recipe '%s' loaded: \"%s\" v%s, %d sequences.",
            Path(recipe_path).name,
            recipe.name,
            recipe.version,
            len(recipe.sequences),
        )
        if recipe.sequences:
            names = ", ".join("'" + name + "'" for name in recipe.sequences)
            log.info("Sequences available: %s.", names)

    def unload_recipe(self) -> None:
        """
        Forget the loaded recipe, and have the Sequencer forget the last run's.

        After this a StartSequence is refused as it is before the first load.
        The HMI is answered either way - with nothing loaded there is nothing
        to forget, but the frontend still returns to its no-recipe state.
        """
        if self.recipe is None:
            log.debug("Unload asked with no recipe loaded; nothing to forget.")
        else:
            log.info('Recipe "%s" unloaded.', self.recipe.name)
            self.recipe = None
        self.to_sequencer.send(ForgetRecipe())
        self.to_hmi.send(RecipeUnloaded())

    def start_sequence(
        self,
        sequence_name: str,
        excluded_step_ids: tuple[UUID, ...] = (),
        write_report: bool = True,
    ) -> None:
        """
        Ask the Sequencer to run a sequence, handing over the recipe with it.

        CORE holds the loaded recipe, so CORE is the one that can refuse: with
        nothing loaded the command stops here and the operator is told why. The
        Sequencer is never asked to run a recipe it was not given.

        `excluded_step_ids` and `write_report` (the GUI's engineering mode) are
        copied onto the RunSequence unread.
        """
        if self.recipe is None:
            self.handle_module_error(
                ModuleError(
                    source="pypts.core.core",
                    severity=ErrorSeverity.ERROR,
                    message=(
                        f"Cannot start '{sequence_name}': no recipe is loaded. "
                        f"Open a recipe first."
                    ),
                    operation="Core.start_sequence",
                )
            )
            return
        log.debug(
            "CORE asking the Sequencer to run sequence '%s' (%d steps left out, report: %s).",
            sequence_name,
            len(excluded_step_ids),
            write_report,
        )
        self.to_sequencer.send(
            RunSequence(self.recipe, sequence_name, excluded_step_ids, write_report)
        )

    def set_config_parameter(self, key: str, value: str) -> None:
        """
        Write one value to config.ini, and tell the frontend whether it was.

        CORE holds the configuration for writing - core_main() opens it so - and
        the Config Handler does the real work: it parses the value against the
        schema before anything reaches the file, and refuses a file that was
        discarded at startup. CORE adds one rule of its own, READ_ONLY_SECTIONS,
        so a frontend that forgets to hide `meta` still cannot break the file.

        Every refusal is answered, not only logged: the operator who asked is
        looking at a dialog waiting for the answer.

        Written now, in force from the next start. Every process read its
        configuration once at startup, CORE included, and nothing tells a
        running one that a value changed - so nothing here pretends to.
        """
        section = key.rpartition(".")[0]
        if section in READ_ONLY_SECTIONS:
            self.refuse_config_parameter(
                key, value, f"'{key}' is managed by pypts and cannot be changed."
            )
            return

        try:
            ConfigHandler().set_parameter(key, value)
        except ConfigError as error:
            self.refuse_config_parameter(key, value, str(error))
            return

        # The operator's line ("Setting ... changed to ...") is the Config
        # Handler's, written as the value reached the file.
        log.debug("The setting '%s' applies from the next start.", key)
        self.to_hmi.send(ConfigParameterResult(key=key, value=value, accepted=True))

    def refuse_config_parameter(self, key: str, value: str, reason: str) -> None:
        """Log a refused SetConfigParameter and answer it, naming why."""
        log.warning("The setting '%s' was not changed: %s", key, reason)
        log.debug("The refused change was %s = %r.", key, value)
        self.to_hmi.send(
            ConfigParameterResult(key=key, value=value, accepted=False, reason=reason)
        )

    #: What CORE logs a reported failure at. The sender rates its own failure -
    #: it is the only one who can - and CORE takes it at its word. That is the
    #: whole of the decision: what to *do* about an error beyond recording it
    #: and telling the operator is Phase 1's to settle (roadmap §1.11).
    LOG_LEVEL_FOR_SEVERITY: ClassVar[dict[ErrorSeverity, int]] = {
        ErrorSeverity.WARNING: logging.WARNING,
        ErrorSeverity.ERROR: logging.ERROR,
        ErrorSeverity.CRITICAL: logging.CRITICAL,
    }

    def report_own_error(self, error: Exception, operation: str) -> None:
        """
        Report a failure of CORE's own, through the same path as everyone else's.

        CORE cannot use report_error(): that reports *to* CORE through an
        instance's `core` outbox, and CORE has no outbox to itself. So it
        builds the same ModuleError by hand and feeds its own handler - the
        error is logged and shown to the operator exactly like a reported one.
        Called from inside an `except` block, like report_error().
        """
        self.handle_module_error(
            ModuleError(
                source="pypts.core.core",
                severity=ErrorSeverity.ERROR,
                message=str(error),
                exception=repr(error),
                traceback=traceback.format_exc(),
                operation=operation,
                error_type=type(error).__name__,
            )
        )

    def handle_module_error(self, error: ModuleError) -> None:
        """
        Record a module failure and, unless it is only a warning, show it to the
        operator. CORE deciding what reaches the frontend is what keeps the
        runtime log readable during a long run.

        Two or three records, per logging_rules.md section 7: one the operator
        can read, naming the part of the software that failed and what it said,
        one at DEBUG naming the method, the exception type and the severity, and
        a separate DEBUG record with the traceback, only when there is one.
        The traceback never appears above DEBUG - in the operator's panel it
        hides the line that matters.
        """
        where = error.operation or error.source

        log.log(
            self.LOG_LEVEL_FOR_SEVERITY[error.severity],
            "A problem occurred in %s: %s",
            describe_source(error.source),
            error.message,
        )
        log.debug(
            "Reported by '%s' in '%s' (%s), severity %s.",
            error.source,
            error.operation or "an unnamed operation",
            error.error_type or "no exception",
            error.severity.name,
        )
        if error.traceback:
            log.debug("Traceback for the failure in '%s':\n%s", where, error.traceback)

        if error.severity is not ErrorSeverity.WARNING:
            self.to_hmi.send(ModuleErrorReported(error))

    def note_heartbeat(self, beat: Heartbeat) -> None:
        state = self.modules.get(beat.source)
        if state is None:
            log.debug("Heartbeat from an unknown module: '%s'.", beat.source)
            return

        # A module that was reported late and is now answering again is worth
        # one line, so the log says the outage ended instead of just going quiet.
        if state.heartbeat_lost:
            log.info("The %s is responding again.", FRIENDLY_MODULE_NAME[beat.source])
            log.debug("Module is responding again: %s", beat.source)
            state.heartbeat_lost = False

        state.last_heartbeat = beat.timestamp

    # --- Background tasks -----------------------------------------------------

    def do_periodic_tasks(self) -> None:
        """
        Beat once towards the HMI, and watch the three beats coming back.

        Only modules still expected to be running are checked, so a module that
        has already reported itself stopped does not produce a timeout warning
        for the rest of the run.

        **Two thresholds, doing two different jobs.** Silence past
        HEARTBEAT_TIMEOUT_S is *reported*: one WARNING, and the run carries on,
        because five seconds of quiet is as likely to be a stall as a death - a
        large recipe parsed inline, a machine that swapped - and a warning that
        is wrong costs nothing. Silence past HEARTBEAT_FATAL_S is *acted on*:
        the module is not coming back, and a run whose engine or whose operator
        interface has gone is not a run any more. That one ends the session, so
        it waits three times as long before it believes itself.

        One warning per outage, not one per tick. The loop calling this turns
        every 10 ms and a timed-out module stays timed out, so logging on every
        pass would bury the ModuleError explaining the crash under thousands of
        copies of the same sentence. note_heartbeat() clears the flag when the
        module answers again, so a second outage is reported afresh.
        """
        # CORE's half of the protocol. Before everything below, so that a CORE
        # which is looping is always saying so - including all through a
        # shutdown, when the HMI is being stopped and must not conclude from the
        # silence that the engine died under it.
        self.hmi_heartbeat.tick()

        # The watch stays on through an orderly close: it has no deadline, so a
        # module that dies during it would hold CORE for ever, and this is what
        # turns that into a crash close. A module that has answered its stop is
        # skipped below (state.running). Once the crash close has begun there
        # is nothing left to watch, and without this the fatal branch would
        # re-report the same dead module on every tick until CORE leaves.
        if self.closing_at_once:
            return

        now = time.time()
        for name, state in self.modules.items():
            if not state.running:
                continue

            if state.last_heartbeat is None:
                self.note_a_module_has_not_started(name, state)
                # Never heard from is not the same as gone: it may still be
                # starting, and a module that has never spoken cannot be said to
                # have stopped responding. Nothing below applies until it does.
                continue

            silent_for = now - state.last_heartbeat

            if silent_for > HEARTBEAT_TIMEOUT_S and not state.heartbeat_lost:
                # The one liveness fact the operator is told, and it is told
                # without the mechanism - logging_rules.md section 7.1. Everything
                # measurable about it is on the DEBUG line under it.
                log.warning("The %s has stopped responding.", FRIENDLY_MODULE_NAME[name])
                # The mechanism, for the developer: which module, on its own
                # line, with the measurements below it.
                log.debug("Heartbeat timeout for module: %s", name)
                log.debug(
                    "It had been silent for %.1f s; the timeout is %.1f s.",
                    silent_for,
                    HEARTBEAT_TIMEOUT_S,
                )
                state.heartbeat_lost = True

            # Always acts: there is deliberately no setting to turn this off. A
            # run that carries on past a dead module produces a record nobody
            # can trust.
            if silent_for > HEARTBEAT_FATAL_S:
                self.end_run_for_silent_module(name, silent_for)
                # Every module has just been asked to stop; there is nothing
                # to be learned by measuring the other two against a clock
                # they were never going to answer.
                return

    def note_a_module_has_not_started(self, name: str, state: _ModuleState) -> None:
        """
        Say once that a module has yet to say anything at all.

        A separate sentence from "has stopped responding", because it is a
        separate fact and the other one would be a lie: a module that has never
        spoken was never responding. On a bench where a frontend takes a while to
        come up this is the normal state of affairs for the first few seconds, so
        it waits out the same reporting threshold the timeout uses and is said
        once, not once per tick. It is DEBUG: a slow GUI start (PySide6 takes
        seconds to import) is routine and tells the technician nothing.

        It does not end the run. A frontend that never starts at all is caught
        by the launcher: its `ui_process.join()` returns at once if the frontend
        dies on import.
        """
        if state.start_reported:
            return
        if time.time() - self.started_at < HEARTBEAT_TIMEOUT_S:
            return

        state.start_reported = True
        log.debug(
            "The %s has not started yet: no heartbeat from %s in the %.1f s since CORE was built.",
            FRIENDLY_MODULE_NAME[name],
            name,
            HEARTBEAT_TIMEOUT_S,
        )

    def end_run_for_silent_module(self, name: str, silent_for: float) -> None:
        """
        Bring the application down because a module is not coming back.

        The operator is told *before* anything stops. A window that simply
        vanishes leaves a technician with a half-finished test and no reason for
        it, so this goes through handle_module_error() - the same path a
        reported failure takes - which logs it at the severity's level and sends
        it on as ModuleErrorReported. Sending it first matters: the StopHmi from
        close_at_once() is what closes their window. Nothing here writes an operator-facing line
        of its own; that would say the same thing twice.

        Then the crash close (close_at_once()): the silent module will not
        answer - it is why we are here - so nothing is waited for. With a run
        open, the same CRITICAL says the bench may still be energised: the
        crash close does not wait for the run's teardown.
        """
        # The mechanism only. The operator's sentence is written by
        # handle_module_error() below, from the ModuleError - saying it here as
        # well would tell them the same thing twice, which logging_rules.md
        # section 5 is explicit about.
        # Shaped like the timeout line above: the prefix and the module name,
        # with the measurements on their own line below.
        log.debug("Heartbeat fatal for module: %s", name)
        log.debug(
            "It had been silent for %.1f s; the limit is %.1f s.",
            silent_for,
            HEARTBEAT_FATAL_S,
        )

        message = f"It stopped responding for {silent_for:.0f} seconds, so pypts is closing."
        if self.run_open:
            message += " " + BENCH_MAY_BE_ENERGISED
        self.handle_module_error(
            ModuleError(
                source=MODULE_SOURCE[name],
                severity=ErrorSeverity.CRITICAL,
                message=message,
                operation="heartbeat",
            )
        )
        # The CRITICAL above already said whatever there was to say.
        self.close_at_once(warn=False)

    # --- Shutdown -------------------------------------------------------------
    #
    # Two ways to close, and only two. The orderly close waits for each module
    # in turn, with no deadline: a running test finishes its step and its
    # teardown steps first. The crash close tells every module to stop in one
    # go and waits for nothing. A module that dies during an orderly close is
    # caught by the watchdog, which turns it into a crash close.

    def stop_all_modules(self) -> None:
        """
        The orderly close: StopSequencer now, StopReport on SequencerStopped,
        StopHmi on ReportStopped. CORE leaves once all three have stopped.

        Idempotent: a frontend may ask more than once.
        """
        if self.shutting_down:
            return
        self.shutting_down = True
        log.info("Shutting down.")
        log.debug("Orderly close: the Sequencer first, then the Report, then the HMI.")
        self.send_stop(SEQUENCER)

    def close_at_once(self, warn: bool = True) -> None:
        """
        The crash close: every module still running is told to stop in one go,
        and CORE leaves without waiting for any answer.

        Taken on ShutdownRequested(immediate=True) - the CLI's Ctrl+C, the
        launcher once the frontend has gone - and by the watchdog. A crash close
        that overtakes an orderly one stops whatever is left. With nothing left
        running (the launcher's request after an orderly close) it only lets
        CORE leave, and says nothing to the operator.

        `warn` is False for the watchdog, whose own CRITICAL has already told
        the operator what died and whether the bench may still be energised.
        """
        if self.closing_at_once:
            return
        still_running = [name for name, state in self.modules.items() if state.running]
        self.shutting_down = True
        self.closing_at_once = True
        if not still_running:
            log.debug("Asked to close at once; every module has already stopped.")
            self.running = False
            return

        if warn:
            if self.run_open:
                log.critical("pypts is closing at once. %s", BENCH_MAY_BE_ENERGISED)
            else:
                log.info("pypts is closing at once.")
        log.debug("Crash close: stopping %s without waiting.", ", ".join(still_running))
        for name in still_running:
            self.send_stop(name)
        self.running = False

    def send_stop(self, name: str) -> None:
        """Tell one module to stop, exactly once whatever the close does next."""
        if name in self.stop_sent:
            return
        self.stop_sent.add(name)
        log.debug("Sending the stop to the %s.", name)
        if name == SEQUENCER:
            self.to_sequencer.send(StopSequencer())
        elif name == REPORT:
            self.to_report.send(StopReport())
        else:
            self.to_hmi.send(StopHmi())

    def check_stop_status(self) -> None:
        """
        CORE leaves its loop once every module has reported itself stopped.

        There is no deadline. A module that dies without answering stops
        beating, and the watchdog in do_periodic_tasks() turns the wait into a
        crash close.
        """
        if not any(state.running for state in self.modules.values()):
            log.debug("Every module has reported itself stopped.")
            self.running = False
