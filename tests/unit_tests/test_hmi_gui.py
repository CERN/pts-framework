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

import logging
import queue
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


@pytest.fixture(autouse=True)
def isolated_recent_recipes(tmp_path, monkeypatch):
    """No GUI test may read or write the operator's real recent-recipes list."""
    monkeypatch.setattr(
        file_locations,
        "recent_recipes_path",
        lambda: tmp_path / "state" / "recent_recipes.json",
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
    # Cancel is appended to every prompt, after the recipe's own options, so
    # the operator is never stuck in front of a question they cannot answer.
    assert [b.text() for b in center.option_buttons] == ["yes", "no", "Cancel"]

    center.option_buttons[0].click()

    assert UserPromptResponse(request_id=request.request_id, choice="yes") in drain(outbox)
    assert center.stack.currentWidget() is center.idle_page


def test_the_cancel_button_declines_the_prompt(gui):
    """Cancel answers None, which the step that asked turns into an ERROR."""
    instance, outbox, _inbox = gui
    request = UserPromptRequest(
        request_id=uuid4(), message="Connect the DUT", options=("yes", "no")
    )

    instance.ask_user(request)
    instance.center.option_buttons[-1].click()

    assert UserPromptResponse(request_id=request.request_id, choice=None) in drain(outbox)
    assert instance.center.stack.currentWidget() is instance.center.idle_page


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


# --------------------------------------------------------------------------
# Remove Cache
# --------------------------------------------------------------------------


def an_item(key="state", label="Recent recipes", count=2, size=200, note=""):
    from pypts.utilities.data_removal import RemovableItem

    return RemovableItem(
        key=key,
        label=label,
        detail="Every run folder.",
        location="C:/pypts/reports",
        targets=(),
        size_bytes=size,
        item_count=count,
        kept_note=note,
    )


def test_remove_cache_is_available_when_idle(gui):
    instance, _outbox, _inbox = gui

    assert instance.window.remove_cache_action.isEnabled() is True


def test_remove_cache_is_greyed_out_during_a_run_and_says_why(inbox_run_started):
    """Emptying the reports folder under the Report thread would take the run down."""
    instance, _outbox, _inbox = inbox_run_started

    assert instance.window.remove_cache_action.isEnabled() is False
    assert "running" in instance.window.remove_cache_action.toolTip().lower()


def test_remove_cache_comes_back_when_the_run_finishes(inbox_run_started):
    instance, _outbox, inbox = inbox_run_started

    inbox.send(RunFinished(result=ResultType.PASS, outcomes=()))
    instance.poll_core()

    assert instance.window.remove_cache_action.isEnabled() is True


@pytest.fixture
def inbox_run_started(gui):
    instance, outbox, inbox = gui
    inbox.send(RunStarted(recipe_name="demo", recipe_description="d"))
    instance.poll_core()
    return instance, outbox, inbox


def four_items(**sizes):
    """The four real categories, so the default ticks can be asserted."""
    return [
        an_item(key="state", label="Recent recipes", size=sizes.get("state", 800)),
        an_item(key="config", label="Configuration", size=sizes.get("config", 200)),
        an_item(key="reports", label="Reports", size=sizes.get("reports", 4000)),
        an_item(key="logs", label="Run logs", size=sizes.get("logs", 1000)),
    ]


def test_the_dialog_lists_every_category_with_its_size(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog(four_items())

    shown = _all_text(dialog)
    assert any("Reports" in text for text in shown)
    assert any("Run logs" in text for text in shown)
    assert any("2 items" in text for text in shown)
    dialog.close()


def test_state_and_config_are_ticked_and_the_records_are_not(qapp):
    """Removing test records stays a deliberate extra click."""
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog(four_items())

    assert dialog.checkboxes["state"].isChecked() is True
    assert dialog.checkboxes["config"].isChecked() is True
    assert dialog.checkboxes["reports"].isChecked() is False
    assert dialog.checkboxes["logs"].isChecked() is False
    dialog.close()


def test_the_total_counts_only_what_is_ticked(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog(four_items(state=1024, config=1024))

    assert dialog.total_label.text() == "2.0 KB"
    dialog.close()


def test_ticking_a_category_updates_the_total(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog(four_items(state=1024, config=1024, reports=2048))
    dialog.checkboxes["reports"].setChecked(True)

    assert dialog.total_label.text() == "4.0 KB"
    dialog.close()


def test_an_empty_category_cannot_be_ticked(qapp):
    """Nothing there means nothing to choose."""
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog([an_item(key="state", count=0, size=0), an_item(key="logs")])

    assert dialog.checkboxes["state"].isEnabled() is False
    assert dialog.checkboxes["state"].isChecked() is False
    dialog.close()


def test_unticking_everything_disables_the_confirm_button(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog(four_items())
    dialog.checkboxes["state"].setChecked(False)
    dialog.checkboxes["config"].setChecked(False)

    assert dialog.remove_button.isEnabled() is False
    dialog.close()


def test_only_the_ticked_categories_are_removed(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog
    from pypts.utilities.data_removal import RemovalOutcome

    passed = []

    def remover(items):
        passed.extend(items)
        return RemovalOutcome()

    dialog = RemoveCacheDialog(four_items(), remover=remover)
    dialog.checkboxes["logs"].setChecked(True)
    dialog.remove_button.click()

    assert [item.key for item in passed] == ["state", "config", "logs"]
    dialog.close()


def test_cancelling_removes_nothing(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    called = []
    dialog = RemoveCacheDialog(four_items(), remover=lambda items: called.append(items))
    dialog.cancel_button.click()

    assert called == []
    assert dialog.outcome is None


def test_confirming_calls_the_remover_and_shows_the_result(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog
    from pypts.utilities.data_removal import RemovalOutcome

    outcome = RemovalOutcome(removed_bytes=2048, removed_count=3)
    dialog = RemoveCacheDialog(four_items(), remover=lambda items: outcome)

    dialog.remove_button.click()

    assert dialog.outcome is outcome
    assert dialog.showing == "result"
    shown = " ".join(_all_text(dialog))
    assert "3 items deleted" in shown
    assert "2.0 KB freed" in shown
    dialog.close()


def test_the_result_page_names_what_could_not_be_removed(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog
    from pypts.utilities.data_removal import RemovalOutcome

    outcome = RemovalOutcome(removed_count=1, failures=("pypts_now.log: in use",))
    dialog = RemoveCacheDialog(four_items(), remover=lambda items: outcome)

    dialog.remove_button.click()

    shown = " ".join(_all_text(dialog))
    assert "pypts_now.log: in use" in shown
    dialog.close()


def test_the_kept_log_note_is_repeated_on_the_result_page(qapp):
    """The operator has to learn why one log is still there."""
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog
    from pypts.utilities.data_removal import RemovalOutcome

    item = an_item(key="logs", label="Run logs", note="This run's log stays - it is in use.")
    dialog = RemoveCacheDialog([item], remover=lambda items: RemovalOutcome())
    dialog.checkboxes["logs"].setChecked(True)

    dialog.remove_button.click()

    assert "This run's log stays" in " ".join(_all_text(dialog))
    dialog.close()


def test_a_dialog_with_nothing_to_remove_cannot_be_confirmed(qapp):
    from pypts.hmi.gui.remove_cache_dialog import RemoveCacheDialog

    dialog = RemoveCacheDialog([an_item(key="state", count=0, size=0)])

    assert dialog.remove_button.isEnabled() is False
    assert dialog.remove_button.text() == "Nothing to remove"
    dialog.close()


def test_removing_the_cache_resets_the_recents_the_gui_holds(gui, tmp_path, monkeypatch):
    """The store held the old list in memory and would write it straight back."""
    from pypts.hmi.gui import gui as gui_module
    from pypts.utilities.data_removal import RemovalOutcome

    instance, _outbox, inbox = gui
    instance.open_recipe(str(a_recipe_file(tmp_path)))
    load_demo_recipe(instance, inbox)
    assert instance.recent_recipes.entries() != []

    # The real file is under tmp_path (autouse fixture); delete it as removal would.
    file_locations.recent_recipes_path().unlink()
    # survey() with no arguments resolves the *real* installation. Stubbed so
    # that no test in this file can ever be one edit away from deleting it.
    monkeypatch.setattr(gui_module, "survey", list)
    monkeypatch.setattr(
        gui_module, "show_remove_cache_dialog", lambda items, parent=None: RemovalOutcome()
    )

    instance._remove_cache()

    assert instance.recent_recipes.entries() == []


def test_cancelling_from_the_menu_changes_nothing(gui, monkeypatch):
    from pypts.hmi.gui import gui as gui_module

    instance, _outbox, _inbox = gui
    monkeypatch.setattr(gui_module, "survey", list)
    monkeypatch.setattr(gui_module, "show_remove_cache_dialog", lambda items, parent=None: None)

    instance._remove_cache()

    assert instance.window.remove_cache_action.isEnabled() is True


def _all_text(widget):
    """Every label *and* checkbox caption - category names are checkboxes now."""
    from PySide6.QtWidgets import QCheckBox, QLabel

    return [
        child.text()
        for child in widget.findChildren(QLabel) + widget.findChildren(QCheckBox)
    ]


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


def test_pause_calls_itself_resume_once_it_has_paused(gui, inbox_run_started):
    """Hovering a paused run's Pause button must not still say "Pause"."""
    instance, _outbox, _inbox = inbox_run_started
    assert "Pause" in instance.top_bar.pause_button.accessibleName()

    instance._toggle_pause()

    assert instance.top_bar.pause_button.accessibleName() == "Resume"
    assert "Continue the run" in instance.top_bar.pause_button.toolTip()

    instance._toggle_pause()
    assert instance.top_bar.pause_button.accessibleName() == "Pause"


def test_a_finished_run_forgets_it_was_paused(gui, inbox_run_started):
    instance, _outbox, inbox = inbox_run_started
    instance._toggle_pause()

    inbox.send(RunFinished(result=ResultType.PASS, outcomes=()))
    instance.poll_core()

    assert instance.top_bar.pause_button.accessibleName() == "Pause"


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


# --- The step table's YAML hover panel ----------------------------------------
#
# What the operator gets between runs: the pointer on a row, and that step's
# YAML beside it. The fragments themselves are the recipe layer's
# (step_source.py, covered in test_recipe.py); these tests own the wiring, the
# idle gate and the theme.


A_FRAGMENT = "steptype: Wait\nstep_name: First wait\nwait_time: '0.01'"


def a_table_with_yaml(qapp):
    """A step table filled from a sequence, every row carrying a fragment."""
    from pypts.hmi.gui.step_table import StepTableContent

    content = StepTableContent()
    sequence = a_recipe_loaded().sequences[0]
    sources = tuple(f"{A_FRAGMENT}\n# row {row}" for row in range(len(sequence.steps)))
    content.show_sequence(sequence, sources)
    return content, sources


def test_each_row_carries_its_own_yaml(qapp):
    from pypts.hmi.gui.step_table import _YAML_ROLE

    content, sources = a_table_with_yaml(qapp)

    stored = [
        content.table.item(row, 0).data(_YAML_ROLE)
        for row in range(content.table.rowCount())
    ]
    assert stored == list(sources)


def test_a_sequence_without_fragments_still_fills_the_table(qapp):
    """A recipe the GUI could not read back off disk costs the panel, not the
    table - show_sequence's second argument is optional on purpose."""
    from pypts.hmi.gui.step_table import _YAML_ROLE, StepTableContent

    content = StepTableContent()
    content.show_sequence(a_recipe_loaded().sequences[0])

    assert content.table.rowCount() == 2
    assert content.table.item(0, 0).data(_YAML_ROLE) is None

    content._hover_cell(0, 0)
    content._show_hovered_yaml()
    assert content.yaml_popup.isVisible() is False


def test_hovering_a_row_shows_that_row_s_yaml(qapp):
    content, sources = a_table_with_yaml(qapp)

    content._hover_cell(1, 0)
    content._show_hovered_yaml()

    assert content.yaml_popup.isVisible() is True
    assert content.yaml_popup.text_view.toPlainText() == sources[1]


def test_the_panel_waits_for_the_pointer_to_rest(qapp):
    """Dragging the eye down the table must show nothing: the panel opens on a
    rest, not on a crossing."""
    from pypts.hmi.gui.step_table import _HOVER_DELAY_MS

    content, _sources = a_table_with_yaml(qapp)

    content._hover_cell(0, 0)

    assert content.yaml_popup.isVisible() is False
    assert content._hover_timer.isActive() is True
    assert content._hover_timer.interval() == _HOVER_DELAY_MS

    # Crossing to another row restarts the wait rather than opening on the first.
    content._hover_cell(1, 0)
    assert content.yaml_popup.isVisible() is False
    assert content._hovered_row == 1


def test_the_delay_really_opens_the_panel(qapp, qtbot):
    """The timer is wired to the show, not merely armed. Run at 10 ms rather
    than the real 1.5 s - the wiring is the same, the wait is not."""
    content, sources = a_table_with_yaml(qapp)
    content._hover_timer.setInterval(10)

    content._hover_cell(1, 0)
    qtbot.waitUntil(content.yaml_popup.isVisible, timeout=1000)

    assert content.yaml_popup.text_view.toPlainText() == sources[1]


def test_an_open_panel_follows_the_pointer_without_waiting_again(qapp):
    """Once it is up the operator has asked for it; another 1.5 s per row would
    turn reading down the table into a series of pauses."""
    content, sources = a_table_with_yaml(qapp)
    content._hover_cell(0, 0)
    content._show_hovered_yaml()

    content._hover_cell(1, 0)

    assert content.yaml_popup.isVisible() is True
    assert content.yaml_popup.text_view.toPlainText() == sources[1]
    assert content._hover_timer.isActive() is False


def test_hiding_the_panel_disarms_the_delay(qapp):
    """A wait left running would open the panel after the pointer had gone."""
    content, _sources = a_table_with_yaml(qapp)
    content._hover_cell(0, 0)
    assert content._hover_timer.isActive() is True

    content.hide_yaml_popup()

    assert content._hover_timer.isActive() is False


def test_the_panel_is_suppressed_while_a_recipe_runs(qapp):
    """The operator asked for it between runs: during one the table is being
    written to and read for verdicts, and must not be covered. A hold counts
    as running - set_running(False) only comes with RunFinished."""
    content, _sources = a_table_with_yaml(qapp)
    content._hover_cell(0, 0)
    content._show_hovered_yaml()
    assert content.yaml_popup.isVisible() is True

    content.set_running(True)
    assert content.yaml_popup.isVisible() is False

    content._hover_cell(1, 0)
    assert content._hover_timer.isActive() is False
    content._show_hovered_yaml()
    assert content.yaml_popup.isVisible() is False

    content.set_running(False)
    content._hover_cell(1, 0)
    content._show_hovered_yaml()
    assert content.yaml_popup.isVisible() is True


def test_leaving_the_table_hides_the_panel(qapp):
    from PySide6.QtCore import QEvent

    content, _sources = a_table_with_yaml(qapp)
    content._hover_cell(0, 0)
    content._show_hovered_yaml()
    assert content.yaml_popup.isVisible() is True

    content.eventFilter(content.table.viewport(), QEvent(QEvent.Type.Leave))

    assert content.yaml_popup.isVisible() is False


def test_a_long_fragment_is_cut_and_says_so(qapp):
    """A Qt.ToolTip window sits under the pointer, so it cannot be scrolled -
    truncation is honest where a scroll bar would be decoration."""
    from pypts.hmi.gui.step_yaml_popup import _MAX_LINES, StepYamlPopup

    popup = StepYamlPopup()
    popup.show_for("\n".join(f"key_{n}: {n}" for n in range(_MAX_LINES + 5)), 10, 10)

    shown = popup.text_view.toPlainText().split("\n")
    assert len(shown) == _MAX_LINES + 1
    assert shown[-1] == "# ... 5 more lines"
    popup.hide()


def test_an_empty_fragment_shows_nothing(qapp):
    from pypts.hmi.gui.step_yaml_popup import StepYamlPopup

    popup = StepYamlPopup()
    popup.show_for("   \n  ", 10, 10)

    assert popup.isVisible() is False


def test_switching_theme_recolours_the_yaml(qapp):
    """Syntax colours are per-character QTextCharFormats, which no stylesheet
    can reach - the same contract the log panel's backlog has."""
    from pypts.hmi.gui.palette import DARK, LIGHT
    from pypts.hmi.gui.step_yaml_popup import StepYamlPopup

    popup = StepYamlPopup()
    popup.show_for(A_FRAGMENT, 10, 10)

    def key_colour():
        # Every step held in a local: a highlighter's formats hang off the
        # block's layout, and reading through a chain of temporaries lets
        # PySide free the QTextCharFormat before the colour is read off it.
        block = popup.text_view.document().firstBlock()
        layout = block.layout()
        ranges = layout.formats()
        return ranges[0].format.foreground().color().name()

    assert key_colour().lower() == LIGHT.yaml_key.lower()

    popup.set_dark(True)
    assert key_colour().lower() == DARK.yaml_key.lower()
    popup.hide()


def test_the_step_table_carries_the_theme_into_the_panel(qapp):
    content, _sources = a_table_with_yaml(qapp)

    content.set_dark(True)

    assert content.yaml_popup._dark is True


def test_the_gui_reads_the_recipe_back_for_the_hover_panel(gui, tmp_path, monkeypatch):
    """The assembler's half: the path it asked CORE to open is the path it
    reads the fragments from, once, when the recipe loads."""
    from pypts.hmi.gui import gui as gui_module
    from pypts.hmi.gui.step_table import _YAML_ROLE

    asked = []

    def fake_sources(path):
        asked.append(path)
        return {"Main": ("steptype: Wait\nstep_name: First wait", "steptype: Wait")}

    monkeypatch.setattr(gui_module.step_source, "step_yaml_by_sequence", fake_sources)

    instance, _outbox, inbox = gui
    instance._requested_recipe_path = str(tmp_path / "demo.yml")
    load_demo_recipe(instance, inbox)

    assert asked == [str(tmp_path / "demo.yml")]
    table = instance.step_table.table
    assert table.item(0, 0).data(_YAML_ROLE) == "steptype: Wait\nstep_name: First wait"


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

    assert "Could not open https://example.invalid/" in caplog.text
