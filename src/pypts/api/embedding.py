# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The embedding API: pypts driven by code instead of by an operator.

`Pts` is a third frontend beside the GUI and the CLI. It starts the same Logger
and CORE the launcher starts (startup.start_engine), talks to CORE through the
same HmiClient protocol, and turns that conversation into blocking calls: load
a recipe, run a sequence, get the result back.

`open_gui()` is the other door: the normal window, started from code, with a
recipe already opened - and started, if asked.

What comes back is the small set of dataclasses below, not the internal
messages, so the message layer stays free to change underneath callers.
"""

import importlib
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from pypts.hmi.hmi_client import HmiClient
from pypts.launcher import startup
from pypts.logger.log import log
from pypts.messages import QueueWrapper
from pypts.messages.common_messages import Heartbeat, ResultType
from pypts.messages.core_hmi_communication import (
    CoreToHmi,
    HmiToCore,
    ModuleErrorReported,
    ReportReady,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunStarted,
    StepFinished,
    UserPromptRequest,
    UserTextRequest,
)
from pypts.utilities.error_handling import catch_and_report_errors

#: Seconds between polls of the CORE inbox, on the background thread.
POLL_INTERVAL_S = 0.05

#: How often a waiting call looks at the messages that have arrived.
WAIT_STEP_S = 0.1

#: How long load_recipe() waits for CORE to answer.
LOAD_TIMEOUT_S = 30.0

#: How long run() waits for the report once the run itself has finished. The
#: Report writes the HTML after RunFinished, so ReportReady always comes later.
REPORT_TIMEOUT_S = 15.0

#: The operation CORE reports a refused recipe under.
LOAD_REFUSAL = "Core.load_recipe"

#: The operations that refuse a start. An error under one of these names that
#: arrives before RunStarted means the run never began.
START_REFUSALS = (
    "Core.start_sequence",
    "Sequencer.run_sequence",
    "Sequencer.execute_sequence",
)

#: A question the running recipe puts to the operator, answered by code: the
#: button to press for a UserPromptRequest, the text to type for a
#: UserTextRequest, or None to decline.
Answer = Callable[[UserPromptRequest | UserTextRequest], str | None]


class PtsError(Exception):
    """pypts refused what was asked of it, or could not finish it."""


@dataclass(frozen=True)
class LoadedRecipe:
    """What CORE loaded."""

    name: str
    version: str
    main_sequence: str
    sequences: tuple[str, ...]
    #: Notices that did not stop the load - a recipe written for another
    #: pypts version, for one.
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepVerdict:
    """One step of a run, as it finished."""

    name: str
    result: ResultType
    #: Why it did not pass, or why it did not run; empty otherwise.
    info: str = ""


@dataclass(frozen=True)
class RunResult:
    """One finished run."""

    sequence: str
    result: ResultType
    steps: tuple[StepVerdict, ...]
    #: The run's report folder, or None if no report arrived.
    report_dir: str | None = None
    #: Errors reported while the run was going; the run carried on past them.
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """PASS, or DONE - a run with nothing in it to judge."""
        return self.result in (ResultType.PASS, ResultType.DONE)


class ApiClient(HmiClient):
    """
    The protocol half of a frontend, with no presentation at all.

    A background thread drains CORE's inbox and sends heartbeats, as the CLI's
    does, and hands every message on through `received`. The waiting - and the
    answering of operator questions - happens on the caller's thread, in
    load() and run(): an answer function that takes a minute must not stop the
    heartbeats, or CORE would decide this frontend is gone.
    """

    def __init__(
        self, to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]
    ) -> None:
        super().__init__(to_core, from_core)
        #: Every message from CORE except heartbeats, in arrival order.
        self.received: queue.Queue[Any] = queue.Queue()
        #: The recipe CORE holds, as far as this client knows. A refused load
        #: leaves it as it was, as CORE leaves its own recipe.
        self.loaded: LoadedRecipe | None = None
        self._polling_thread: threading.Thread | None = None

    # --- Background thread ------------------------------------------------------

    def start_polling(self) -> None:
        self._polling_thread = threading.Thread(
            target=self._poll_loop, name="api-poll", daemon=True
        )
        self._polling_thread.start()

    def join_polling(self, timeout_s: float = 1.0) -> None:
        if self._polling_thread is not None:
            self._polling_thread.join(timeout=timeout_s)

    def _poll_loop(self) -> None:
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(POLL_INTERVAL_S)

    @catch_and_report_errors()
    def poll_core(self) -> None:
        for message in self.inbox.receive():
            self.handle_core_message(message)
            if not isinstance(message, Heartbeat):
                self.received.put(message)

    # --- Questions: answered by whoever is waiting in run() -----------------------

    def ask_user(self, request: UserPromptRequest) -> None:
        log.debug("A question reached the API; run() answers it: %s", request.message)

    def ask_user_text(self, request: UserTextRequest) -> None:
        log.debug("A text request reached the API; run() answers it: %s", request.message)

    # --- Blocking calls -----------------------------------------------------------

    def load(
        self, recipe_path: str | PathLike[str], timeout_s: float = LOAD_TIMEOUT_S
    ) -> LoadedRecipe:
        """Ask CORE to load a recipe and wait for its answer."""
        path = str(Path(recipe_path).resolve())
        self._forget_old_messages()
        self.load_recipe(path)

        warnings: list[str] = []
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            message = self._next_message("loading the recipe")
            if message is None:
                continue
            if isinstance(message, RecipeLoaded):
                self.loaded = LoadedRecipe(
                    name=message.recipe_name,
                    version=message.recipe_version,
                    main_sequence=message.main_sequence,
                    sequences=tuple(sequence.sequence_name for sequence in message.sequences),
                    warnings=tuple(warnings),
                )
                return self.loaded
            if isinstance(message, ModuleErrorReported):
                if message.error.operation == LOAD_REFUSAL:
                    raise PtsError(f"The recipe was not loaded: {message.error.message}")
                warnings.append(message.error.message)
        raise PtsError(
            f"The engine did not answer within {timeout_s:.0f} s of being asked to load {path}."
        )

    def run(
        self,
        sequence_name: str | None = None,
        answer: Answer | None = None,
        on_step: Callable[[StepVerdict], None] | None = None,
    ) -> RunResult:
        """Start a sequence of the loaded recipe and wait until the run has finished."""
        if self.loaded is None:
            raise PtsError("No recipe is loaded. Call load_recipe() first.")
        if sequence_name is None:
            sequence_name = self.loaded.main_sequence

        self._forget_old_messages()
        self.start_sequence(sequence_name)

        started = False
        steps: list[StepVerdict] = []
        errors: list[str] = []
        while True:
            message = self._next_message("the run was going")
            if message is None:
                continue
            if isinstance(message, RunStarted):
                started = True
            elif isinstance(message, StepFinished):
                outcome = message.outcome
                step = StepVerdict(outcome.step_name, outcome.result, outcome.error_info)
                steps.append(step)
                if on_step is not None:
                    on_step(step)
            elif isinstance(message, UserPromptRequest | UserTextRequest):
                self._answer(answer, message)
            elif isinstance(message, ModuleErrorReported):
                if not started and message.error.operation in START_REFUSALS:
                    raise PtsError(f"The run did not start: {message.error.message}")
                errors.append(message.error.message)
            elif isinstance(message, RunFinished):
                report_dir = self._wait_for_report(errors)
                return RunResult(
                    sequence=sequence_name,
                    result=message.result,
                    steps=tuple(steps),
                    report_dir=report_dir,
                    errors=tuple(errors),
                )

    # --- Helpers ------------------------------------------------------------------

    def _answer(self, answer: Answer | None, request: UserPromptRequest | UserTextRequest) -> None:
        """
        Answer one question, always.

        The step on the other side is blocked until it hears something, so the
        answer is sent even when the answer function raises - as a decline - and
        the exception then goes on to the caller.
        """
        value = None
        try:
            if answer is None:
                log.warning(
                    "No answer function was given, so the question '%s' was declined.",
                    request.message,
                )
            else:
                given = answer(request)
                if given is not None:
                    value = str(given)
        finally:
            if isinstance(request, UserPromptRequest):
                self.answer_user_prompt(request, value)
            else:
                self.answer_user_text(request, value)

    def _wait_for_report(self, errors: list[str]) -> str | None:
        deadline = time.monotonic() + REPORT_TIMEOUT_S
        while time.monotonic() < deadline and self.running:
            try:
                message = self.received.get(timeout=WAIT_STEP_S)
            except queue.Empty:
                continue
            if isinstance(message, ReportReady):
                return message.report_dir
            if isinstance(message, ModuleErrorReported):
                errors.append(message.error.message)
        log.debug("No report arrived within %.1f s of the run finishing.", REPORT_TIMEOUT_S)
        return None

    def _next_message(self, what: str) -> Any | None:
        """
        The next message, or None after a short wait.

        Raises once the queue is empty and CORE has told this client to stop:
        whatever was being waited for is not coming. Checked only when the queue
        is empty, so messages that arrived before StopHmi are still seen.
        """
        try:
            return self.received.get(timeout=WAIT_STEP_S)
        except queue.Empty:
            if not self.running:
                raise PtsError(f"The engine stopped while {what}.") from None
            return None

    def _forget_old_messages(self) -> None:
        """Drop what is left over from before the command about to be sent."""
        while True:
            try:
                self.received.get_nowait()
            except queue.Empty:
                return


class Pts:
    """
    pypts with no window: the engine, driven by calls.

        if __name__ == "__main__":
            with Pts() as pts:
                pts.load_recipe("bench.yml")
                result = pts.run(answer=my_answers)

    Creating one starts the Logger and CORE processes, as `python -m pypts`
    does, and close() shuts them down; use it as a context manager or call
    close() yourself. Everything is written to the usual run log and report
    folders from config.ini.

    Create it under `if __name__ == "__main__":`. pypts starts its processes
    with spawn, which imports the calling script again in every child.

    While it is open, this process's root logger sends its records to the pypts
    run log. close() puts back the handlers and the level it found.
    """

    def __init__(self, log_level: str | None = None, debug_monitor: bool = False) -> None:
        """
        Args:
            log_level: "DEBUG", "INFO", ... - overrides [logging] level in config.ini.
            debug_monitor: open the Debug Monitor on this run's log.
        """
        self._saved_logging = _save_root_logging()
        try:
            self._engine = startup.start_engine("api", log_level, debug_monitor)
        except BaseException:
            _restore_root_logging(self._saved_logging)
            raise
        self._client = ApiClient(self._engine.to_core, self._engine.to_hmi)
        self._client.start_polling()
        self._closed = False
        log.debug("The embedding API is connected to CORE.")

    def __enter__(self) -> "Pts":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def loaded_recipe(self) -> LoadedRecipe | None:
        """The recipe CORE holds, or None before the first successful load."""
        return self._client.loaded

    def load_recipe(self, recipe_path: str | PathLike[str]) -> LoadedRecipe:
        """
        Load a recipe, replacing any loaded before.

        Raises PtsError with CORE's reason when the recipe is refused.
        """
        return self._client.load(recipe_path)

    def run(
        self,
        sequence: str | None = None,
        answer: Answer | None = None,
        on_step: Callable[[StepVerdict], None] | None = None,
    ) -> RunResult:
        """
        Run a sequence of the loaded recipe and wait until it has finished.

        Args:
            sequence: which one; None runs the recipe's main sequence.
            answer: called for every question the recipe asks the operator,
                with the UserPromptRequest or UserTextRequest; returns the
                button or the text, or None to decline. Without it every
                question is declined, and a declined question is an ERROR.
            on_step: called with each step as it finishes, for live progress.

        Raises PtsError if the run could not start, or if the engine stopped
        before the run finished. A run that starts always comes back as a
        RunResult, whatever its verdict.
        """
        return self._client.run(sequence, answer, on_step)

    def stop(self) -> None:
        """
        Abort the running sequence - safe to call from another thread.

        It lands at the next step boundary; the run() waiting on it then
        returns with result STOP.
        """
        self._client.stop_sequence()

    def close(self) -> None:
        """Shut pypts down. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._client.running:
                self._client.request_shutdown()
                self._client.wait_until_stopped()
            self._client.join_polling()
        finally:
            startup.stop_engine(self._engine)
            _restore_root_logging(self._saved_logging)


def open_gui(
    recipe: str | PathLike[str] | None = None,
    *,
    start: bool = False,
    sequence: str | None = None,
    log_level: str | None = None,
    debug_monitor: bool = False,
) -> None:
    """
    Open the pypts window, as `python -m pypts` does, and wait until it is closed.

        open_gui()                                        # an empty window
        open_gui("bench.yml")                             # with the recipe loaded
        open_gui("bench.yml", start=True)                 # ...and its main sequence started
        open_gui("bench.yml", start=True, sequence="Cal") # ...or the sequence named

    The operator takes it from there: the window is the ordinary one. A recipe
    CORE refuses shows its error in the window and is not started.

    Call it under `if __name__ == "__main__":`, for the reason Pts says.

    Raises:
        ValueError: `sequence` without `start`, or `start` without a recipe.
        PtsError: the recipe file does not exist, or PySide6 cannot be loaded.
            Both are checked before any process is started.
    """
    if sequence is not None and not start:
        raise ValueError("'sequence' names the sequence to start, so it needs start=True.")
    if start and recipe is None:
        raise ValueError("start=True needs a recipe to start.")

    recipe_path = None
    if recipe is not None:
        path = Path(recipe).resolve()
        if not path.is_file():
            raise PtsError(f"Recipe file not found: {path}")
        recipe_path = str(path)

    try:
        importlib.import_module("pypts.hmi.gui.gui")
    except ImportError as error:
        raise PtsError(f"The GUI needs PySide6, which cannot be loaded: {error}") from error

    saved_logging = _save_root_logging()
    try:
        engine = startup.start_engine("gui", log_level, debug_monitor)
        try:
            startup.run_gui(engine, recipe_path, start, sequence)
        finally:
            startup.stop_engine(engine)
    finally:
        _restore_root_logging(saved_logging)


def _save_root_logging() -> tuple[int, list[logging.Handler]]:
    root = logging.getLogger()
    return root.level, list(root.handlers)


def _restore_root_logging(saved: tuple[int, list[logging.Handler]]) -> None:
    """Undo what init_logging() did to this process, which is not pypts' own."""
    level, handlers = saved
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
