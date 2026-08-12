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
from pypts.messages import Channel, unhandled
from pypts.messages.common import ModuleError, ResultType, StepOutcome
from pypts.messages.hmi_link import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    LoadRecipe,
    ModuleErrorReported,
    ShutdownRequested,
    StartSequence,
    StatusChanged,
    StopHmi,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    SerialNumberRequest,
    SerialNumberResponse,
    StepFinished,
    StepStarted,
    UserPromptRequest,
    UserPromptResponse,
)
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager

#: The name CORE knows a frontend by, and the `source` on its heartbeats. Both
#: frontends use it because only one of them ever runs.
MODULE_NAME = "hmi"

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

    def __init__(self, to_core: Channel[HmiToCore], from_core: Channel[CoreToHmi]) -> None:
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
            case RecipeLoaded(recipe_name=name, recipe_version=version):
                self.show_recipe_loaded(name, version)
            case RunStarted(recipe_name=name, recipe_description=description):
                self.show_run_started(name, description)
            case RunFinished(result=result, outcomes=outcomes):
                self.show_run_finished(result, outcomes)
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
            case SerialNumberRequest():
                self.ask_serial_number(message)
            case _:
                unhandled(message)

    # --- Commands this frontend can send --------------------------------------

    def load_recipe(self, recipe_path: str) -> None:
        self.core.send(LoadRecipe(recipe_path))

    def start_sequence(self, sequence_name: str) -> None:
        self.core.send(StartSequence(sequence_name))

    def request_shutdown(self) -> None:
        """
        Ask CORE to shut the whole application down.

        This is the only way a frontend leaves. CORE stops every module, sends
        StopHmi back, and this frontend answers HmiStopped from stop() - so CORE
        learns that all three modules are down and can exit on its own.
        """
        log.info("Requesting application shutdown.")
        self.core.send(ShutdownRequested())

    def answer_user_prompt(self, request: UserPromptRequest, choice: str | None) -> None:
        """Answer a UserPromptRequest. `choice` is None if the operator cancelled."""
        self.core.send(UserPromptResponse(request_id=request.request_id, choice=choice))

    def answer_serial_number(self, request: SerialNumberRequest, serial_number: str | None) -> None:
        """Answer a SerialNumberRequest. `serial_number` is None if declined."""
        self.core.send(
            SerialNumberResponse(request_id=request.request_id, serial_number=serial_number)
        )

    # --- Shutdown -------------------------------------------------------------

    @catch_and_report_errors()
    def stop(self) -> None:
        """
        Stop this frontend and tell CORE it has stopped.

        Called on StopHmi, never directly by a subclass - a frontend that wants
        to leave calls request_shutdown() and lets CORE bring everything down in
        order.
        """
        log.info("Stopping module")
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
            log.warning("CORE did not acknowledge the shutdown request; stopping anyway.")
            self.stop()

    # --- Presentation hooks ---------------------------------------------------
    #
    # Defaults log and nothing else. Override the ones a frontend can draw.

    def show_status(self, text: str) -> None:
        log.info(f"status: {text}")

    def show_error(self, error: ModuleError) -> None:
        log.error(f"{error.source}: {error.message}")

    def show_recipe_loaded(self, recipe_name: str, recipe_version: str) -> None:
        log.info(f"recipe loaded: {recipe_name} {recipe_version}")

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        log.info(f"run started: {recipe_name}")

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        log.info(f"run finished: {result} ({len(outcomes)} steps)")

    def show_sequence_started(self, sequence_name: str) -> None:
        log.info(f"sequence started: {sequence_name}")

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        log.info(f"sequence finished: {sequence_name} -> {result}")

    def show_step_started(self, event: StepStarted) -> None:
        log.info(f"step started: {event.step_name}")

    def show_step_finished(self, outcome: StepOutcome) -> None:
        log.info(f"step finished: {outcome.step_name} -> {outcome.result}")

    def ask_user(self, request: UserPromptRequest) -> None:
        """
        Put the question to the operator and answer with answer_user_prompt().

        The default declines, because a frontend that cannot ask must still
        answer: the step on the other side is blocked until it hears something.
        """
        log.warning(f"Cannot prompt the operator: {request.message}")
        self.answer_user_prompt(request, None)

    def ask_serial_number(self, request: SerialNumberRequest) -> None:
        """As ask_user(), and declines for the same reason."""
        log.warning("Cannot ask for a serial number")
        self.answer_serial_number(request, None)

    def on_stop(self) -> None:
        """Frontend teardown - close the window, print a farewell. Optional."""
