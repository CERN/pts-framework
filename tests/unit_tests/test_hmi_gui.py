# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the GUI HMI (src/pypts/hmi/gui/).

GUI tests need a display. On a headless machine (and on the GitLab runner) set
QT_QPA_PLATFORM=offscreen; adding that to CI is an existing TODO. pytest-qt is
already a test dependency.

The GUI holds its widgets rather than inheriting from one. That is not a style
choice: PySide6's QWidget.__init__ cooperatively calls the next __init__ in the
MRO, so `class GUI(QWidget, HmiClient)` would call HmiClient.__init__ with no
arguments and fail at construction.

What is *not* tested here is the message handling, because the GUI does not
implement any: it inherits the whole protocol from HmiClient, and
test_messages.py asserts that both frontends leave it inherited. These tests
cover the presentation half - the four panel contents and the assembler wiring
between them.
"""

import queue
from uuid import uuid4

import pytest

from pypts.messages import QueueWrapper
from pypts.messages.common_messages import ErrorSeverity, ModuleError, ResultType, StepOutcome
from pypts.messages.core_hmi_communication import (
    HmiStopped,
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
    SequenceSummary,
    SerialNumberRequest,
    SerialNumberResponse,
    StepFinished,
    StepStarted,
    StepSummary,
    StopSequence,
    UserPromptRequest,
    UserPromptResponse,
)

PLACEHOLDER = "placeholder - test not implemented yet"

pytest.importorskip("PySide6", reason="the GUI is an optional extra")


def a_recipe_loaded():
    """A two-sequence recipe summary, the shape every table test needs."""
    main_steps = (
        StepSummary(step_id=uuid4(), step_name="First wait", description="Pause briefly."),
        StepSummary(step_id=uuid4(), step_name="Second wait", description="Pause again."),
    )
    extra_steps = (
        StepSummary(step_id=uuid4(), step_name="Only wait", description="One pause."),
    )
    return RecipeLoaded(
        recipe_name="Wait demo",
        recipe_version="1.0.0",
        main_sequence="Main",
        sequences=(
            SequenceSummary(sequence_name="Main", steps=main_steps),
            SequenceSummary(sequence_name="Extra", steps=extra_steps),
        ),
    )


@pytest.fixture
def gui(qapp):
    """A constructed GUI with both wrappers wired to plain queues.

    `qapp` comes from pytest-qt and gives the widgets the QApplication they
    need. Yields (gui, outbox, inbox) where outbox holds what the GUI sent to
    CORE.
    """
    from pypts.hmi.gui.gui import GUI

    outbox: queue.Queue = queue.Queue()
    inbox: queue.Queue = queue.Queue()
    instance = GUI(QueueWrapper(outbox), QueueWrapper(inbox))
    yield instance, outbox, QueueWrapper(inbox)
    instance.timer.stop()
    # closeEvent redirects [X] to a shutdown request; the teardown must really
    # close, or every test leaks an offscreen window into the next one.
    instance.window.allow_close = True
    instance.window.close()


def drain(a_queue):
    """Everything waiting on a queue right now, as a list."""
    messages = []
    while True:
        try:
            messages.append(a_queue.get_nowait())
        except queue.Empty:
            return messages


def load_demo_recipe(instance, inbox):
    event = a_recipe_loaded()
    inbox.send(event)
    instance.poll_core()
    return event


def result_column_texts(table):
    return [table.item(row, 2).text() for row in range(table.rowCount())]


def test_the_gui_forces_light_mode(qapp):
    """The GUI is designed light (the result colors are pale backgrounds with
    dark text); until a dark palette is designed, the OS theme must not leak in."""
    from PySide6.QtCore import Qt

    from pypts.hmi.gui.gui import force_light_mode

    force_light_mode(qapp)

    assert qapp.styleHints().colorScheme() == Qt.ColorScheme.Light


# --------------------------------------------------------------------------
# The status line and the shutdown handshake (pre-rebuild contract, kept)
# --------------------------------------------------------------------------


def test_gui_starts_offscreen(gui):
    """Construction alone is worth asserting - it is where the MRO trap fires."""
    instance, _outbox, _inbox = gui
    instance.show()

    assert instance.window.isVisible()
    assert instance.status_label.text() == "Status: Idle"


def test_status_label_follows_update_status_events(gui):
    instance, _outbox, inbox = gui

    inbox.send(StatusChanged(text="Running Main"))
    instance.poll_core()

    assert instance.status_label.text() == "Status: Running Main"


def test_module_errors_are_shown_to_the_operator(gui):
    """Before ModuleErrorReported existed, an error could only reach the log file."""
    instance, _outbox, inbox = gui

    inbox.send(
        ModuleErrorReported(
            error=ModuleError(
                source="pypts.sequencer.sequencer",
                severity=ErrorSeverity.ERROR,
                message="instrument did not respond",
            )
        )
    )
    instance.poll_core()

    assert "instrument did not respond" in instance.status_label.text()


def test_stop_button_asks_core_to_shut_down(gui):
    """The button asks; it does not leave.

    A frontend that stopped itself would orphan the Sequencer and the Report,
    which is what used to happen when the window was simply closed.
    """
    instance, outbox, _inbox = gui

    instance.request_shutdown()

    assert isinstance(outbox.get_nowait(), ShutdownRequested)
    assert instance.running is True


def test_stop_from_core_closes_the_window_and_acknowledges(gui):
    """The GUI half of the shutdown handshake CORE waits for."""
    instance, outbox, inbox = gui
    instance.show()

    inbox.send(StopHmi())
    instance.poll_core()

    assert instance.running is False
    assert not instance.window.isVisible()
    assert isinstance(outbox.get_nowait(), HmiStopped)


def test_window_close_asks_core_first_then_closes_on_stop_hmi(gui):
    """[X] is a shutdown *request* - the window only really closes when CORE
    answers StopHmi, so nothing is ever orphaned by closing the window."""
    instance, outbox, inbox = gui
    instance.show()

    instance.window.close()

    assert isinstance(outbox.get_nowait(), ShutdownRequested)
    assert instance.window.isVisible(), "the window must outlive its own [X] click"

    inbox.send(StopHmi())
    instance.poll_core()

    assert not instance.window.isVisible()
    assert isinstance(outbox.get_nowait(), HmiStopped)


# --------------------------------------------------------------------------
# The step table
# --------------------------------------------------------------------------


def test_recipe_loaded_prefills_the_step_table(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)

    table = instance.step_table.table
    assert table.rowCount() == 2
    assert [table.item(row, 0).text() for row in range(2)] == ["First wait", "Second wait"]
    assert [table.item(row, 1).text() for row in range(2)] == ["Pause briefly.", "Pause again."]
    assert result_column_texts(table) == ["Pending", "Pending"]
    from PySide6.QtCore import Qt

    stored = [table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(2)]
    assert stored == [str(step.step_id) for step in event.sequences[0].steps]


def test_step_started_marks_the_row_running(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)

    second = event.sequences[0].steps[1]
    inbox.send(StepStarted(step_id=second.step_id, step_name=second.step_name))
    instance.poll_core()

    assert result_column_texts(instance.step_table.table) == ["Pending", "Running..."]


def test_step_finished_writes_the_colored_verdict(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    first, second = event.sequences[0].steps

    inbox.send(
        StepFinished(
            outcome=StepOutcome(
                step_id=first.step_id, step_name=first.step_name, result=ResultType.PASS
            )
        )
    )
    inbox.send(
        StepFinished(
            outcome=StepOutcome(
                step_id=second.step_id,
                step_name=second.step_name,
                result=ResultType.FAIL,
                error_info="expected 45, got 44",
            )
        )
    )
    instance.poll_core()

    table = instance.step_table.table
    assert result_column_texts(table) == ["PASS", "FAIL"]
    assert table.item(0, 2).background().color().name().upper() == "#C8E6C9"
    assert table.item(0, 2).foreground().color().name().upper() == "#1B4F24"
    assert table.item(1, 2).background().color().name().upper() == "#F28B82"
    assert "expected 45" in table.item(1, 2).toolTip()


def test_a_run_restart_resets_the_verdicts_to_pending(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    first = event.sequences[0].steps[0]

    inbox.send(
        StepFinished(
            outcome=StepOutcome(
                step_id=first.step_id, step_name=first.step_name, result=ResultType.PASS
            )
        )
    )
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()

    assert result_column_texts(instance.step_table.table) == ["Pending", "Pending"]


def test_sequence_dropdown_refills_the_table(gui):
    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)

    instance.top_bar.sequence_combo.setCurrentText("Extra")

    table = instance.step_table.table
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Only wait"


# --------------------------------------------------------------------------
# The top bar - commands out, state machine
# --------------------------------------------------------------------------


def test_run_lifecycle_drives_the_button_states(gui):
    instance, _outbox, inbox = gui
    top = instance.top_bar

    assert top.open_button.isEnabled()
    assert not top.start_button.isEnabled()
    assert not top.stop_button.isEnabled()

    load_demo_recipe(instance, inbox)
    assert top.start_button.isEnabled()
    assert top.sequence_combo.isEnabled()
    assert not top.stop_button.isEnabled()

    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()
    assert not top.open_button.isEnabled()
    assert not top.start_button.isEnabled()
    assert not top.sequence_combo.isEnabled()
    assert top.stop_button.isEnabled()

    inbox.send(RunFinished(result=ResultType.DONE))
    instance.poll_core()
    assert top.open_button.isEnabled()
    assert top.start_button.isEnabled()
    assert top.sequence_combo.isEnabled()
    assert not top.stop_button.isEnabled()


def test_start_sends_the_selected_sequence(gui, qtbot):
    instance, outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    top = instance.top_bar

    top.sequence_combo.setCurrentText("Extra")
    top.start_button.click()

    sent = drain(outbox)
    assert StartSequence(sequence_name="Extra") in sent


def test_stop_button_sends_stop_sequence(gui):
    instance, outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()

    instance.top_bar.stop_button.click()

    assert StopSequence() in drain(outbox)


# --------------------------------------------------------------------------
# The center view - prompts
# --------------------------------------------------------------------------


def test_ask_user_shows_the_prompt_and_answers_once(gui):
    instance, outbox, _inbox = gui
    request = UserPromptRequest(
        request_id=uuid4(), message="Connect the DUT", options=("yes", "no")
    )

    instance.ask_user(request)

    center = instance.center
    assert center.stack.currentWidget() is center.prompt_page
    assert "Connect the DUT" in center.prompt_message.text()
    assert [b.text() for b in center.option_buttons] == ["yes", "no"]

    center.option_buttons[0].click()

    assert UserPromptResponse(request_id=request.request_id, choice="yes") in drain(outbox)
    assert center.stack.currentWidget() is center.idle_page


def test_a_new_prompt_declines_the_unanswered_one(gui):
    """A step waiting on the old request must be released, not stranded."""
    instance, outbox, _inbox = gui
    first = UserPromptRequest(request_id=uuid4(), message="First?", options=("ok",))
    second = UserPromptRequest(request_id=uuid4(), message="Second?", options=("ok",))

    instance.ask_user(first)
    instance.ask_user(second)

    assert UserPromptResponse(request_id=first.request_id, choice=None) in drain(outbox)
    assert "Second?" in instance.center.prompt_message.text()


def test_run_finished_cancels_a_pending_prompt(gui):
    instance, outbox, inbox = gui
    request = UserPromptRequest(request_id=uuid4(), message="Still there?", options=("ok",))
    instance.ask_user(request)

    inbox.send(RunFinished(result=ResultType.STOP))
    instance.poll_core()

    assert UserPromptResponse(request_id=request.request_id, choice=None) in drain(outbox)
    assert instance.center.stack.currentWidget() is instance.center.idle_page


def test_ask_serial_number_round_trip(gui):
    instance, outbox, _inbox = gui
    request = SerialNumberRequest(request_id=uuid4())

    instance.ask_serial_number(request)
    center = instance.center
    assert center.stack.currentWidget() is center.serial_page
    center.serial_input.setText("SN-0042")
    center.serial_ok_button.click()

    assert SerialNumberResponse(request_id=request.request_id, serial_number="SN-0042") in drain(
        outbox
    )
    assert center.stack.currentWidget() is center.idle_page

    # And the cancel path answers None rather than leaving the step waiting.
    request2 = SerialNumberRequest(request_id=uuid4())
    instance.ask_serial_number(request2)
    center.serial_cancel_button.click()
    assert SerialNumberResponse(request_id=request2.request_id, serial_number=None) in drain(
        outbox
    )


# --------------------------------------------------------------------------
# Phase 3 placeholders
# --------------------------------------------------------------------------


@pytest.mark.skip(reason=PLACEHOLDER)
def test_gui_survives_an_engine_crash_and_reports_it():
    """The reason the GUI keeps its own process."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_widgets_are_resolved_by_step_or_stream_type():
    """"Widgets can be expanded, but the GUI implementation stays the same"."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_view_refreshes_on_every_event():
    """Known bug in TODO.txt: the GUI does not always refresh properly."""
