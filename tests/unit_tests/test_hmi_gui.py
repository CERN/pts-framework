# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the GUI HMI (src/pypts/hmi/gui/).

GUI tests run offscreen: tests/conftest.py sets QT_QPA_PLATFORM=offscreen unless
it is already set, so no window reaches the screen. pytest-qt is already a test
dependency.

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

import logging
import queue
from pathlib import Path
from uuid import uuid4

import pytest

from pypts.config_handler import file_locations
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
    PauseSequence,
    RecipeLoaded,
    ResumeSequence,
    RunFinished,
    RunMetadata,
    RunPaused,
    RunResumed,
    RunStarted,
    SequenceSummary,
    StepFinished,
    StepStarted,
    StepSummary,
    StopSequence,
    UserPathRequest,
    UserPathResponse,
    UserPromptRequest,
    UserPromptResponse,
    UserTextRequest,
    UserTextResponse,
)

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


@pytest.fixture(autouse=True)
def isolated_recent_recipes(tmp_path, monkeypatch):
    """No GUI test may read or write the operator's real recent-recipes list."""
    monkeypatch.setattr(
        file_locations,
        "recent_recipes_path",
        lambda: tmp_path / "state" / "recent_recipes.json",
    )


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    """
    No GUI test may read the operator's real config.ini: its [gui] theme and
    window size would decide what every test here sees.

    Pointed at a file that does not exist, so a GUI opens with the template's
    defaults - and a test that wants a configuration writes one there with
    `a_config_file()`. The operating system's theme, which the default theme
    follows, is pinned to light for the same reason.
    """
    from pypts.config_handler import ConfigHandler
    from pypts.hmi.gui import gui as gui_module

    monkeypatch.setattr(
        file_locations, "config_file_path", lambda: tmp_path / "config" / "config.ini"
    )
    monkeypatch.setattr(gui_module, "detect_system_dark_mode", lambda app=None: False)
    ConfigHandler.reset_for_testing()
    yield
    ConfigHandler.reset_for_testing()


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


def test_theme_detection_returns_a_bool(qapp):
    """detect_system_dark_mode is always callable and returns a bool."""
    from pypts.hmi.gui.gui_theme import detect_system_dark_mode

    result = detect_system_dark_mode(qapp)

    assert isinstance(result, bool)


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
# The run progress bar - GUI only, counted from the summary and StepFinished
# --------------------------------------------------------------------------


def a_nested_recipe_loaded():
    """Main: a step, a call (group row) with two steps inside, and a teardown step."""
    rows = (
        StepSummary(step_id=uuid4(), step_name="Setup", description=""),
        StepSummary(step_id=uuid4(), step_name="Sub", description="", is_group=True),
        StepSummary(step_id=uuid4(), step_name="Inner one", description="", depth=1),
        StepSummary(step_id=uuid4(), step_name="Inner two", description="", depth=1),
        StepSummary(step_id=uuid4(), step_name="Teardown", description=""),
    )
    return RecipeLoaded(
        recipe_name="Nested demo",
        recipe_version="1.0.0",
        main_sequence="Main",
        sequences=(SequenceSummary(sequence_name="Main", steps=rows),),
    )


def finished(step, result=ResultType.PASS):
    return StepFinished(
        outcome=StepOutcome(step_id=step.step_id, step_name=step.step_name, result=result)
    )


def test_progress_text_counts_and_rounds_the_percentage_down():
    from pypts.hmi.gui.run_progress import progress_text

    assert progress_text(6, 15) == "6 / 15 (40 %)"
    assert progress_text(2, 3) == "2 / 3 (66 %)"
    assert progress_text(0, 0) == "0 / 0 (0 %)"


def test_the_progress_bar_is_hidden_until_a_recipe_is_loaded(gui):
    instance, _outbox, inbox = gui
    progress = instance.window.run_progress
    assert progress.isHidden()

    load_demo_recipe(instance, inbox)

    assert not progress.isHidden()
    assert progress.label.text() == "0 / 2 (0 %)"


def test_the_progress_bar_counts_nested_steps_but_not_call_rows(gui):
    instance, _outbox, inbox = gui
    event = a_nested_recipe_loaded()
    inbox.send(event)
    instance.poll_core()
    setup, call, inner_one, inner_two, teardown = event.sequences[0].steps
    progress = instance.window.run_progress
    assert progress.label.text() == "0 / 4 (0 %)"

    inbox.send(RunStarted(recipe_name="Nested demo", recipe_description=""))
    inbox.send(finished(setup))
    inbox.send(finished(inner_one))
    inbox.send(finished(inner_two, ResultType.SKIP))
    inbox.send(finished(call))
    instance.poll_core()

    assert progress.label.text() == "3 / 4 (75 %)"
    assert progress.bar.value() == 3
    assert progress.bar.maximum() == 4

    inbox.send(finished(teardown, ResultType.STOP))
    instance.poll_core()
    assert progress.label.text() == "4 / 4 (100 %)"


def test_a_step_finished_twice_is_counted_once(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    first = event.sequences[0].steps[0]

    inbox.send(finished(first))
    inbox.send(finished(first))
    instance.poll_core()

    assert instance.window.run_progress.label.text() == "1 / 2 (50 %)"


def test_the_progress_bar_empties_on_run_start_and_on_a_new_selection(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    progress = instance.window.run_progress

    inbox.send(finished(event.sequences[0].steps[0]))
    inbox.send(RunFinished(result=ResultType.PASS, outcomes=()))
    instance.poll_core()
    assert progress.label.text() == "1 / 2 (50 %)"

    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()
    assert progress.label.text() == "0 / 2 (0 %)"

    instance.top_bar.sequence_combo.setCurrentText("Extra")
    assert progress.label.text() == "0 / 1 (0 %)"


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
    assert not center.interaction.is_idle()
    assert "Connect the DUT" in center.prompt_message.text()
    # Cancel is appended to every prompt, after the recipe's own options, so
    # the operator is never stuck in front of a question they cannot answer.
    assert [b.text() for b in center.option_buttons] == ["yes", "no", "Cancel"]

    center.option_buttons[0].click()

    assert UserPromptResponse(request_id=request.request_id, choice="yes") in drain(outbox)
    assert center.interaction.is_idle()


def test_the_cancel_button_declines_the_prompt(gui):
    """Cancel answers None, which the step that asked turns into an ERROR."""
    instance, outbox, _inbox = gui
    request = UserPromptRequest(
        request_id=uuid4(), message="Connect the DUT", options=("yes", "no")
    )

    instance.ask_user(request)
    instance.center.option_buttons[-1].click()

    assert UserPromptResponse(request_id=request.request_id, choice=None) in drain(outbox)
    assert instance.center.interaction.is_idle()


def test_a_second_cancel_click_answers_nothing(gui):
    """The exactly-once gate covers Cancel like any other answer."""
    instance, outbox, _inbox = gui
    request = UserPromptRequest(request_id=uuid4(), message="Well?", options=("ok",))

    instance.ask_user(request)
    cancel = instance.center.option_buttons[-1]
    cancel.click()
    drain(outbox)
    cancel.click()

    assert drain(outbox) == []


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
    # After run finishes the center returns to the idle interaction panel.
    assert instance.center.interaction.is_idle()


def test_ask_user_text_round_trip(gui):
    instance, outbox, _inbox = gui
    request = UserTextRequest(
        request_id=uuid4(), message="Scan or type the serial number"
    )

    instance.ask_user_text(request)
    center = instance.center
    panel = center.interaction
    assert not panel.is_idle()
    assert "serial number" in center.prompt_message.text()
    # No empty answers: OK stays disabled until something is typed, which is
    # why no recipe has to spell an `allow_empty` out.
    assert not panel.text_ok_button.isEnabled()
    panel.text_input.setText("SN-0042")
    assert panel.text_ok_button.isEnabled()
    panel.text_ok_button.click()

    assert UserTextResponse(request_id=request.request_id, text="SN-0042") in drain(outbox)
    assert panel.is_idle()

    # And the cancel path answers None rather than leaving the step waiting.
    request2 = UserTextRequest(request_id=uuid4(), message="Again?")
    instance.ask_user_text(request2)
    panel.text_cancel_button.click()
    assert UserTextResponse(request_id=request2.request_id, text=None) in drain(outbox)


def test_a_text_request_supersedes_an_unanswered_prompt(gui):
    """The two questions share one panel, so the exactly-once gate spans both."""
    instance, outbox, _inbox = gui
    prompt = UserPromptRequest(request_id=uuid4(), message="Well?", options=("ok",))
    text_request = UserTextRequest(request_id=uuid4(), message="Type it")

    instance.ask_user(prompt)
    instance.ask_user_text(text_request)

    assert UserPromptResponse(request_id=prompt.request_id, choice=None) in drain(outbox)
    assert "Type it" in instance.center.prompt_message.text()


# --------------------------------------------------------------------------
# The center view - the path prompt (UserLoading)
# --------------------------------------------------------------------------


def a_path_request(select="file", message="Select the calibration file for this unit."):
    return UserPathRequest(request_id=uuid4(), message=message, select=select)


def no_real_file_dialog(monkeypatch, chosen_file="", chosen_folder=""):
    """Replace both choosers the path page can open, so no real dialog appears.
    Returns the list of calls, each (kind, start_folder)."""
    from pypts.hmi.gui import interaction_panel

    calls = []

    def fake_open_file_name(parent, caption="", start_folder=""):
        calls.append(("file", start_folder))
        return chosen_file, ""

    def fake_existing_directory(parent, caption="", start_folder=""):
        calls.append(("folder", start_folder))
        return chosen_folder

    monkeypatch.setattr(interaction_panel.QFileDialog, "getOpenFileName", fake_open_file_name)
    monkeypatch.setattr(
        interaction_panel.QFileDialog, "getExistingDirectory", fake_existing_directory
    )
    return calls


def test_a_path_request_shows_the_path_page(gui):
    instance, _outbox, inbox = gui

    request = a_path_request()
    inbox.send(request)
    instance.poll_core()

    center = instance.center
    panel = center.interaction
    assert not panel.is_idle()
    assert "calibration file" in center.prompt_message.text()
    assert panel.path_input.text() == ""
    assert panel.path_browse_button.text() == "Browse..."
    assert not panel.path_ok_button.isEnabled()


def test_path_ok_is_disabled_until_the_path_is_an_existing_file(gui, tmp_path):
    instance, _outbox, _inbox = gui
    instance.ask_user_path(a_path_request(select="file"))
    panel = instance.center.interaction

    assert not panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() != ""

    panel.path_input.setText(str(tmp_path / "missing.csv"))
    assert not panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() == "No such file."

    panel.path_input.setText(str(tmp_path))
    assert not panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() == "That is a folder - a file is asked for."

    calibration = tmp_path / "unit42.csv"
    calibration.write_text("1,2,3")
    panel.path_input.setText(str(calibration))
    assert panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() == ""


def test_path_ok_is_disabled_until_the_path_is_an_existing_folder(gui, tmp_path):
    instance, _outbox, _inbox = gui
    instance.ask_user_path(a_path_request(select="folder", message="Pick the dump folder"))
    panel = instance.center.interaction

    panel.path_input.setText(str(tmp_path / "no_such_folder"))
    assert not panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() == "No such folder."

    a_file = tmp_path / "a_file.txt"
    a_file.write_text("x")
    panel.path_input.setText(str(a_file))
    assert not panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() == "That is a file - a folder is asked for."

    panel.path_input.setText(str(tmp_path))
    assert panel.path_ok_button.isEnabled()
    assert panel.path_hint_label.text() == ""


def test_path_ok_sends_the_absolute_path_to_core(gui, tmp_path):
    instance, outbox, _inbox = gui
    request = a_path_request()
    instance.ask_user_path(request)
    panel = instance.center.interaction
    calibration = tmp_path / "unit42.csv"
    calibration.write_text("1,2,3")

    panel.path_input.setText(f"  {calibration}  ")
    panel.path_ok_button.click()

    expected = UserPathResponse(request_id=request.request_id, path=str(calibration.resolve()))
    assert expected in drain(outbox)
    assert panel.is_idle()


def test_a_relative_path_is_sent_absolute(gui, tmp_path, monkeypatch):
    """CORE would resolve a relative path against its own working directory."""
    instance, outbox, _inbox = gui
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cal").mkdir()
    request = a_path_request(select="folder")
    instance.ask_user_path(request)
    panel = instance.center.interaction

    panel.path_input.setText("cal")
    assert panel.path_ok_button.isEnabled()
    panel.path_ok_button.click()

    sent = drain(outbox)
    expected = str((tmp_path / "cal").resolve())
    assert UserPathResponse(request_id=request.request_id, path=expected) in sent
    assert Path(expected).is_absolute()


def test_return_in_the_path_field_answers_only_when_valid(gui, tmp_path):
    instance, outbox, _inbox = gui
    request = a_path_request()
    instance.ask_user_path(request)
    panel = instance.center.interaction

    panel.path_input.setText(str(tmp_path / "missing.csv"))
    panel.path_input.returnPressed.emit()
    assert drain(outbox) == []
    assert not panel.is_idle()

    calibration = tmp_path / "unit42.csv"
    calibration.write_text("1,2,3")
    panel.path_input.setText(str(calibration))
    panel.path_input.returnPressed.emit()
    expected = UserPathResponse(request_id=request.request_id, path=str(calibration.resolve()))
    assert expected in drain(outbox)


def test_browse_fills_the_path_field_from_the_file_chooser(gui, tmp_path, monkeypatch):
    instance, _outbox, _inbox = gui
    calibration = tmp_path / "unit42.csv"
    calibration.write_text("1,2,3")
    # Qt hands paths out with forward slashes.
    calls = no_real_file_dialog(monkeypatch, chosen_file=calibration.as_posix())
    instance.ask_user_path(a_path_request(select="file"))
    panel = instance.center.interaction

    panel.path_browse_button.click()

    assert calls == [("file", "")]
    assert panel.path_input.text() == str(calibration)
    assert panel.path_ok_button.isEnabled()


def test_browse_uses_the_folder_chooser_and_starts_where_the_field_points(
    gui, tmp_path, monkeypatch
):
    instance, _outbox, _inbox = gui
    start = tmp_path / "start"
    start.mkdir()
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    calls = no_real_file_dialog(monkeypatch, chosen_folder=str(chosen))
    instance.ask_user_path(a_path_request(select="folder"))
    panel = instance.center.interaction
    panel.path_input.setText(str(start))

    panel.path_browse_button.click()

    assert calls == [("folder", str(start.resolve()))]
    assert panel.path_input.text() == str(chosen)


def test_a_cancelled_chooser_leaves_the_path_field_unchanged(gui, tmp_path, monkeypatch):
    instance, outbox, _inbox = gui
    calibration = tmp_path / "unit42.csv"
    calibration.write_text("1,2,3")
    calls = no_real_file_dialog(monkeypatch, chosen_file="")
    instance.ask_user_path(a_path_request(select="file"))
    panel = instance.center.interaction
    panel.path_input.setText(str(calibration))

    panel.path_browse_button.click()

    # A file in the field: the chooser starts in the folder that holds it.
    assert calls == [("file", str(tmp_path.resolve()))]
    assert panel.path_input.text() == str(calibration)
    assert drain(outbox) == []
    assert not panel.is_idle()


def test_the_cancel_button_declines_the_path_prompt(gui):
    instance, outbox, _inbox = gui
    request = a_path_request()
    instance.ask_user_path(request)

    instance.center.interaction.path_cancel_button.click()

    assert UserPathResponse(request_id=request.request_id, path=None) in drain(outbox)
    assert instance.center.interaction.is_idle()


def test_run_finished_cancels_a_pending_path_prompt(gui):
    instance, outbox, inbox = gui
    request = a_path_request()
    instance.ask_user_path(request)

    inbox.send(RunFinished(result=ResultType.STOP))
    instance.poll_core()

    assert UserPathResponse(request_id=request.request_id, path=None) in drain(outbox)
    assert instance.center.interaction.is_idle()


def test_a_path_request_supersedes_an_unanswered_text_request(gui):
    """Three questions, one panel: the exactly-once gate spans all of them."""
    instance, outbox, _inbox = gui
    text_request = UserTextRequest(request_id=uuid4(), message="Type it")
    path_request = a_path_request(message="Pick it")

    instance.ask_user_text(text_request)
    instance.ask_user_path(path_request)

    assert UserTextResponse(request_id=text_request.request_id, text=None) in drain(outbox)
    panel = instance.center.interaction
    assert "Pick it" in instance.center.prompt_message.text()
    assert not panel._text_row.isVisibleTo(panel)
    assert panel._path_page.isVisibleTo(panel)


# --------------------------------------------------------------------------
# The report button
# --------------------------------------------------------------------------


def test_report_ready_points_the_report_button_at_the_run(gui, tmp_path):
    """The button is live from the start; a finished run redirects it at itself.

    Always enabled on purpose: old reports are browsable without finishing a
    run. Before the first ReportReady the destination is the reports root,
    which open_report_folder() resolves from the config.
    """
    from pypts.messages.core_hmi_communication import ReportReady

    instance, _outbox, inbox = gui
    assert instance.top_bar.report_button.isEnabled() is True
    assert instance.report_dir is None

    run_dir = tmp_path / "run_1"
    inbox.send(
        ReportReady(report_path=str(run_dir / "report.html"), report_dir=str(run_dir))
    )
    instance.poll_core()

    assert instance.top_bar.report_button.isEnabled() is True
    assert instance.report_dir == str(run_dir)

# --------------------------------------------------------------------------
# The LOG OUTPUT panel
# --------------------------------------------------------------------------


def a_record(level: str, message: str, clock: str = "12:04:31") -> str:
    """One line in the shape log.LOG_FORMAT writes: time;LEVEL;process;where;message."""
    return f"2026-09-01 {clock}.123;{level};Core;core.py:handle_message;{message}"


def test_format_record_shows_level_time_and_message():
    """Level first, because that is what LogPanel colours on; date and origin dropped."""
    from pypts.hmi.gui.log_tail import format_record

    line = format_record(a_record("INFO", "Recipe 'demo' (v1.0) loaded."))

    assert line is not None
    assert line.startswith("INFO")
    assert "12:04:31" in line
    assert line.endswith("Recipe 'demo' (v1.0) loaded.")
    # The parts the Debug Monitor is for stay out of the operator's panel.
    assert "core.py" not in line
    assert "2026-09-01" not in line


def test_format_record_keeps_a_message_containing_semicolons():
    """The message is the last field, so it is split off with a maxsplit, not naively."""
    from pypts.hmi.gui.log_tail import format_record

    line = format_record(a_record("INFO", "values: a;b;c"))

    assert line is not None
    assert line.endswith("values: a;b;c")


def test_format_record_drops_records_below_the_panel_level():
    """config.ini ships DEBUG, so the file carries the whole message trace."""
    from pypts.hmi.gui.log_tail import format_record

    assert format_record(a_record("DEBUG", "HMI->CORE send: LoadRecipe(...)")) is None
    assert format_record(a_record("WARNING", "unknown log level")) is not None
    assert format_record(a_record("ERROR", "it broke")) is not None


def test_log_tail_reads_only_what_is_new(tmp_path):
    """Each call returns the records written since the last one."""
    from pypts.hmi.gui.log_tail import LogTail

    log_file = tmp_path / "run.log"
    log_file.write_text(a_record("INFO", "first") + "\n", encoding="utf-8")

    tail = LogTail(log_file)
    tail.open()
    try:
        assert [line.endswith("first") for line in tail.new_lines()] == [True]
        assert tail.new_lines() == []

        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(a_record("INFO", "second") + "\n")

        assert [line.endswith("second") for line in tail.new_lines()] == [True]
    finally:
        tail.close()


def test_log_tail_holds_back_a_torn_record(tmp_path):
    """A read can land between the write and the flush; half a record is never shown."""
    from pypts.hmi.gui.log_tail import LogTail

    log_file = tmp_path / "run.log"
    whole = a_record("INFO", "complete record")
    log_file.write_text(whole[:20], encoding="utf-8")

    tail = LogTail(log_file)
    tail.open()
    try:
        assert tail.new_lines() == []

        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(whole[20:] + "\n")

        lines = tail.new_lines()
        assert len(lines) == 1
        assert lines[0].endswith("complete record")
    finally:
        tail.close()


def test_log_tail_keeps_traceback_lines_with_their_record(tmp_path):
    """A traceback is written under its record and has to travel with it."""
    from pypts.hmi.gui.log_tail import LogTail

    log_file = tmp_path / "run.log"
    log_file.write_text(
        a_record("ERROR", "it broke") + "\n"
        + "Traceback (most recent call last):" + "\n"
        + "  ValueError: nope" + "\n"
        + a_record("DEBUG", "trace") + "\n"
        + "  dropped continuation" + "\n",
        encoding="utf-8",
    )

    tail = LogTail(log_file)
    tail.open()
    try:
        lines = tail.new_lines()
    finally:
        tail.close()

    assert lines[0].startswith("ERROR")
    assert lines[1] == "Traceback (most recent call last):"
    assert lines[2] == "  ValueError: nope"
    # The DEBUG record was dropped, so what hangs under it goes with it.
    assert len(lines) == 3


def test_the_panel_is_filled_from_the_run_log(gui, tmp_path, monkeypatch):
    """The operator's panel shows the run, which happens in CORE, not in the GUI."""
    from pypts.hmi.gui import gui as gui_module

    instance, _outbox, _inbox = gui

    log_file = tmp_path / "run.log"
    log_file.write_text(
        a_record("INFO", "Recipe 'demo' (v1.0) loaded.") + "\n"
        + a_record("DEBUG", "HMI->CORE send: LoadRecipe(...)") + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gui_module, "get_log_path", lambda: str(log_file))

    instance.start_log_tail()
    instance.poll_log()

    shown = instance.center.log_panel.toPlainText()
    assert "Recipe 'demo' (v1.0) loaded." in shown
    assert "HMI->CORE send" not in shown

    instance.stop_log_tail()


def test_a_gui_without_a_run_log_says_so_and_does_not_poll(gui):
    """A frontend started by hand, or a test, has no log file to follow."""
    instance, _outbox, _inbox = gui

    # The fixture's GUI was built with no path - init_logging() was never told one.
    assert instance.log_tail is None
    assert instance.log_timer.isActive() is False
    assert "No run log to follow." in instance.center.log_panel.toPlainText()


# --------------------------------------------------------------------------
# Open Recent
# --------------------------------------------------------------------------


def a_recipe_file(tmp_path, name="wait_demo.yml"):
    path = tmp_path / name
    path.write_text("name: wait demo", encoding="utf-8")
    return path


def recent_menu_labels(instance):
    """What the submenu shows right now, rebuilt the way Qt rebuilds it."""
    instance._rebuild_recent_menu()
    return [action.text() for action in instance.window.recent_menu.actions()]


def test_a_loaded_recipe_is_remembered(gui, tmp_path):
    """The entry is written when CORE confirms the parse, not when it is chosen."""
    instance, _outbox, inbox = gui
    recipe = a_recipe_file(tmp_path)

    instance.open_recipe(str(recipe))
    load_demo_recipe(instance, inbox)

    entries = instance.recent_recipes.entries()
    assert len(entries) == 1
    assert entries[0].recipe_name == "Wait demo"
    assert entries[0].path == str(recipe.resolve())


def test_a_recipe_that_never_loaded_is_not_remembered(gui, tmp_path):
    """Chosen in the dialog, rejected by CORE: not something to offer again."""
    instance, _outbox, _inbox = gui

    instance.open_recipe(str(a_recipe_file(tmp_path, "broken.yml")))

    assert instance.recent_recipes.entries() == []


def test_the_submenu_lists_recipes_most_recent_first(gui, tmp_path):
    instance, _outbox, inbox = gui
    for name in ("first.yml", "second.yml"):
        instance.open_recipe(str(a_recipe_file(tmp_path, name)))
        load_demo_recipe(instance, inbox)

    labels = recent_menu_labels(instance)

    assert labels[0] == "second.yml"
    assert labels[1] == "first.yml"
    assert "Clear list" in labels


def test_an_empty_submenu_says_so_and_cannot_be_clicked(gui):
    """A dead menu item beats an empty menu the operator thinks is broken."""
    instance, _outbox, _inbox = gui

    instance._rebuild_recent_menu()
    actions = instance.window.recent_menu.actions()

    assert len(actions) == 1
    assert actions[0].isEnabled() is False
    assert "No recent recipes" in actions[0].text()


def test_the_full_path_is_the_tooltip(gui, tmp_path):
    """Two recipes of the same name in different folders have to be tellable apart."""
    instance, _outbox, inbox = gui
    recipe = a_recipe_file(tmp_path)
    instance.open_recipe(str(recipe))
    load_demo_recipe(instance, inbox)

    instance._rebuild_recent_menu()

    assert instance.window.recent_menu.actions()[0].toolTip() == str(recipe.resolve())


def test_opening_a_recent_recipe_asks_core_to_load_it(gui, tmp_path):
    instance, outbox, inbox = gui
    recipe = a_recipe_file(tmp_path)
    instance.open_recipe(str(recipe))
    load_demo_recipe(instance, inbox)
    drain(outbox)

    instance._rebuild_recent_menu()
    instance.window.recent_menu.actions()[0].trigger()

    sent = drain(outbox)
    assert [type(message).__name__ for message in sent] == ["LoadRecipe"]
    assert sent[0].recipe_path == str(recipe.resolve())


def test_a_recent_recipe_that_is_gone_is_reported_and_forgotten(gui, tmp_path):
    """The only place the store checks the disk: one stat, on an explicit click."""
    instance, outbox, inbox = gui
    recipe = a_recipe_file(tmp_path)
    instance.open_recipe(str(recipe))
    load_demo_recipe(instance, inbox)
    drain(outbox)
    recipe.unlink()

    instance._rebuild_recent_menu()
    instance.window.recent_menu.actions()[0].trigger()

    assert instance.recent_recipes.entries() == []
    sent = drain(outbox)
    assert [type(message).__name__ for message in sent] == ["ModuleError"]
    assert sent[0].severity is ErrorSeverity.WARNING
    assert sent[0].operation == "open_recent"


def test_clear_list_empties_the_submenu(gui, tmp_path):
    instance, _outbox, inbox = gui
    instance.open_recipe(str(a_recipe_file(tmp_path)))
    load_demo_recipe(instance, inbox)

    instance._rebuild_recent_menu()
    actions = instance.window.recent_menu.actions()
    clear_action = next(a for a in actions if a.text() == "Clear list")
    clear_action.trigger()

    assert instance.recent_recipes.entries() == []


# --------------------------------------------------------------------------
# The colour palette - one file for every colour the GUI uses
# --------------------------------------------------------------------------


def test_both_themes_define_every_token():
    """LIGHT and DARK are the same dataclass, so a token added to one exists in
    the other by construction - this pins that none is left empty."""
    from pypts.hmi.gui.palette import DARK, LIGHT, token_names

    for palette in (LIGHT, DARK):
        assert palette.verdicts, f"{palette.name} has no verdict chips"
        for token in token_names():
            value = getattr(palette, token)
            # logo_tint is None in the light theme: the artwork is already the
            # right blue there, and tinting it would be a no-op with a cost.
            if token == "logo_tint" and value is None:
                continue
            assert value, f"{palette.name}.{token} is empty"


def test_every_token_is_a_hex_colour():
    """A typo'd colour is silently ignored by Qt, so it is caught here instead."""
    import re

    from pypts.hmi.gui.palette import DARK, LIGHT, token_names

    hex_colour = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
    for palette in (LIGHT, DARK):
        for token in token_names():
            value = getattr(palette, token)
            if token == "logo_tint" and value is None:
                continue
            assert hex_colour.match(value), f"{palette.name}.{token} = {value!r}"
        for name, chip in palette.verdicts.items():
            assert hex_colour.match(chip.background), f"{palette.name} {name} background"
            assert hex_colour.match(chip.text), f"{palette.name} {name} text"


def test_every_result_type_has_a_verdict_chip_in_both_themes():
    """A new ResultType with no colour would paint as the white-on-black
    fallback in the step table and the results panel."""
    from pypts.hmi.gui.palette import DARK, LIGHT

    for palette in (LIGHT, DARK):
        for result in ResultType:
            assert result.name in palette.verdicts, f"no {palette.name} chip for {result.name}"
        for state in ("PENDING", "RUNNING"):
            assert state in palette.verdicts, f"no {palette.name} chip for {state}"


def test_the_two_themes_agree_on_which_verdicts_exist():
    """The hue is what an operator reads, so both themes must cover the same
    set - a verdict coloured in one theme and not the other is a bug waiting."""
    from pypts.hmi.gui.palette import DARK, LIGHT

    assert set(LIGHT.verdicts) == set(DARK.verdicts)


def test_the_step_table_paints_the_verdict_chip(gui):
    """The Result cell carries the chip's background, not only its text colour -
    a stylesheet ::item rule used to suppress exactly this (gui.md section 9)."""
    from PySide6.QtGui import QColor

    from pypts.hmi.gui.palette import LIGHT

    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    step = event.sequences[0].steps[0]

    inbox.send(
        StepFinished(
            outcome=StepOutcome(
                step_id=step.step_id, step_name=step.step_name,
                result=ResultType.PASS, error_info="",
            )
        )
    )
    instance.poll_core()

    table = instance.step_table.table
    cell = table.item(0, 2)
    expected = LIGHT.verdicts["PASS"]
    assert cell.background().color() == QColor(expected.background)
    assert cell.foreground().color() == QColor(expected.text)


def test_no_colour_literal_lives_outside_the_palette():
    """The whole point of palette.py: one file to edit. A hex anywhere else in
    hmi/gui/ means the next colour change misses it."""
    import re
    from pathlib import Path

    gui_package = Path(__file__).parents[2] / "src" / "pypts" / "hmi" / "gui"
    offenders = {}
    for source in gui_package.glob("*.py"):
        if source.name == "palette.py":
            continue
        found = re.findall(r"#[0-9a-fA-F]{3,8}\b", source.read_text(encoding="utf-8"))
        if found:
            offenders[source.name] = sorted(set(found))

    assert not offenders, f"colour literals outside palette.py: {offenders}"


def test_the_window_title_names_the_loaded_recipe(gui):
    """Several bench windows are often open at once, and the taskbar shows only the title."""
    instance, _outbox, inbox = gui
    assert instance.window.windowTitle() == "pyPTS"

    load_demo_recipe(instance, inbox)

    assert instance.window.windowTitle() == "pyPTS: Wait demo"


def test_open_recipe_and_start_starts_the_main_sequence_once_it_has_loaded(gui):
    from pypts.messages.core_hmi_communication import LoadRecipe, StartSequence

    instance, outbox, inbox = gui

    instance.open_recipe_and_start("bench.yml")
    assert drain(outbox) == [LoadRecipe("bench.yml")]

    load_demo_recipe(instance, inbox)

    assert drain(outbox) == [StartSequence("Main")]


def test_open_recipe_and_start_starts_the_sequence_it_names(gui):
    from pypts.messages.core_hmi_communication import StartSequence

    instance, outbox, inbox = gui

    instance.open_recipe_and_start("bench.yml", "Extra")
    drain(outbox)
    load_demo_recipe(instance, inbox)

    assert drain(outbox) == [StartSequence("Extra")]
    assert instance.top_bar.sequence_combo.currentText() == "Extra"


def test_open_recipe_and_start_refuses_a_sequence_the_recipe_does_not_have(gui):
    from pypts.messages.common_messages import ModuleError
    from pypts.messages.core_hmi_communication import StartSequence

    instance, outbox, inbox = gui

    instance.open_recipe_and_start("bench.yml", "Nope")
    drain(outbox)
    load_demo_recipe(instance, inbox)

    sent = drain(outbox)
    assert not [message for message in sent if isinstance(message, StartSequence)]
    errors = [message for message in sent if isinstance(message, ModuleError)]
    assert len(errors) == 1
    assert "Nope" in errors[0].message


def test_another_open_cancels_a_pending_start(gui):
    from pypts.messages.core_hmi_communication import StartSequence

    instance, outbox, inbox = gui

    instance.open_recipe_and_start("bench.yml")
    instance.open_recipe("other.yml")
    drain(outbox)
    load_demo_recipe(instance, inbox)

    assert not [message for message in drain(outbox) if isinstance(message, StartSequence)]


def test_a_start_happens_once_not_on_every_later_load(gui):
    from pypts.messages.core_hmi_communication import StartSequence

    instance, outbox, inbox = gui

    instance.open_recipe_and_start("bench.yml")
    load_demo_recipe(instance, inbox)
    drain(outbox)
    load_demo_recipe(instance, inbox)

    assert not [message for message in drain(outbox) if isinstance(message, StartSequence)]


def test_the_file_menu_cannot_open_a_recipe_during_a_run(inbox_run_started):
    """The toolbar button is not the only way in: File -> Open Recipe and
    File -> Open Recent would repaint the step table under the running sequence."""
    instance, _outbox, _inbox = inbox_run_started

    assert instance.window.open_recipe_action.isEnabled() is False
    assert instance.window.recent_menu.menuAction().isEnabled() is False


def test_the_file_menu_can_open_a_recipe_again_when_the_run_finishes(inbox_run_started):
    instance, _outbox, inbox = inbox_run_started

    inbox.send(RunFinished(result=ResultType.PASS, outcomes=()))
    instance.poll_core()

    assert instance.window.open_recipe_action.isEnabled() is True
    assert instance.window.recent_menu.menuAction().isEnabled() is True


@pytest.fixture
def inbox_run_started(gui):
    instance, outbox, inbox = gui
    inbox.send(RunStarted(recipe_name="demo", recipe_description="d"))
    instance.poll_core()
    return instance, outbox, inbox


def test_switching_theme_repaints_the_verdicts(gui):
    """The chips are set per item, so no stylesheet can restyle them: the step
    table has to repaint them itself or the run keeps the old theme's colours."""
    from PySide6.QtGui import QColor

    from pypts.hmi.gui.palette import DARK

    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    step = event.sequences[0].steps[0]
    inbox.send(
        StepFinished(
            outcome=StepOutcome(
                step_id=step.step_id, step_name=step.step_name,
                result=ResultType.FAIL, error_info="it broke",
            )
        )
    )
    instance.poll_core()

    instance._apply_theme(True)

    cell = instance.step_table.table.item(0, 2)
    assert cell.background().color() == QColor(DARK.verdicts["FAIL"].background)
    assert cell.foreground().color() == QColor(DARK.verdicts["FAIL"].text)
    # The tooltip survives the repaint - it carries the failure text.
    assert cell.toolTip() == "it broke"


def a_measured_outcome(step_id=None, result=ResultType.PASS):
    from uuid import uuid4

    return StepOutcome(
        step_id=step_id or uuid4(),
        step_name="Measure voltage",
        result=result,
        inputs=(("channel", "1"),),
        outputs=(("voltage", "12.1"),),
        expectations=(("voltage", "range 11 .. 13"),),
    )


def test_a_passing_rows_tooltip_lists_its_values(gui):
    """M-3: a PASS row says what was measured, not only a FAIL row."""
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    step = event.sequences[0].steps[0]

    inbox.send(StepFinished(outcome=a_measured_outcome(step.step_id)))
    instance.poll_core()

    tooltip = instance.step_table.table.item(0, 2).toolTip()
    assert tooltip == "inputs: channel = 1\noutputs: voltage = 12.1 (range 11 .. 13)"


def test_the_results_tree_opens_each_step_into_its_values(qapp):
    from PySide6.QtCore import QModelIndex, Qt

    from pypts.hmi.gui.results_panel import StepResultModel

    model = StepResultModel((a_measured_outcome(),))

    step_row = model.index(0, 0)
    assert model.data(step_row) == "Measure voltage"
    assert model.data(model.index(0, 1)) == "PASS"
    assert model.rowCount(step_row) == 2

    inputs_group = model.index(0, 0, step_row)
    outputs_group = model.index(1, 0, step_row)
    assert model.data(inputs_group) == "Inputs"
    assert model.data(outputs_group) == "Outputs"
    assert model.data(model.index(0, 0, inputs_group)) == "channel = 1"

    voltage = model.index(0, 0, outputs_group)
    assert model.data(voltage) == "voltage = 12.1"
    assert model.data(model.index(0, 2, outputs_group)) == "range 11 .. 13"
    # A value row has no verdict chip, and walks back up to its step.
    assert model.data(model.index(0, 1, outputs_group)) == ""
    assert model.data(model.index(0, 1, outputs_group), Qt.BackgroundRole) is None
    assert model.parent(voltage) == outputs_group
    assert model.parent(outputs_group) == step_row
    assert model.parent(step_row) == QModelIndex()


def test_a_step_with_no_values_has_no_groups(qapp):
    from uuid import uuid4

    from pypts.hmi.gui.results_panel import StepResultModel

    model = StepResultModel(
        (StepOutcome(step_id=uuid4(), step_name="Wait", result=ResultType.DONE),)
    )

    assert model.rowCount(model.index(0, 0)) == 0


def test_pending_rows_are_repainted_too(gui):
    """A theme switch before a run must not leave the Pending column behind."""
    from PySide6.QtGui import QColor

    from pypts.hmi.gui.palette import DARK

    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)

    instance._apply_theme(True)

    cell = instance.step_table.table.item(0, 2)
    assert cell.text() == "Pending"
    assert cell.background().color() == QColor(DARK.verdicts["PENDING"].background)


def test_the_log_panel_redraws_its_backlog_on_a_theme_change(gui):
    """Lines already on screen keep the QTextCharFormat they were written with,
    so without a redraw the whole backlog stays in the old theme's grey."""
    instance, _outbox, _inbox = gui
    panel = instance.center.log_panel
    panel.append_line("INFO      12:04:31  Recipe loaded.")
    panel.append_line("plain continuation line")

    instance._apply_theme(True)

    # Same text, redrawn - not cleared, not duplicated.
    shown = panel.toPlainText()
    assert shown.count("Recipe loaded.") == 1
    assert "plain continuation line" in shown


# --------------------------------------------------------------------------
# Top bar descriptions
# --------------------------------------------------------------------------


def test_every_top_bar_control_describes_itself(gui):
    """Tooltip and the accessible pair, on all five controls plus the combo."""
    instance, _outbox, _inbox = gui
    top = instance.top_bar

    controls = (
        top.open_button,
        top.start_button,
        top.pause_button,
        top.stop_button,
        top.report_button,
        top.sequence_combo,
    )
    for control in controls:
        assert control.toolTip() != ""
        assert control.accessibleName() != ""
        assert control.accessibleDescription() != ""


def test_a_disabled_control_says_why_it_is_disabled(gui):
    """The greyed button nobody can explain is the one that gets filed as a bug."""
    instance, _outbox, _inbox = gui
    top = instance.top_bar

    assert top.start_button.isEnabled() is False
    assert "Open a recipe first" in top.start_button.toolTip()
    assert "Open a recipe first" in top.sequence_combo.toolTip()
    assert "Nothing is running" in top.stop_button.toolTip()


def test_loading_a_recipe_rewrites_the_start_description(gui, inbox_recipe_loaded):
    instance, _outbox, _inbox = inbox_recipe_loaded

    assert instance.top_bar.start_button.isEnabled() is True
    assert "Run the selected sequence" in instance.top_bar.start_button.toolTip()


@pytest.fixture
def inbox_recipe_loaded(gui):
    instance, outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    return instance, outbox, inbox


def test_during_a_run_open_says_it_must_wait(gui, inbox_run_started):
    instance, _outbox, _inbox = inbox_run_started

    assert "stop the run first" in instance.top_bar.open_button.toolTip()
    assert "A run is already in progress" in instance.top_bar.start_button.toolTip()


# --------------------------------------------------------------------------
# Pause and Resume (gui.md section 13)
# --------------------------------------------------------------------------


def test_clicking_pause_asks_the_engine_and_says_it_is_pausing(gui, inbox_run_started):
    """The hold begins only when the current step ends, so the window has to
    say something is coming - and Start already resumes, which is also how a
    pause that has not begun is cancelled."""
    instance, outbox, _inbox = inbox_run_started
    top = instance.top_bar
    drain(outbox)
    assert top.pause_button.isEnabled() is True
    assert top.start_button.isEnabled() is False
    assert "current step has finished" in top.pause_button.toolTip()

    top.pause_button.click()

    assert PauseSequence() in drain(outbox)
    assert top.pause_button.isEnabled() is False
    assert top.start_button.isEnabled() is True
    assert top.start_button.accessibleName() == "Resume"
    assert "Continue the run" in top.start_button.toolTip()
    assert "Start resumes it" in top.pause_button.toolTip()
    assert instance.window.recipe_label.text() == "Pausing after the current step..."
    assert instance.status_label.text() == "Status: Pausing"


def test_run_paused_names_the_step_the_run_is_held_before(gui, inbox_run_started):
    instance, _outbox, inbox = inbox_run_started
    instance.top_bar.pause_button.click()

    inbox.send(RunPaused(step_name="measure", position=4, total=10))
    instance.poll_core()

    assert instance.window.recipe_label.text() == "Paused before step 4/10 'measure'"
    assert instance.status_label.text() == "Status: Paused"
    assert instance.top_bar.pause_button.isEnabled() is False
    assert instance.top_bar.start_button.accessibleName() == "Resume"


def test_clicking_start_while_paused_resumes_and_shows_the_run_moving(gui, inbox_run_started):
    """Resume does not wait for a confirmation before the label changes: a
    cancelled pause that never began gets no RunResumed at all."""
    instance, outbox, inbox = inbox_run_started
    top = instance.top_bar
    top.pause_button.click()
    inbox.send(RunPaused(step_name="measure", position=4, total=10))
    instance.poll_core()
    drain(outbox)

    top.start_button.click()

    # Resume, never a second StartSequence.
    assert drain(outbox) == [ResumeSequence()]
    assert top.pause_button.isEnabled() is True
    assert top.start_button.isEnabled() is False
    assert top.start_button.accessibleName() == "Start"
    assert instance.window.recipe_label.text() == "Running demo..."
    assert instance.status_label.text() == "Status: Running"


def test_run_resumed_puts_the_running_label_and_the_pause_button_back(gui, inbox_run_started):
    """A RunPaused that crosses a Resume click leaves "Paused..." showing; the
    RunResumed the engine sends for that hold is what corrects it."""
    instance, _outbox, inbox = inbox_run_started
    instance.top_bar.pause_button.click()
    instance.top_bar.start_button.click()
    inbox.send(RunPaused(step_name="measure", position=4, total=10))
    instance.poll_core()

    inbox.send(RunResumed())
    instance.poll_core()

    assert instance.window.recipe_label.text() == "Running demo..."
    assert instance.top_bar.pause_button.isEnabled() is True
    assert instance.top_bar.start_button.isEnabled() is False


def test_a_finished_run_forgets_it_was_paused(gui, inbox_run_started):
    """A pause that lapsed gets no RunPaused - only the RunFinished."""
    instance, _outbox, inbox = inbox_run_started
    instance.top_bar.pause_button.click()

    inbox.send(RunFinished(result=ResultType.PASS, outcomes=()))
    instance.poll_core()

    top = instance.top_bar
    assert instance._pause_requested is False
    assert top.pause_button.isEnabled() is False
    assert top.start_button.isEnabled() is True
    assert top.start_button.accessibleName() == "Start"
    assert instance.window.recipe_label.text() == "Done - demo: PASS\nno steps ran"


def an_outcome(result):
    return StepOutcome(step_id=uuid4(), step_name="step", result=result)


def test_a_finished_run_leaves_its_summary_above_the_table(gui, inbox_run_started):
    instance, _outbox, inbox = inbox_run_started
    outcomes = (
        an_outcome(ResultType.PASS),
        an_outcome(ResultType.PASS),
        an_outcome(ResultType.FAIL),
        an_outcome(ResultType.SKIP),
    )

    inbox.send(RunFinished(result=ResultType.FAIL, outcomes=outcomes))
    instance.poll_core()

    assert instance.window.recipe_label.text() == (
        "Done - demo: FAIL\n4 steps: 2 PASS, 1 FAIL, 1 SKIP"
    )
    assert instance.status_label.text() == "Status: Finished"


def test_a_run_stopped_while_paused_shows_its_summary_not_running(gui, inbox_run_started):
    """Stop during a hold sends RunResumed, then RunFinished(STOP); the label
    must end on the summary, not on the "Running..." the RunResumed put back."""
    instance, _outbox, inbox = inbox_run_started
    instance.top_bar.pause_button.click()
    inbox.send(RunPaused(step_name="measure", position=2, total=3))
    inbox.send(RunResumed())
    inbox.send(RunFinished(result=ResultType.STOP, outcomes=(an_outcome(ResultType.PASS),)))
    instance.poll_core()

    assert instance.window.recipe_label.text() == "Stopped - demo\n1 step: 1 PASS"
    assert instance.status_label.text() == "Status: Stopped"


def test_the_report_status_line_does_not_hide_the_run_state(gui, inbox_run_started):
    """CORE sends "Report generated: <path>" and then ReportReady, right after
    RunFinished; the status bar goes back to how the run ended."""
    from pypts.messages.core_hmi_communication import ReportReady

    instance, _outbox, inbox = inbox_run_started
    inbox.send(RunFinished(result=ResultType.PASS, outcomes=(an_outcome(ResultType.PASS),)))
    inbox.send(StatusChanged(text="Report generated: C:/r/report.html"))
    inbox.send(ReportReady(report_path="C:/r/report.html", report_dir="C:/r"))
    instance.poll_core()

    assert instance.status_label.text() == "Status: Finished"
    assert instance.window.recipe_label.text() == "Done - demo: PASS\n1 step: 1 PASS"


def test_a_new_run_starts_unpaused(gui, inbox_run_started):
    instance, outbox, inbox = inbox_run_started
    instance.top_bar.pause_button.click()
    inbox.send(RunPaused(step_name="measure", position=4, total=10))
    instance.poll_core()

    inbox.send(RunStarted(recipe_name="second", recipe_description="d"))
    instance.poll_core()
    drain(outbox)

    assert instance.top_bar.pause_button.accessibleName() == "Pause"
    assert instance.window.recipe_label.text() == "Running second..."
    # Unpaused for real: the next click pauses rather than resumes.
    instance.top_bar.pause_button.click()
    assert drain(outbox) == [PauseSequence()]


def test_stop_still_works_while_the_run_is_pausing(gui, inbox_run_started):
    instance, outbox, _inbox = inbox_run_started
    instance.top_bar.pause_button.click()
    drain(outbox)

    assert instance.top_bar.stop_button.isEnabled() is True
    instance.top_bar.stop_button.click()

    assert drain(outbox) == [StopSequence()]


def test_a_prompt_stays_answerable_while_the_run_is_pausing(gui, inbox_run_started):
    """The step running when Pause is pressed may be this very question, and
    the hold cannot begin until it is answered - so nothing may block it."""
    from PySide6.QtCore import Qt

    instance, outbox, _inbox = inbox_run_started
    instance.top_bar.pause_button.click()
    request = UserPromptRequest(request_id=uuid4(), message="Connect the DUT", options=("ok",))

    instance.ask_user(request)

    interaction = instance.center.interaction
    for row in (interaction._button_row, interaction._text_row, interaction._path_page):
        assert not row.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    for button in instance.center.option_buttons:
        assert not button.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    drain(outbox)
    instance.center.option_buttons[0].click()
    assert drain(outbox) == [UserPromptResponse(request_id=request.request_id, choice="ok")]


def test_the_toolbar_answers_tooltips_for_disabled_buttons(gui, qapp):
    """Qt gives a disabled widget no mouse events, so the toolbar answers instead."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QHelpEvent

    instance, _outbox, _inbox = gui
    top = instance.top_bar
    assert top.start_button.isEnabled() is False

    # Widgets in an unshown window have no laid-out geometry, and childAt()
    # needs real coordinates.
    instance.window.show()
    qapp.processEvents()
    centre = top.start_button.mapTo(top, top.start_button.rect().center())

    # tooltip_at() is the branch worth asserting: event() cannot be, because the
    # base QWidget accepts a ToolTip event either way.
    assert "Open a recipe first" in top.tooltip_at(centre)

    # Nothing to say there: no text, so event() falls through to the base class.
    top.start_button.setToolTip("")
    assert top.tooltip_at(centre) == ""

    # And the handler itself runs without raising on a real event.
    top.setToolTip("")
    top.event(QHelpEvent(QEvent.Type.ToolTip, centre, top.mapToGlobal(centre)))


# --- The step table's YAML click panel ----------------------------------------
#
# What the operator gets between runs: a click on a step's name or description,
# and the whole sequence that step is in beside the pointer, the step picked out.
# The sources themselves are the recipe layer's (step_source.py, covered in
# test_recipe.py); these tests own the wiring, the idle gate, the gesture, the
# row highlight and the theme.


A_FRAGMENT = "steptype: Wait\nstep_name: First wait\nwait_time: '0.01'"

#: A sequence document long enough to scroll, its second step on lines 40-42.
A_LONG_SEQUENCE = "\n".join(
    ["sequence_name: Main", "steps:"]
    + [f"  # filler {n}" for n in range(38)]
    + ["  - steptype: Wait", "    step_name: Deep step", "    wait_time: '0'"]
    + [f"  # tail {n}" for n in range(60)]
)


def a_source(text=A_FRAGMENT, first_line=0, last_line=2):
    from pypts.recipe.step_source import StepSource

    return StepSource(text=text, first_line=first_line, last_line=last_line)


def a_table_with_yaml(qapp):
    """A step table filled from a sequence, every row carrying a source."""
    from pypts.hmi.gui.step_table import StepTableContent

    content = StepTableContent()
    sequence = a_recipe_loaded().sequences[0]
    sources = tuple(
        a_source(f"{A_FRAGMENT}\n# row {row}", 0, 2) for row in range(len(sequence.steps))
    )
    content.show_sequence(sequence, sources)
    return content, sources


def band_lines(popup):
    """The block numbers the panel's step band covers."""
    return sorted({s.cursor.blockNumber() for s in popup.text_view.extraSelections()})


def test_each_row_carries_its_own_source(qapp):
    from pypts.hmi.gui.step_table import _YAML_ROLE

    content, sources = a_table_with_yaml(qapp)

    stored = [
        content.table.item(row, 0).data(_YAML_ROLE)
        for row in range(content.table.rowCount())
    ]
    assert stored == list(sources)


def test_a_sequence_without_sources_still_fills_the_table(qapp):
    """A recipe the GUI could not read back off disk costs the panel, not the
    table - show_sequence's second argument is optional on purpose."""
    from pypts.hmi.gui.step_table import _YAML_ROLE, StepTableContent

    content = StepTableContent()
    content.show_sequence(a_recipe_loaded().sequences[0])

    assert content.table.rowCount() == 2
    assert content.table.item(0, 0).data(_YAML_ROLE) is None

    content._clicked_cell(0, 0)
    assert content.yaml_popup.isVisible() is False


def test_clicking_a_row_shows_its_sequence_with_the_step_picked_out(qapp):
    content, sources = a_table_with_yaml(qapp)

    content._clicked_cell(1, 0)

    assert content.yaml_popup.isVisible() is True
    assert content.yaml_popup.text_view.toPlainText() == sources[1].text
    assert band_lines(content.yaml_popup) == [0, 1, 2]
    content.hide_yaml_popup()


def test_the_description_opens_the_panel_too_and_the_result_does_not(qapp):
    """The two prose columns are the affordance; the Result column is a verdict
    with its own tooltip, and a click there dismisses instead."""
    content, _sources = a_table_with_yaml(qapp)

    content._clicked_cell(0, 1)
    assert content.yaml_popup.isVisible() is True

    content._clicked_cell(0, 2)
    assert content.yaml_popup.isVisible() is False


def test_nothing_opens_without_a_click(qapp):
    """Moving the pointer over the table shows nothing: the panel opens on a
    click, never on a crossing."""
    from PySide6.QtCore import QPoint

    content, _sources = a_table_with_yaml(qapp)

    content.pointer_moved_to(QPoint(5, 5))

    assert content.yaml_popup.isVisible() is False


def test_the_clicked_row_is_highlighted_and_the_verdict_chip_is_not(qapp):
    """The row goes the row-number column's blue - but only the two prose
    cells, so a PASS chip keeps the colour the palette gave it."""
    from pypts.hmi.gui.palette import get_palette

    content, _sources = a_table_with_yaml(qapp)
    chip_before = content.table.item(0, 2).background().color().name()

    content._clicked_cell(0, 0)

    tint = get_palette(False).header_background.lower()
    assert content.table.item(0, 0).background().color().name().lower() == tint
    assert content.table.item(0, 1).background().color().name().lower() == tint
    assert content.table.item(0, 2).background().color().name() == chip_before
    content.hide_yaml_popup()


def shown_table_with_yaml(qapp):
    """A table on screen, so its cells have global geometry, row 0 clicked."""
    content, sources = a_table_with_yaml(qapp)
    content.resize(600, 300)
    content.show()
    qapp.processEvents()
    content._clicked_cell(0, 0)
    return content, sources


def global_centre_of(content, row, column):
    item = content.table.item(row, column)
    cell = content.table.visualItemRect(item)
    return content.table.viewport().mapToGlobal(cell.center())


def test_the_panel_stays_while_the_pointer_is_on_the_clicked_row(qapp):
    """Name to description is still the same field: one step, one panel."""
    content, _sources = shown_table_with_yaml(qapp)

    content.pointer_moved_to(global_centre_of(content, 0, 1))

    assert content.yaml_popup.isVisible() is True
    content.hide()
    content.hide_yaml_popup()


def test_the_panel_stays_while_the_pointer_is_on_the_panel(qapp):
    """Moving onto the panel is how its text gets scrolled with the wheel."""
    content, _sources = shown_table_with_yaml(qapp)

    content.pointer_moved_to(content.yaml_popup.frameGeometry().center())

    assert content.yaml_popup.isVisible() is True
    content.hide()
    content.hide_yaml_popup()


def test_moving_to_another_row_hides_the_panel_and_the_highlight(qapp):
    """Reading down the table does not drag the panel along."""
    from PySide6.QtCore import Qt

    content, _sources = shown_table_with_yaml(qapp)
    far_away = content.yaml_popup.frameGeometry().bottomRight()
    far_away.setX(far_away.x() + 500)
    far_away.setY(far_away.y() + 500)

    content.pointer_moved_to(far_away)

    assert content.yaml_popup.isVisible() is False
    assert content._active_row == -1
    assert content.table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush
    content.hide()


def test_hiding_the_panel_drops_the_highlight_and_stops_watching(qapp):
    """A tint left behind would mark a row for no reason once the panel is gone."""
    from PySide6.QtCore import Qt

    content, _sources = a_table_with_yaml(qapp)
    content._clicked_cell(0, 0)
    assert content._active_row == 0
    assert content._pointer_timer.isActive() is True

    content.hide_yaml_popup()

    assert content._active_row == -1
    assert content._pointer_timer.isActive() is False
    assert content.table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush


def test_the_panel_is_suppressed_while_a_recipe_runs(qapp):
    """The operator asked for it between runs: during one the table is being
    written to and read for verdicts, and must not be covered. A hold counts
    as running - set_running(False) only comes with RunFinished."""
    content, _sources = a_table_with_yaml(qapp)
    content._clicked_cell(0, 0)
    assert content.yaml_popup.isVisible() is True

    content.set_running(True)
    assert content.yaml_popup.isVisible() is False

    content._clicked_cell(1, 0)
    assert content.yaml_popup.isVisible() is False

    content.set_running(False)
    content._clicked_cell(1, 0)
    assert content.yaml_popup.isVisible() is True
    content.hide_yaml_popup()


def test_a_long_sequence_scrolls_to_the_clicked_step(qapp):
    """A whole sequence is taller than the panel may be: it scrolls, and opens
    with the clicked step in view rather than at the top of the document."""
    from PySide6.QtGui import QGuiApplication

    from pypts.hmi.gui.step_yaml_popup import _CONTEXT_LINES, StepYamlPopup

    popup = StepYamlPopup()
    area = QGuiApplication.primaryScreen().availableGeometry()
    popup.show_for(A_LONG_SEQUENCE, 40, 42, area.left() + 20, area.top() + 20)

    assert popup.text_view.toPlainText() == A_LONG_SEQUENCE
    assert popup.height() <= area.height()
    assert band_lines(popup) == [40, 41, 42]
    bar = popup.text_view.verticalScrollBar()
    if bar.maximum() > 0:
        assert bar.value() == min(40 - _CONTEXT_LINES, bar.maximum())
    popup.hide()


def test_a_whole_sequence_shows_with_nothing_picked_out_from_the_top(qapp):
    """A call's row shows the sequence it calls: no band, and the top of it."""
    from pypts.hmi.gui.step_yaml_popup import StepYamlPopup

    popup = StepYamlPopup()
    popup.show_for(A_LONG_SEQUENCE, -1, -1, 20, 20)

    assert popup.isVisible() is True
    assert popup.text_view.extraSelections() == []
    assert popup.text_view.verticalScrollBar().value() == 0
    popup.hide()


def test_an_empty_text_shows_nothing(qapp):
    from pypts.hmi.gui.step_yaml_popup import StepYamlPopup

    popup = StepYamlPopup()
    popup.show_for("   \n  ", 0, 0, 10, 10)

    assert popup.isVisible() is False


def test_switching_theme_recolours_the_yaml_and_the_step_band(qapp):
    """Syntax colours and the band are per-character and per-line formats, which
    no stylesheet can reach - the same contract the log panel's backlog has."""
    from pypts.hmi.gui.palette import DARK, LIGHT
    from pypts.hmi.gui.step_yaml_popup import StepYamlPopup

    popup = StepYamlPopup()
    popup.show_for(A_FRAGMENT, 1, 1, 10, 10)

    def key_colour():
        # Every step held in a local: a highlighter's formats hang off the
        # block's layout, and reading through a chain of temporaries lets
        # PySide free the QTextCharFormat before the colour is read off it.
        block = popup.text_view.document().firstBlock()
        layout = block.layout()
        ranges = layout.formats()
        return ranges[0].format.foreground().color().name()

    def band_colour():
        selection = popup.text_view.extraSelections()[0]
        return selection.format.background().color().name()

    assert key_colour().lower() == LIGHT.yaml_key.lower()
    assert band_colour().lower() == LIGHT.yaml_step_highlight.lower()

    popup.set_dark(True)
    assert key_colour().lower() == DARK.yaml_key.lower()
    assert band_colour().lower() == DARK.yaml_step_highlight.lower()
    popup.hide()


def test_the_step_table_carries_the_theme_into_the_panel(qapp):
    content, _sources = a_table_with_yaml(qapp)

    content.set_dark(True)

    assert content.yaml_popup._dark is True


def test_the_gui_reads_the_recipe_back_for_the_click_panel(gui, tmp_path, monkeypatch):
    """The assembler's half: the path it asked CORE to open is the path it
    reads the sources from, once, when the recipe loads."""
    from pypts.hmi.gui import gui as gui_module
    from pypts.hmi.gui.step_table import _YAML_ROLE

    asked = []
    first = a_source("sequence_name: Main\nsteps: []", 1, 1)

    def fake_sources(path):
        asked.append(path)
        return {"Main": (first, a_source())}

    monkeypatch.setattr(gui_module.step_source, "step_sources_by_sequence", fake_sources)

    instance, _outbox, inbox = gui
    instance._requested_recipe_path = str(tmp_path / "demo.yml")
    load_demo_recipe(instance, inbox)

    assert asked == [str(tmp_path / "demo.yml")]
    table = instance.step_table.table
    assert table.item(0, 0).data(_YAML_ROLE) == first


def test_the_preview_button_is_greyed_until_a_recipe_can_be_shown(gui):
    instance, _outbox, _inbox = gui
    button = instance.top_bar.preview_button

    assert button.isEnabled() is False
    assert "Open a recipe first" in button.toolTip()

    instance.top_bar.set_preview_available(True)

    assert button.isEnabled() is True
    assert "Click anywhere outside it to close it" in button.toolTip()


def test_the_preview_button_shows_the_whole_recipe_in_a_popup(gui, tmp_path, monkeypatch):
    """The whole file, as written, in a Qt.Popup window - which Qt itself closes
    on a click outside it, so nothing in pypts has to watch for that click."""
    from PySide6.QtCore import Qt

    from pypts.hmi.gui import gui as gui_module

    recipe_text = "name: Wait demo\nversion: 0.2\n---\nsequence_name: Main\nsteps: []\n"
    monkeypatch.setattr(gui_module.step_source, "step_sources_by_sequence", lambda path: {})
    monkeypatch.setattr(gui_module.step_source, "recipe_file_text", lambda path: recipe_text)

    instance, _outbox, inbox = gui
    instance._requested_recipe_path = str(tmp_path / "demo.yml")
    load_demo_recipe(instance, inbox)
    assert instance.top_bar.preview_button.isEnabled() is True

    instance.top_bar.preview_button.click()

    preview = instance.recipe_preview
    assert preview.isVisible() is True
    assert preview.text_view.toPlainText() == recipe_text
    assert preview.text_view.extraSelections() == []
    assert preview.windowType() == Qt.WindowType.Popup
    preview.hide()


def test_a_recipe_that_cannot_be_read_back_has_no_preview(gui, tmp_path, monkeypatch):
    from pypts.hmi.gui import gui as gui_module

    monkeypatch.setattr(gui_module.step_source, "step_sources_by_sequence", lambda path: {})
    monkeypatch.setattr(gui_module.step_source, "recipe_file_text", lambda path: "")

    instance, _outbox, inbox = gui
    instance._requested_recipe_path = str(tmp_path / "demo.yml")
    load_demo_recipe(instance, inbox)

    assert instance.top_bar.preview_button.isEnabled() is False
    instance.show_recipe_preview()
    assert instance.recipe_preview.isVisible() is False


def test_the_theme_reaches_the_recipe_preview(gui):
    instance, _outbox, _inbox = gui

    instance._apply_theme(True)

    assert instance.recipe_preview._dark is True


def test_a_run_turns_the_hover_panel_off_and_the_end_of_it_back_on(gui):
    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    assert instance.step_table._running is False

    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()
    assert instance.step_table._running is True

    inbox.send(RunFinished(result=ResultType.PASS, outcomes=()))
    instance.poll_core()
    assert instance.step_table._running is False


# --- Folding groups in the step table -----------------------------------------
#
# A row that stands for a called sequence folds the rows under it away. The rows
# are only hidden, never removed, so everything keyed by step id keeps working.


def a_nested_sequence():
    """Main: a step, a group holding a step and a nested group, then a step.

    Rows, depth-first as Sequence.to_summary() sends them:
        0 Warm up          depth 0
        1 PowerCycle       depth 0, group
        2 Power off        depth 1
        3 Settle           depth 1, group
        4 Settle time      depth 2
        5 Power on         depth 1
        6 Final check      depth 0
    """
    rows = (
        ("Warm up", 0, False),
        ("PowerCycle", 0, True),
        ("Power off", 1, False),
        ("Settle", 1, True),
        ("Settle time", 2, False),
        ("Power on", 1, False),
        ("Final check", 0, False),
    )
    steps = tuple(
        StepSummary(
            step_id=uuid4(), step_name=name, description=f"About {name}.",
            depth=depth, is_group=is_group,
        )
        for name, depth, is_group in rows
    )
    return SequenceSummary(sequence_name="Main", steps=steps)


def a_folding_table(qapp):
    from pypts.hmi.gui.step_table import StepTableContent

    content = StepTableContent()
    sequence = a_nested_sequence()
    content.show_sequence(sequence)
    return content, sequence


def visible_rows(content):
    return [row for row in range(content.table.rowCount()) if not content.table.isRowHidden(row)]


def test_groups_start_folded_with_an_arrow_and_indented_steps(qapp):
    content, _sequence = a_folding_table(qapp)

    assert visible_rows(content) == [0, 1, 6]
    names = [content.table.item(row, 0).text() for row in range(7)]
    assert names[0] == "Warm up"
    assert names[1] == "\u25b8 PowerCycle"
    assert names[2] == "    Power off"
    assert names[3] == "    \u25b8 Settle"
    assert names[4] == "        Settle time"


def test_clicking_a_group_name_unfolds_one_level(qapp):
    """Settle stays folded inside PowerCycle until it is opened itself."""
    content, _sequence = a_folding_table(qapp)

    content._clicked_cell(1, 0)

    assert visible_rows(content) == [0, 1, 2, 3, 5, 6]
    assert content.table.item(1, 0).text() == "\u25be PowerCycle"
    assert content.yaml_popup.isVisible() is False

    content._clicked_cell(3, 0)
    assert visible_rows(content) == [0, 1, 2, 3, 4, 5, 6]

    content._clicked_cell(1, 0)
    assert visible_rows(content) == [0, 1, 6]


def test_folding_an_outer_group_keeps_what_was_open_inside_it(qapp):
    content, _sequence = a_folding_table(qapp)
    content.set_expanded(1, True)
    content.set_expanded(3, True)

    content.set_expanded(1, False)
    content.set_expanded(1, True)

    assert visible_rows(content) == [0, 1, 2, 3, 4, 5, 6]


def test_a_double_click_toggles_a_group_once(qapp):
    """A double-click arrives as a click and then a double-click: on the name the
    click toggled already; on the description the double-click does it."""
    content, _sequence = a_folding_table(qapp)

    content._clicked_cell(1, 0)
    content._double_clicked_cell(1, 0)
    assert content.is_expanded(1) is True

    content._clicked_cell(1, 1)
    content._double_clicked_cell(1, 1)
    assert content.is_expanded(1) is False


def test_the_description_of_a_group_still_opens_the_panel(qapp):
    from pypts.hmi.gui.step_table import StepTableContent
    from pypts.recipe.step_source import StepSource

    content = StepTableContent()
    sequence = a_nested_sequence()
    sources = tuple(
        StepSource(text=f"sequence_name: row {row}", first_line=-1, last_line=-1)
        for row in range(len(sequence.steps))
    )
    content.show_sequence(sequence, sources)

    content._clicked_cell(1, 1)

    assert content.yaml_popup.isVisible() is True
    assert content.is_expanded(1) is False
    content.hide_yaml_popup()


def test_expand_all_and_collapse_all(qapp):
    content, _sequence = a_folding_table(qapp)

    content.expand_all()
    assert visible_rows(content) == list(range(7))
    assert content.table.item(3, 0).text() == "    \u25be Settle"

    content.collapse_all()
    assert visible_rows(content) == [0, 1, 6]


def test_a_step_that_is_not_a_group_does_not_fold(qapp):
    content, _sequence = a_folding_table(qapp)

    content.set_expanded(0, True)

    assert content.is_expanded(0) is False
    assert visible_rows(content) == [0, 1, 6]


def test_a_folded_step_still_gets_its_verdict(qapp):
    """Hidden, not removed: the row is found by step id and updated as ever, and
    unfolding shows the verdict it already has."""
    content, sequence = a_folding_table(qapp)
    inner = sequence.steps[4]

    content.mark_running(StepStarted(step_id=inner.step_id, step_name=inner.step_name))
    content.show_outcome(
        StepOutcome(step_id=inner.step_id, step_name=inner.step_name, result=ResultType.PASS)
    )

    assert content.table.isRowHidden(4) is True
    assert content.table.item(4, 2).text() == "PASS"
    assert content.is_expanded(1) is False
    content.expand_all()
    assert content.table.item(4, 2).text() == "PASS"


def test_a_run_does_not_unfold_anything(qapp):
    content, sequence = a_folding_table(qapp)
    content.set_running(True)
    inner = sequence.steps[2]

    content.mark_running(StepStarted(step_id=inner.step_id, step_name=inner.step_name))

    assert visible_rows(content) == [0, 1, 6]
    assert content._visible_row_for(4) == 1


def test_groups_can_be_folded_during_a_run(qapp):
    content, _sequence = a_folding_table(qapp)
    content.set_running(True)

    content._clicked_cell(1, 0)

    assert content.is_expanded(1) is True


def test_a_new_sequence_starts_folded_again(qapp):
    content, sequence = a_folding_table(qapp)
    content.expand_all()

    content.show_sequence(sequence)

    assert visible_rows(content) == [0, 1, 6]


def test_folding_away_the_row_the_panel_is_open_on_closes_the_panel(qapp):
    from pypts.hmi.gui.step_table import StepTableContent
    from pypts.recipe.step_source import StepSource

    content = StepTableContent()
    sequence = a_nested_sequence()
    sources = tuple(
        StepSource(text=f"sequence_name: row {row}", first_line=0, last_line=0)
        for row in range(len(sequence.steps))
    )
    content.show_sequence(sequence, sources)
    content.expand_all()
    content._clicked_cell(2, 0)
    assert content.yaml_popup.isVisible() is True

    content.set_expanded(1, False)

    assert content.yaml_popup.isVisible() is False


# --- File > Open Config -------------------------------------------------------


def test_open_config_hands_the_file_to_the_default_editor(gui, tmp_path, monkeypatch):
    """The operator edits config.ini in whatever this machine opens an .ini with;
    pypts never opens an editor itself."""
    from PySide6.QtGui import QDesktopServices

    config_file = tmp_path / "config.ini"
    config_file.write_text("[meta]\n", encoding="utf-8")
    monkeypatch.setattr(file_locations, "config_file_path", lambda: config_file)

    opened = []

    def record(url):
        opened.append(url)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", record)

    instance, outbox, _inbox = gui
    instance.window.open_config_action.trigger()

    assert [Path(url.toLocalFile()) for url in opened] == [config_file]
    assert drain(outbox) == []


def test_open_config_reports_a_missing_file_instead_of_failing(gui, tmp_path, monkeypatch):
    """Nothing to open is a warning to the operator, not a dead menu entry and
    not a window that goes down with it."""
    from PySide6.QtGui import QDesktopServices

    missing = tmp_path / "config.ini"
    monkeypatch.setattr(file_locations, "config_file_path", lambda: missing)
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda _url: pytest.fail("nothing to open")
    )

    instance, outbox, _inbox = gui
    instance.window.open_config_action.trigger()

    errors = [message for message in drain(outbox) if isinstance(message, ModuleError)]
    assert len(errors) == 1
    assert errors[0].severity is ErrorSeverity.WARNING
    assert errors[0].operation == "open_config_file"
    assert str(missing) in errors[0].message


# --- The About menu -----------------------------------------------------------


def test_the_about_menu_opens_the_project_urls(gui, monkeypatch):
    """Both entries were dead stubs with no connection at all; the GitLab one
    also named a repository the project has moved off."""
    from pypts.hmi.gui import gui as gui_module

    opened = []
    monkeypatch.setattr(gui_module, "open_external_url", opened.append)

    instance, _outbox, _inbox = gui
    window = instance.window

    assert window.repository_action.text() == "GitHub"
    window.repository_action.trigger()
    window.documentation_action.trigger()

    assert opened == [
        "https://github.com/CERN/pts-framework",
        "https://cern.github.io/pts-framework/",
    ]


def test_a_machine_with_no_browser_only_logs(qapp, monkeypatch, caplog):
    """openUrl returns False rather than raising, and the About menu is not
    part of running a recipe."""
    from PySide6.QtGui import QDesktopServices

    from pypts.hmi.gui.gui import open_external_url

    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _url: False)

    with caplog.at_level(logging.WARNING):
        open_external_url("https://example.invalid/")

    assert "no application set up to open https://example.invalid/" in caplog.text


def test_run_metadata_is_shown_in_the_top_bar(gui):
    """The operator can see which unit is on the bench without opening anything."""
    instance, _outbox, inbox = gui

    inbox.send(RunMetadata(values=(("serial_number", "SN-0042"),)))
    instance.poll_core()

    label = instance.top_bar.metadata_label
    assert "SN-0042" in label.text()
    assert label.isVisibleTo(instance.top_bar)


def test_a_new_recipe_clears_the_metadata_of_the_last_run(gui):
    """A different recipe describes a different unit."""
    instance, _outbox, inbox = gui
    inbox.send(RunMetadata(values=(("serial_number", "SN-0042"),)))
    instance.poll_core()

    instance.top_bar.show_recipe_loaded(
        RecipeLoaded(
            recipe_name="Another",
            recipe_version="1.0",
            main_sequence="Main",
            sequences=(),
        )
    )

    assert instance.top_bar.metadata_label.text() == ""
    assert not instance.top_bar.metadata_label.isVisibleTo(instance.top_bar)


# --------------------------------------------------------------------------
# The Run | Results tabs (gui.md section 14)
# --------------------------------------------------------------------------


def results_tree_rows(instance):
    return instance.window.results_panel.tree_view.model().rowCount()


def finish_a_step(instance, inbox, step):
    inbox.send(StepFinished(outcome=a_measured_outcome(step.step_id)))
    instance.poll_core()


def test_the_left_pane_opens_on_the_run_tab(gui):
    from pypts.hmi.gui.view_tabs import TAB_RUN

    instance, _outbox, _inbox = gui
    tabs = instance.window.view_tabs

    assert [tabs.tabText(index) for index in range(tabs.count())] == ["Run", "Results"]
    assert tabs.currentIndex() == TAB_RUN
    assert instance.window.left_stack.currentWidget() is instance.window.run_stack
    assert tabs.pulsing_tab() is None


def test_the_results_tab_shows_the_results_panel(gui):
    from pypts.hmi.gui.view_tabs import TAB_RESULTS, TAB_RUN

    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)

    instance.window.view_tabs.setCurrentIndex(TAB_RESULTS)
    assert instance.window.left_stack.currentWidget() is instance.window.results_panel

    instance.window.view_tabs.setCurrentIndex(TAB_RUN)
    assert instance.window.run_stack.currentWidget() is instance.step_table


def test_the_results_fill_live_after_every_step(gui):
    instance, _outbox, inbox = gui
    event = load_demo_recipe(instance, inbox)
    first, second = event.sequences[0].steps
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()

    finish_a_step(instance, inbox, first)
    assert results_tree_rows(instance) == 1
    finish_a_step(instance, inbox, second)
    assert results_tree_rows(instance) == 2
    # Live filling does not ask for attention; the end of the run does.
    assert instance.window.view_tabs.pulsing_tab() is None


def test_a_finished_run_pulses_the_results_tab_until_it_is_opened(gui):
    from pypts.hmi.gui.view_tabs import TAB_RESULTS, TAB_RUN

    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    inbox.send(RunFinished(result=ResultType.PASS, outcomes=(a_measured_outcome(),)))
    instance.poll_core()

    tabs = instance.window.view_tabs
    assert tabs.currentIndex() == TAB_RUN  # not switched to
    assert tabs.pulsing_tab() == TAB_RESULTS

    tabs.setCurrentIndex(TAB_RESULTS)
    assert tabs.pulsing_tab() is None


def test_a_run_finished_while_on_the_results_tab_does_not_pulse(gui):
    from pypts.hmi.gui.view_tabs import TAB_RESULTS

    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()
    instance.window.view_tabs.setCurrentIndex(TAB_RESULTS)

    inbox.send(RunFinished(result=ResultType.PASS, outcomes=(a_measured_outcome(),)))
    instance.poll_core()

    assert instance.window.view_tabs.pulsing_tab() is None


def test_a_run_with_no_results_does_not_pulse(gui):
    instance, _outbox, inbox = gui
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    inbox.send(RunFinished(result=ResultType.STOP, outcomes=()))
    instance.poll_core()

    assert instance.window.view_tabs.pulsing_tab() is None


def test_a_new_run_clears_the_results_stops_the_pulse_and_opens_run(gui):
    from pypts.hmi.gui.view_tabs import TAB_RESULTS, TAB_RUN

    instance, _outbox, inbox = gui
    load_demo_recipe(instance, inbox)
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    inbox.send(RunFinished(result=ResultType.PASS, outcomes=(a_measured_outcome(),)))
    instance.poll_core()
    assert results_tree_rows(instance) == 1
    assert instance.window.view_tabs.pulsing_tab() == TAB_RESULTS

    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    instance.poll_core()

    assert results_tree_rows(instance) == 0
    assert instance.window.view_tabs.pulsing_tab() is None
    assert instance.window.view_tabs.currentIndex() == TAB_RUN


def test_loading_a_recipe_or_choosing_a_sequence_opens_the_run_tab(gui):
    from pypts.hmi.gui.view_tabs import TAB_RESULTS, TAB_RUN

    instance, _outbox, inbox = gui
    tabs = instance.window.view_tabs

    tabs.setCurrentIndex(TAB_RESULTS)
    load_demo_recipe(instance, inbox)
    assert tabs.currentIndex() == TAB_RUN

    tabs.setCurrentIndex(TAB_RESULTS)
    instance.top_bar.sequence_combo.setCurrentText("Extra")
    assert tabs.currentIndex() == TAB_RUN
    assert instance.window.run_stack.currentWidget() is instance.step_table


def test_loading_a_recipe_keeps_the_last_results(gui):
    instance, _outbox, inbox = gui
    inbox.send(RunStarted(recipe_name="Wait demo", recipe_description=""))
    inbox.send(RunFinished(result=ResultType.PASS, outcomes=(a_measured_outcome(),)))
    instance.poll_core()

    load_demo_recipe(instance, inbox)

    assert results_tree_rows(instance) == 1
