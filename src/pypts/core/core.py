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
from pathlib import Path
from queue import Queue
from typing import ClassVar

from pypts.logger.log import DEFAULT_LOG_LEVEL, init_logging, log
from pypts.messages import QueueWrapper, UnhandledMessage, unhandled
from pypts.messages.common_messages import ErrorSeverity, Heartbeat, ModuleError
from pypts.messages.core_hmi_communication import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    LoadRecipe,
    ModuleErrorReported,
    ReportReady,
    SetConfigParameter,
    ShutdownRequested,
    StartSequence,
    StatusChanged,
    StopHmi,
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
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequencer,
    UseRecipe,
)
from pypts.messages.links import (
    CORE_TO_REPORT,
    CORE_TO_SEQUENCER,
    REPORT_TO_CORE,
    SEQUENCER_TO_CORE,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunMetadata,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    StepExecuted,
    StepFinished,
    StepStarted,
    StopSequence,
    UserPromptRequest,
    UserPromptResponse,
    UserTextRequest,
    UserTextResponse,
)
from pypts.recipe.recipe import Recipe, RecipeError
from pypts.report.report import report_main
from pypts.sequencer.sequencer import sequencer_main

# The heartbeat protocol - the timeout CORE applies and the names it knows the
# modules by - is declared with the sender's half in heartbeat_manager.py, so
# that the two cannot drift and so that a tool needing only the names does not
# have to import the engine to get them.
from pypts.utilities.heartbeat_manager import (
    HEARTBEAT_TIMEOUT_S,
    HMI,
    REPORT,
    SEQUENCER,
)

#: What the operator is told each module is. The names above are the protocol's
#: own words and belong in the DEBUG trace; anything at INFO or above is read by
#: a technician, who has no reason to know what a "sequencer" is. See logging_rules.md.
FRIENDLY_MODULE_NAME = {
    HMI: "operator interface",
    SEQUENCER: "test engine",
    REPORT: "report writer",
}

#: The same, for a ModuleError, which names its sender by dotted module. A
#: module missing here is described as "the software" rather than by its import
#: path - an unknown sender is still a failure worth showing the operator.
FRIENDLY_SOURCE_NAME = {
    "pypts.core.core": "the engine",
    "pypts.sequencer.sequencer": "the test engine",
    "pypts.report.report": "the report writer",
    "pypts.recipe.recipe": "the recipe reader",
    "pypts.recipe.recipe_parser": "the recipe reader",
    "pypts.recipe.validator": "the recipe checker",
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
    init_logging(log_queue, log_level)
    Core(to_hmi, from_hmi, log_queue, log_level=log_level).start()


class Core:
    """
    Mediator, and the thread that owns the Sequencer and the Report.

    Naming convention for the six links: `to_x` is what CORE sends to module x,
    `from_x` is what x sends to CORE. CORE builds both halves of its own links
    and hands them to the thread that runs the module, so a module cannot
    construct a link to anyone it has no business talking to.
    """

    #: How long a submodule thread gets to leave its event loop once it has
    #: reported itself stopped. It has already said it is done, so this only
    #: covers the return from the loop; it is not a shutdown budget.
    THREAD_JOIN_TIMEOUT_S = 5.0

    #: How long every module together gets to answer a stop request. This one
    #: *is* the shutdown budget: it starts when stop_all_modules() asks, and it
    #: covers a module noticing the request, finishing what it is doing and
    #: reporting itself stopped.
    #:
    #: Without it CORE waits forever for a module that will never answer, and
    #: the only thing that ends the run is the launcher's own join timeout
    #: terminating the process - which loses the log line saying who was to
    #: blame. Five seconds because it matches the launcher's budget and the
    #: heartbeat timeout; a module quiet for that long is already presumed dead.
    SHUTDOWN_TIMEOUT_S = 5.0

    def __init__(
        self,
        to_hmi: QueueWrapper[CoreToHmi],
        from_hmi: QueueWrapper[HmiToCore],
        log_queue,
        log_level: int = DEFAULT_LOG_LEVEL,
    ) -> None:
        """
        Args:
            log_queue: kept so CORE can hand it on if a submodule ever needs to
                configure logging of its own. The threads do not: they share
                this process's root logger, which core_main() has already
                pointed at the Logger.
            log_level: kept for the same reason.
        """
        self.to_hmi = to_hmi
        self.from_hmi = from_hmi

        self.log_queue = log_queue
        self.log_level = log_level

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
        self.shutting_down = False

        #: True between "shutdown asked" and "the Report has been told to stop".
        #: The Report is stopped LAST so it can drain the aborted run's tail
        #: (StepExecuted / RunFinished / GenerateReport) before it closes.
        self.stop_report_pending = False

        #: The recipe LoadRecipe loaded and validated, or None until one has.
        #: The Sequencer holds the same object - one process, nothing copied.
        self.recipe: Recipe | None = None

        #: When CORE stops waiting for the modules it asked to stop. None until
        #: it has asked, because there is nothing to time out before that.
        self.shutdown_deadline: float | None = None

        # Set by start_submodules(). A CORE built by a test may never start
        # them, so join_submodules() has to cope with them being absent.
        self.sequencer_thread: threading.Thread | None = None
        self.report_thread: threading.Thread | None = None

        # Which modules CORE is still waiting for before it may exit.
        self.module_running = {HMI: True, SEQUENCER: True, REPORT: True}
        self.last_heartbeat = {name: time.time() for name in self.module_running}

        # Which modules have already been reported late. The main loop turns
        # every 10 ms, so without this the timeout below would log the same
        # warning about a hundred times a second for the rest of the run.
        self.heartbeat_lost = {name: False for name in self.module_running}

    # --- Startup --------------------------------------------------------------

    def start(self) -> None:
        log.debug("CORE module starting.")
        # Before start_submodules(), not after: CORE is up once its links are
        # built, and the Sequencer and the Report announce themselves from the
        # threads it is about to start. Logging it afterwards put the children
        # above the parent in the operator's log.
        log.info("CORE module started.")
        self.start_submodules()
        self.main_loop()
        self.join_submodules()
        log.info("CORE module stopped.")

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

        By the time CORE leaves its loop both have reported themselves stopped,
        so this normally returns at once. A thread still alive here is stuck
        somewhere after its loop and is worth a line in the log: the process
        will exit anyway, because they are daemons.
        """
        for name, thread in (
            (SEQUENCER, self.sequencer_thread),
            (REPORT, self.report_thread),
        ):
            if thread is None:
                continue
            log.debug("Waiting up to %.1f s for the %s thread.", self.THREAD_JOIN_TIMEOUT_S, name)
            thread.join(timeout=self.THREAD_JOIN_TIMEOUT_S)
            if thread.is_alive():
                log.warning(
                    "The %s did not shut down in time and was left running.",
                    FRIENDLY_MODULE_NAME[name],
                )
                log.debug(
                    "Thread '%s' was still alive after %.1f s.", name, self.THREAD_JOIN_TIMEOUT_S
                )
            else:
                log.debug("The %s thread finished.", name)

    # --- Main event loop ------------------------------------------------------

    def main_loop(self) -> None:
        log.debug("CORE entered its main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            self.check_stop_status()
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
            case ShutdownRequested():
                self.stop_all_modules()
            case HmiStopped():
                self.module_running[HMI] = False
            case LoadRecipe(recipe_path=recipe_path):
                self.load_recipe(recipe_path)
            case StartSequence(sequence_name=sequence_name):
                self.start_sequence(sequence_name)
            case StopSequence():
                # The operator's abort. Relayed unchanged; the Sequencer answers
                # with the run's own RunFinished(STOP).
                self.to_sequencer.send(message)
            case UserPromptResponse() | UserTextResponse():
                # The operator's answer belongs to whoever asked the question.
                self.to_sequencer.send(message)
            case SetConfigParameter(key=key, value=value):
                # NOT SENT YET - no frontend constructs this, and the branch is
                # deliberately a refusal rather than an implementation.
                # CORE is the only process allowed to write config.ini, which is
                # why the message stops here. Carrying it out is not implemented:
                # a change would have to reach the processes already running,
                # each holding what it read at startup, and that is unsolved.
                log.warning(
                    "The setting '%s' was not changed: settings cannot be changed "
                    "while the application is running.",
                    key,
                )
                log.debug("The refused change was %s = %r.", key, value)
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
                self.module_running[SEQUENCER] = False
                self.release_stop_report()
            case RunStarted() | SequenceStarted():
                # Progress is the frontend's business, and these two are the
                # Report's as well: RunStarted opens the run folder and the
                # CSV, SequenceStarted names the rows that follow. The same
                # object is relayed rather than repacked, so nothing is lost
                # on the way.
                log.debug(
                    "CORE relaying %s to the Report and the HMI.", type(message).__name__
                )
                self.to_report.send(message)
                self.to_hmi.send(message)
            case RunFinished():
                # The Report closes the CSV on RunFinished, then builds the
                # HTML on the GenerateReport sent right behind it - one queue,
                # so the order is guaranteed.
                log.debug("CORE relaying RunFinished and asking for the report.")
                self.to_report.send(message)
                self.to_report.send(GenerateReport())
                self.to_hmi.send(message)
            case RunMetadata():
                # What the run has learned about the unit on the bench. The
                # Report stamps it on every row; the HMI shows it beside the
                # recipe name so the operator can see which unit this is.
                self.to_report.send(message)
                self.to_hmi.send(message)
            case SequenceFinished() | StepStarted() | StepFinished():
                log.debug("CORE relaying %s to the HMI.", type(message).__name__)
                self.to_hmi.send(message)
            case StepExecuted():
                # The rich step record. Report only - the HMI already got the
                # flat StepFinished, and this one must not cross the process
                # boundary (see its docstring).
                self.to_report.send(message)
            case UserPromptRequest() | UserTextRequest():
                # A step is waiting on the sequence thread for the answer to
                # this. Relayed unchanged; the answer comes back through
                # handle_hmi_message. Both are live: UserInteraction asks the
                # first, UserWrite the second.
                self.to_hmi.send(message)
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                self.handle_module_error(message)
            case _:
                unhandled(message)

    def handle_report_message(self, message: ReportToCore) -> None:
        match message:
            case ReportStopped():
                self.module_running[REPORT] = False
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

        On success the HMI gets RecipeLoaded and the Sequencer gets the live
        Recipe object with UseRecipe. On failure the Sequencer gets nothing at
        all - an invalid recipe never reaches it - and the operator sees the
        error through the ModuleError path.
        """
        log.debug("Loading a recipe from '%s'.", recipe_path)
        try:
            recipe = Recipe.from_file(recipe_path)
        except RecipeError as error:
            self.report_own_error(error, operation="Core.load_recipe")
            return
        self.recipe = recipe
        # The parser knows the format and has already logged its verdict;
        # CORE owns the channel to the operator, so the sentence is shown
        # from here. A version mismatch never stops a run - it is a warning
        # that the recipe may expect a framework this is not.
        if recipe.version_notice:
            self.handle_module_error(
                ModuleError(
                    source="pypts.recipe.recipe_parser",
                    severity=ErrorSeverity.ERROR,
                    message=recipe.version_notice,
                    operation="Recipe.from_file",
                )
            )
        self.to_sequencer.send(UseRecipe(recipe))
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

    def start_sequence(self, sequence_name: str) -> None:
        """
        Ask the Sequencer to run a sequence.

        The name now reaches the Sequencer, which the old interface could not do:
        its run_sequence() took no arguments, so the operator's choice stopped at
        CORE. Execution itself is still a stub inside the Sequencer.
        """
        log.debug("CORE asking the Sequencer to run sequence '%s'.", sequence_name)
        self.to_sequencer.send(RunSequence(sequence_name))

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

        Two records, per logging_rules.md section 7: one the operator can read, naming
        the part of the software that failed and what it said, and one at DEBUG
        naming the method and the exception type, with the traceback under it.
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
        if beat.source not in self.last_heartbeat:
            log.debug("Heartbeat from an unknown module: '%s'.", beat.source)
            return

        # A module that was reported late and is now answering again is worth
        # one line, so the log says the outage ended instead of just going quiet.
        if self.heartbeat_lost[beat.source]:
            log.info("The %s is responding again.", FRIENDLY_MODULE_NAME[beat.source])
            # The Monitor's other machine-read line - see do_periodic_tasks().
            log.debug("Module is responding again: %s", beat.source)
            self.heartbeat_lost[beat.source] = False

        self.last_heartbeat[beat.source] = beat.timestamp

    # --- Background tasks -----------------------------------------------------

    def do_periodic_tasks(self) -> None:
        """
        Watch the heartbeats.

        Only modules still expected to be running are checked, so a module that
        has already reported itself stopped does not produce a timeout warning
        for the rest of the run. What CORE should *do* about a timeout - restart
        the module, abort the run, tell the operator - is still an open decision
        recorded in the roadmap; for now it warns.

        One warning per outage, not one per tick. The loop calling this turns
        every 10 ms and a timed-out module stays timed out, so logging on every
        pass would bury the ModuleError explaining the crash under thousands of
        copies of the same sentence. note_heartbeat() clears the flag when the
        module answers again, so a second outage is reported afresh.
        """
        now = time.time()
        for name, last_seen in self.last_heartbeat.items():
            if not self.module_running[name]:
                continue
            if now - last_seen > HEARTBEAT_TIMEOUT_S and not self.heartbeat_lost[name]:
                # The one liveness fact the operator is told, and it is told
                # without the mechanism - logging_rules.md section 7.1. Everything
                # measurable about it is on the DEBUG line under it.
                log.warning("The %s has stopped responding.", FRIENDLY_MODULE_NAME[name])
                # Machine-read: the Debug Monitor's liveness tab matches this
                # line on its prefix and takes the rest as the module name, so
                # it carries nothing else and ends without a full stop. See
                # helper_applications/debug_monitor/liveness.py.
                log.debug("Heartbeat timeout for module: %s", name)
                log.debug(
                    "It had been silent for %.1f s; the timeout is %.1f s.",
                    now - last_seen,
                    HEARTBEAT_TIMEOUT_S,
                )
                self.heartbeat_lost[name] = True

    # --- Shutdown -------------------------------------------------------------

    def stop_all_modules(self) -> None:
        """
        Ask every module to stop. Each answers with its own *Stopped event.

        Idempotent, because shutdown is legitimately requested twice: the
        frontend asks when the operator leaves, and the launcher asks again once
        it has joined the UI process - it cannot assume the frontend got the
        chance. Without the guard every module is told to stop twice.
        """
        if self.shutting_down:
            return
        self.shutting_down = True

        # The clock starts here rather than at the first unanswered check, so
        # the budget covers the whole shutdown and not just the tail of it.
        self.shutdown_deadline = time.time() + self.SHUTDOWN_TIMEOUT_S

        log.info("Shutting down.")
        log.debug(
            "Stopping every module; the shutdown budget is %.1f s.", self.SHUTDOWN_TIMEOUT_S
        )
        self.to_sequencer.send(StopSequencer())
        self.to_hmi.send(StopHmi())
        # StopReport is held back: the Sequencer may still be finishing an
        # aborted sequence whose events must reach the Report first. It is
        # released by SequencerStopped, or by the shutdown deadline.
        self.stop_report_pending = True

    def release_stop_report(self) -> None:
        """Send the held StopReport, exactly once."""
        if not self.stop_report_pending:
            return
        self.stop_report_pending = False
        log.debug("Releasing the held StopReport.")
        self.to_report.send(StopReport())

    def check_stop_status(self) -> None:
        """
        CORE exits once every module has reported itself stopped, or once it has
        waited SHUTDOWN_TIMEOUT_S for the ones that have not.

        The clean path is the first branch and is what almost always happens.
        The second exists because a module that dies without reporting used to
        leave CORE waiting forever, and the only thing that ended the run was the
        launcher terminating the process - which killed the log along with it, so
        the one fact worth keeping, *which* module never answered, was the one
        fact lost. Naming them is most of the point of having a timeout at all.

        There is no killing to do. The Sequencer and the Report are daemon
        threads, so abandoning them is exactly what letting CORE leave means:
        they cannot hold the process open, and join_submodules() logs any that
        are still running when it goes. The HMI is a process the launcher owns,
        so CORE could not kill it even if threads were killable - which is the
        other reason this reports rather than acts.
        """
        if not any(self.module_running.values()):
            log.debug("Every module has reported itself stopped.")
            self.running = False
            return

        if self.shutdown_deadline is None or time.time() < self.shutdown_deadline:
            return

        # The Sequencer never answered; stop holding the Report for it.
        self.release_stop_report()

        # Reached once: self.running is cleared below, so the loop that calls
        # this does not come back round to log the same sentence again.
        late = sorted(name for name, running in self.module_running.items() if running)
        log.error(
            "Parts of the software did not stop in time and were left behind: %s.",
            ", ".join(FRIENDLY_MODULE_NAME[name] for name in late),
        )
        log.debug("Abandoned after %.1f s: %s.", self.SHUTDOWN_TIMEOUT_S, ", ".join(late))
        self.running = False
