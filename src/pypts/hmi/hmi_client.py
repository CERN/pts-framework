# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The half of a frontend that is protocol rather than presentation.

The GUI and the CLI implement one and the same contract with CORE, so the
handler for that contract lives here once and the drawing lives in the
subclasses. When each frontend had its own copy they drifted: the GUI answered
StopHmi with a proper handshake while the CLI just set a flag and never replied,
so in CLI mode CORE could never establish that every module had stopped and only
ever exited because the launcher killed it.

Subclasses override the show_* hooks they can actually render. Every hook has a
default that logs, so adding a message to the CoreToHmi union cannot break a
frontend that has not caught up with it yet.
"""

import time

from pypts.logger.log import log
from pypts.messages import QueueWrapper, unhandled
from pypts.messages.common_messages import ModuleError, ResultType, StepOutcome
from pypts.messages.core_hmi_communication import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    LoadRecipe,
    ModuleErrorReported,
    ReportReady,
    ShutdownRequested,
    StartSequence,
    StatusChanged,
    StopHmi,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunMetadata,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    StepFinished,
    StepStarted,
    StopSequence,
    UserPromptRequest,
    UserPromptResponse,
    UserTextRequest,
    UserTextResponse,
)
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HMI, HeartbeatManager

#: The name CORE knows a frontend by, and the `source` on its heartbeats. Both
#: frontends use it because only one of them ever runs. Imported rather than
#: spelled again: CORE keys its liveness tables on the same string.
MODULE_NAME = HMI

#: How long stop_and_wait() gives CORE to answer a shutdown request before the
#: frontend stops on its own. Without a bound, a wedged CORE would hang the exit.
SHUTDOWN_GRACE_S = 5.0


class HmiClient:
    """
    Attributes:
        core: outbox to CORE. Named `core` because @catch_and_report_errors()
              reports failures through it.
        inbox: events and commands from CORE.
        running: False once CORE has told this frontend to stop.
    """

    def __init__(
        self, to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]
    ) -> None:
        self.core = to_core
        self.inbox = from_core
        self.running = True
        self.heartbeat_manager = HeartbeatManager(self.core, MODULE_NAME)

    # --- Event loop -----------------------------------------------------------

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)

    @catch_and_report_errors()
    def do_periodic_tasks(self) -> None:
        self.heartbeat_manager.tick()

    @catch_and_report_errors()
    def handle_core_message(self, message: CoreToHmi) -> None:
        """The routing table both frontends share. Ends in unhandled() on purpose."""
        match message:
            case StopHmi():
                self.stop()
            case StatusChanged(text=text):
                self.show_status(text)
            case ModuleErrorReported(error=error):
                self.show_error(error)
            case ReportReady():
                self.show_report_ready(message)
            # The progress events below are live: CORE and the engine send all
            # of them on every run, and so are both questions - UserInteraction
            # asks the first, UserWrite the second.
            case RecipeLoaded():
                self.show_recipe_loaded(message)
            case RunStarted(recipe_name=name, recipe_description=description):
                self.show_run_started(name, description)
            case RunFinished(result=result, outcomes=outcomes):
                self.show_run_finished(result, outcomes)
            case RunMetadata(values=values):
                self.show_run_metadata(values)
            case SequenceStarted(sequence_name=name):
                self.show_sequence_started(name)
            case SequenceFinished(sequence_name=name, result=result):
                self.show_sequence_finished(name, result)
            case StepStarted():
                self.show_step_started(message)
            case StepFinished(outcome=outcome):
                self.show_step_finished(outcome)
            case UserPromptRequest():
                self.ask_user(message)
            case UserTextRequest():
                self.ask_user_text(message)
            case _:
                unhandled(message)

    # --- Commands this frontend can send --------------------------------------

    def load_recipe(self, recipe_path: str) -> None:
        self.core.send(LoadRecipe(recipe_path))

    def start_sequence(self, sequence_name: str) -> None:
        self.core.send(StartSequence(sequence_name))

    def stop_sequence(self) -> None:
        """
        Ask CORE to abort the running sequence; the application stays up.

        The abort lands at the next step boundary, and the confirmation a
        frontend gets is the run's own RunFinished with result STOP - there is
        no separate acknowledgement to wait for.
        """
        self.core.send(StopSequence())

    def request_shutdown(self) -> None:
        """
        Ask CORE to shut the whole application down.

        This is the only way a frontend leaves. CORE stops every module, sends
        StopHmi back, and this frontend answers HmiStopped from stop() - so CORE
        learns that all three modules are down and can exit on its own.
        """
        log.debug("The frontend is asking CORE to shut the application down.")
        self.core.send(ShutdownRequested())

    def answer_user_prompt(self, request: UserPromptRequest, choice: str | None) -> None:
        """Answer a UserPromptRequest. `choice` is None if the operator cancelled."""
        self.core.send(UserPromptResponse(request_id=request.request_id, choice=choice))

    def answer_user_text(self, request: UserTextRequest, text: str | None) -> None:
        """Answer a UserTextRequest. `text` is None if the operator declined."""
        self.core.send(UserTextResponse(request_id=request.request_id, text=text))

    # --- Shutdown -------------------------------------------------------------

    @catch_and_report_errors()
    def stop(self) -> None:
        """
        Stop this frontend and tell CORE it has stopped.

        Called on StopHmi, never directly by a subclass - a frontend that wants
        to leave calls request_shutdown() and lets CORE bring everything down in
        order.
        """
        log.debug("The frontend is stopping.")
        self.running = False
        self.on_stop()
        self.core.send(HmiStopped())

    def wait_until_stopped(self, grace_s: float = SHUTDOWN_GRACE_S) -> None:
        """
        Block until CORE's StopHmi has been handled, or the grace period expires.

        Only useful to a frontend whose main thread would otherwise return
        straight after request_shutdown(). If CORE never answers, this stops the
        frontend anyway rather than waiting forever.
        """
        deadline = time.time() + grace_s
        while self.running and time.time() < deadline:
            time.sleep(0.05)
        if self.running:
            log.warning("The engine did not confirm the shutdown; closing anyway.")
            log.debug("No StopHmi arrived within %.1f s of the request.", grace_s)
            self.stop()

    # --- Presentation hooks ---------------------------------------------------
    #
    # Defaults log and nothing else. Override the ones a frontend can draw.
    #
    # Every one of these is the *receiving* end of an event CORE, the Sequencer
    # or the Report has already written to the run log in the operator's words.
    # Logging them again at INFO would say the same thing three times in three
    # registers, so they trace at DEBUG instead - logger.md section 5. The
    # operator loses nothing: the GUI panel is fed from the log file, not from
    # this process's own records.

    def show_status(self, text: str) -> None:
        log.debug("Status line: %s", text)

    def show_error(self, error: ModuleError) -> None:
        log.debug("Error received from %s: %s", error.source, error.message)

    def show_recipe_loaded(self, event: RecipeLoaded) -> None:
        """Passed whole: the summary is what fills a table or a sequence chooser."""
        log.debug(
            "RecipeLoaded received: '%s' v%s with %d sequences.",
            event.recipe_name,
            event.recipe_version,
            len(event.sequences),
        )

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        log.debug("RunStarted received for recipe '%s'.", recipe_name)

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        log.debug("RunFinished received: %s over %d steps.", result.name, len(outcomes))

    def show_sequence_started(self, sequence_name: str) -> None:
        log.debug("SequenceStarted received for '%s'.", sequence_name)

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        log.debug("SequenceFinished received for '%s': %s.", sequence_name, result.name)

    def show_step_started(self, event: StepStarted) -> None:
        log.debug("StepStarted received for '%s'.", event.step_name)

    def show_step_finished(self, outcome: StepOutcome) -> None:
        log.debug("StepFinished received for '%s': %s.", outcome.step_name, outcome.result.name)

    def show_report_ready(self, event: ReportReady) -> None:
        """The run's report is on disk. Passed whole: a frontend that offers
        "open the folder" needs `report_dir`, one that names the file needs
        `report_path`."""
        log.debug("ReportReady received: %s", event.report_path)

    def show_run_metadata(self, values: tuple[tuple[str, str], ...]) -> None:
        """What the run has learned about the unit on the bench - the globals
        the recipe named in `report_metadata`, as they are set."""
        log.debug(
            "RunMetadata received: %s.",
            ", ".join(f"{name} = {value}" for name, value in values),
        )

    def ask_user(self, request: UserPromptRequest) -> None:
        """
        Put the question to the operator and answer with answer_user_prompt().

        The default declines, because a frontend that cannot ask must still
        answer: the step on the other side is blocked until it hears something.
        """
        log.warning(
            "This interface cannot ask the operator anything, so the question "
            "'%s' was declined.",
            request.message,
        )
        self.answer_user_prompt(request, None)

    def ask_user_text(self, request: UserTextRequest) -> None:
        """As ask_user(), and declines for the same reason."""
        log.warning(
            "This interface cannot ask the operator to type anything, so the "
            "request '%s' was declined.",
            request.message,
        )
        self.answer_user_text(request, None)

    def on_stop(self) -> None:
        """Frontend teardown - close the window, print a farewell. Optional."""
