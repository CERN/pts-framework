# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the embedding API (src/pypts/api/).

No processes: an ApiClient is wired to plain queues, and a FakeCore thread
plays CORE on the far side - it answers what the client sends from a script,
the way the real CORE would. The real processes are in
tests/functional_tests/test_api.py, which is opt-in.
"""

import queue
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from pypts.api import embedding
from pypts.api.embedding import ApiClient, PtsError, RunResult, StepVerdict, open_gui
from pypts.launcher import startup
from pypts.messages import QueueWrapper
from pypts.messages.common_messages import (
    ErrorSeverity,
    Heartbeat,
    ModuleError,
    ResultType,
    StepOutcome,
)
from pypts.messages.core_hmi_communication import (
    LoadRecipe,
    ModuleErrorReported,
    ReportReady,
    StartSequence,
    StopHmi,
)
from pypts.messages.run_events import (
    RecipeLoaded,
    RunFinished,
    RunStarted,
    SequenceSummary,
    StepFinished,
    StepSummary,
    UserPathRequest,
    UserPathResponse,
    UserPromptRequest,
    UserPromptResponse,
    UserTextRequest,
    UserTextResponse,
)


class FakeCore:
    """CORE's side of the two links, answering from a script: message type -> replies."""

    def __init__(self, inbox: queue.Queue, outbox: queue.Queue) -> None:
        self.inbox = inbox
        self.outbox = outbox
        self.replies = {}
        self.received = []
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def on(self, message_type, reply) -> None:
        """`reply` takes the message and returns the list of messages to send back."""
        self.replies[message_type] = reply

    def sent_of(self, message_type):
        return [message for message in self.received if isinstance(message, message_type)]

    def _loop(self) -> None:
        while self.running:
            try:
                message = self.inbox.get(timeout=0.02)
            except queue.Empty:
                continue
            if isinstance(message, Heartbeat):
                continue
            self.received.append(message)
            reply = self.replies.get(type(message))
            if reply is not None:
                for answer in reply(message):
                    self.outbox.put(answer)


@pytest.fixture
def engine():
    to_core: queue.Queue = queue.Queue()
    from_core: queue.Queue = queue.Queue()
    client = ApiClient(QueueWrapper(to_core), QueueWrapper(from_core))
    core = FakeCore(to_core, from_core)
    client.start_polling()
    yield client, core
    client.running = False
    core.running = False
    client.join_polling()
    core.thread.join(timeout=1.0)


def a_recipe_loaded():
    return RecipeLoaded(
        recipe_name="Wait demo",
        recipe_version="0.2",
        main_sequence="Main",
        sequences=(
            SequenceSummary(
                sequence_name="Main",
                steps=(StepSummary(step_id=uuid4(), step_name="First wait", description=""),),
            ),
            SequenceSummary(sequence_name="Extra", steps=()),
        ),
    )


def error_reported(message, operation):
    return ModuleErrorReported(
        ModuleError(
            source="pypts.core.core",
            severity=ErrorSeverity.ERROR,
            message=message,
            operation=operation,
        )
    )


def an_outcome(name, result, info=""):
    return StepOutcome(step_id=uuid4(), step_name=name, result=result, error_info=info)


def started():
    return RunStarted(recipe_name="Wait demo", recipe_description="")


def finished(result=ResultType.PASS):
    return [
        RunFinished(result=result),
        ReportReady(report_path="C:/reports/run/report.html", report_dir="C:/reports/run"),
    ]


def with_a_recipe_loaded(client, core):
    core.on(LoadRecipe, lambda message: [a_recipe_loaded()])
    client.load("bench.yml")


def wait_until(condition, timeout_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def test_load_returns_what_core_loaded_and_sends_an_absolute_path(engine):
    client, core = engine
    core.on(LoadRecipe, lambda message: [a_recipe_loaded()])

    loaded = client.load("bench.yml")

    assert loaded.name == "Wait demo"
    assert loaded.main_sequence == "Main"
    assert loaded.sequences == ("Main", "Extra")
    assert loaded.warnings == ()
    assert client.loaded == loaded
    # CORE is another process; a relative path would be resolved against its view.
    assert Path(core.sent_of(LoadRecipe)[0].recipe_path).is_absolute()


def test_a_notice_that_does_not_stop_the_load_is_kept_as_a_warning(engine):
    client, core = engine
    core.on(
        LoadRecipe,
        lambda message: [
            error_reported("written for pypts 0.1", "Recipe.from_file"),
            a_recipe_loaded(),
        ],
    )

    assert client.load("bench.yml").warnings == ("written for pypts 0.1",)


def test_a_refused_recipe_raises_with_cores_reason(engine):
    client, core = engine
    core.on(
        LoadRecipe,
        lambda message: [error_reported("missing the required field 'name'", "Core.load_recipe")],
    )

    with pytest.raises(PtsError, match="missing the required field 'name'"):
        client.load("bench.yml")
    assert client.loaded is None


def test_a_load_nobody_answers_times_out(engine):
    client, _core = engine

    with pytest.raises(PtsError, match="did not answer"):
        client.load("bench.yml", timeout_s=0.3)


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def test_run_returns_the_verdict_the_steps_and_the_report_folder(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    first = an_outcome("First wait", ResultType.DONE)
    second = an_outcome("Second wait", ResultType.FAIL, "too slow")
    core.on(
        StartSequence,
        lambda message: [
            started(),
            StepFinished(outcome=first),
            StepFinished(outcome=second),
            *finished(ResultType.FAIL),
        ],
    )

    result = client.run()

    assert [message.sequence_name for message in core.sent_of(StartSequence)] == ["Main"]
    assert result.sequence == "Main"
    assert result.result is ResultType.FAIL
    assert result.steps == (
        StepVerdict("First wait", ResultType.DONE, ""),
        StepVerdict("Second wait", ResultType.FAIL, "too slow"),
    )
    assert result.report_dir == "C:/reports/run"
    assert result.passed is False


def test_each_step_verdict_carries_the_steps_values(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    outcome = StepOutcome(
        step_id=uuid4(),
        step_name="Measure voltage",
        result=ResultType.PASS,
        inputs=(("channel", "1"),),
        outputs=(("voltage", "12.1"),),
        expectations=(("voltage", "range 11 .. 13"),),
    )
    core.on(
        StartSequence,
        lambda message: [started(), StepFinished(outcome=outcome), *finished(ResultType.PASS)],
    )

    result = client.run()

    (step,) = result.steps
    assert step.inputs == {"channel": "1"}
    assert step.outputs == {"voltage": "12.1"}
    assert step.expectations == {"voltage": "range 11 .. 13"}


def test_run_starts_the_sequence_it_is_given(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    core.on(StartSequence, lambda message: [started(), *finished()])

    assert client.run("Extra").sequence == "Extra"
    assert [message.sequence_name for message in core.sent_of(StartSequence)] == ["Extra"]


def test_run_without_a_recipe_raises_and_sends_nothing(engine):
    client, core = engine

    with pytest.raises(PtsError, match="No recipe is loaded"):
        client.run()
    time.sleep(0.1)
    assert core.sent_of(StartSequence) == []


def test_a_refused_start_raises(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    core.on(
        StartSequence,
        lambda message: [error_reported("a test is already running", "Sequencer.run_sequence")],
    )

    with pytest.raises(PtsError, match="already running"):
        client.run()


def test_an_error_during_the_run_is_collected_not_raised(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    core.on(
        StartSequence,
        lambda message: [
            started(),
            error_reported("the step blew up", "Sequencer.execute_sequence"),
            *finished(ResultType.ERROR),
        ],
    )

    result = client.run()

    assert result.result is ResultType.ERROR
    assert result.errors == ("the step blew up",)


def test_on_step_sees_each_step_as_it_finishes(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    core.on(
        StartSequence,
        lambda message: [
            started(),
            StepFinished(outcome=an_outcome("First wait", ResultType.DONE)),
            *finished(ResultType.DONE),
        ],
    )
    seen = []

    client.run(on_step=seen.append)

    assert seen == [StepVerdict("First wait", ResultType.DONE, "")]


def test_a_run_whose_report_never_arrives_still_returns(engine, monkeypatch):
    client, core = engine
    monkeypatch.setattr(embedding, "REPORT_TIMEOUT_S", 0.2)
    with_a_recipe_loaded(client, core)
    core.on(StartSequence, lambda message: [started(), RunFinished(result=ResultType.DONE)])

    result = client.run()

    assert result.result is ResultType.DONE
    assert result.report_dir is None


def test_the_engine_stopping_mid_run_raises(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    core.on(StartSequence, lambda message: [started(), StopHmi()])

    with pytest.raises(PtsError, match="engine stopped"):
        client.run()


# --------------------------------------------------------------------------
# Operator questions
# --------------------------------------------------------------------------


def test_a_question_is_answered_by_the_answer_function(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    request = UserPromptRequest(
        request_id=uuid4(), message="Is the LED lit?", options=("Yes", "No")
    )
    core.on(StartSequence, lambda message: [started(), request])
    core.on(UserPromptResponse, lambda message: finished())
    asked = []

    def answer(question):
        asked.append(question.message)
        return "Yes"

    client.run(answer=answer)

    assert asked == ["Is the LED lit?"]
    assert core.sent_of(UserPromptResponse) == [
        UserPromptResponse(request_id=request.request_id, choice="Yes")
    ]


def test_a_text_request_is_answered_by_the_answer_function(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    request = UserTextRequest(request_id=uuid4(), message="Serial number?")
    core.on(StartSequence, lambda message: [started(), request])
    core.on(UserTextResponse, lambda message: finished())

    client.run(answer=lambda question: "SN-0001")

    assert core.sent_of(UserTextResponse) == [
        UserTextResponse(request_id=request.request_id, text="SN-0001")
    ]


def test_a_path_request_is_answered_by_the_answer_function(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    request = UserPathRequest(
        request_id=uuid4(), message="Select the calibration file.", select="file"
    )
    core.on(StartSequence, lambda message: [started(), request])
    core.on(UserPathResponse, lambda message: finished())
    asked = []

    def answer(question):
        asked.append(question.select)
        return "C:/bench/cal.csv"

    client.run(answer=answer)

    assert asked == ["file"]
    assert core.sent_of(UserPathResponse) == [
        UserPathResponse(request_id=request.request_id, path="C:/bench/cal.csv")
    ]


def test_a_path_request_without_an_answer_function_is_declined(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    request = UserPathRequest(
        request_id=uuid4(), message="Select the dump folder.", select="folder"
    )
    core.on(StartSequence, lambda message: [started(), request])
    core.on(UserPathResponse, lambda message: finished(ResultType.ERROR))

    client.run()

    assert core.sent_of(UserPathResponse) == [
        UserPathResponse(request_id=request.request_id, path=None)
    ]


def test_without_an_answer_function_every_question_is_declined(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    request = UserPromptRequest(request_id=uuid4(), message="Continue?", options=("OK",))
    core.on(StartSequence, lambda message: [started(), request])
    core.on(UserPromptResponse, lambda message: finished(ResultType.ERROR))

    client.run()

    assert core.sent_of(UserPromptResponse) == [
        UserPromptResponse(request_id=request.request_id, choice=None)
    ]


def test_an_answer_function_that_raises_still_answers_so_the_step_is_not_left_waiting(engine):
    client, core = engine
    with_a_recipe_loaded(client, core)
    request = UserPromptRequest(request_id=uuid4(), message="Continue?", options=("OK",))
    core.on(StartSequence, lambda message: [started(), request])

    def broken(question):
        raise RuntimeError("the answer function is broken")

    with pytest.raises(RuntimeError, match="broken"):
        client.run(answer=broken)
    assert wait_until(lambda: core.sent_of(UserPromptResponse) != [])
    assert core.sent_of(UserPromptResponse)[0].choice is None


# --------------------------------------------------------------------------
# The result, and open_gui()'s own checks
# --------------------------------------------------------------------------


def test_passed_counts_done_as_passing():
    assert RunResult("Main", ResultType.PASS, ()).passed is True
    assert RunResult("Main", ResultType.DONE, ()).passed is True
    assert RunResult("Main", ResultType.FAIL, ()).passed is False
    assert RunResult("Main", ResultType.STOP, ()).passed is False


def test_open_gui_needs_start_to_name_a_sequence():
    with pytest.raises(ValueError, match="start=True"):
        open_gui("bench.yml", sequence="Main")


def test_open_gui_needs_a_recipe_to_start():
    with pytest.raises(ValueError, match="needs a recipe"):
        open_gui(start=True)


def test_open_gui_refuses_a_missing_recipe_before_starting_anything(monkeypatch, tmp_path):
    def must_not_start(*args, **kwargs):
        raise AssertionError("no process may be started for a file that is not there")

    monkeypatch.setattr(startup, "start_engine", must_not_start)

    with pytest.raises(PtsError, match="not found"):
        open_gui(tmp_path / "nowhere.yml")


def test_importing_the_api_does_not_import_qt():
    """A headless bench uses Pts; it must not need PySide6 to import it."""
    import subprocess
    import sys

    check = "import sys, pypts.api; sys.exit('PySide6' in sys.modules)"
    subprocess.run([sys.executable, "-c", check], check=True)
