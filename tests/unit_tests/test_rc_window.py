"""
The Recipe Creator's window: the edits that used to crash it, the step form,
the empty state and the layout.

A crash here is a native one (access violation) that would take pytest down
with it, so those scenarios run in a process of their own.
"""

import subprocess
import sys
import textwrap

import pytest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QPushButton

_RECIPE = """\
name: Window test
version: "1.0"
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Settle
    wait_time: 2
  - steptype: PythonModule
    step_name: Measure
    module: my_tests.py
    method_name: measure
    inputs:
      voltage: 5
    outputs:
      result:
        type: equals
        value: 5
---
sequence_name: Other
steps:
  - steptype: Wait
    step_name: Pause
    wait_time: 1
"""


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from pypts.helper_applications.recipe_creator.recipe_creator_new import (
        RecipeCreatorNewWindow,
    )

    win = RecipeCreatorNewWindow()
    yield win
    win._model.undo_stack.setClean()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _select(view, row: int) -> None:
    view._list.setCurrentRow(row)
    QApplication.processEvents()


# -- the edits that crashed the process ---------------------------------------------

_SCENARIO = """
import sys
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox
from pypts.helper_applications.recipe_creator.recipe_creator_new import RecipeCreatorNewWindow

app = QApplication([])
w = RecipeCreatorNewWindow()
w.show()
w._model.load_yaml({recipe!r})
app.processEvents()

def settle():
    for _ in range(5):
        app.processEvents()

{action}
settle()
w._model.undo_stack.setClean()
print("survived", flush=True)
"""

_ACTIONS = {
    "step name, list view": """
w._list_view._list.setCurrentRow(1); settle()
edit = w._list_view._form._name_edit
edit.setFocus(); edit.setText("Renamed"); QTest.keyClick(edit, Qt.Key.Key_Return)
""",
    "output type, list view": """
w._list_view._list.setCurrentRow(1); settle()
w._list_view._form._outputs_rows.findChildren(QComboBox)[0].setCurrentText("range")
""",
    "wait time, list view": """
w._list_view._list.setCurrentRow(0); settle()
spin = w._list_view._form.findChildren(QDoubleSpinBox)[0]
spin.setFocus(); QTest.keyClick(spin, Qt.Key.Key_Up)
""",
    "step name, panels view": """
w._act_panels_view.trigger(); settle()
w._panels_view._list.setCurrentRow(1); settle()
edit = w._panels_view._form._name_edit
edit.setFocus(); edit.setText("Renamed"); QTest.keyClick(edit, Qt.Key.Key_Return)
""",
    "wait time, panels view": """
w._act_panels_view.trigger(); settle()
w._panels_view._list.setCurrentRow(0); settle()
w._panels_view._form.findChildren(QDoubleSpinBox)[0].setValue(9)
""",
    "steptype change rebuilds the rows": """
w._list_view._list.setCurrentRow(0); settle()
spin = w._list_view._form.findChildren(QDoubleSpinBox)[0]
spin.valueChanged.connect(lambda _v: w._model.set_step_field(0, 0, "steptype", "UserWrite"))
spin.setValue(4)
""",
}


@pytest.mark.parametrize("action", list(_ACTIONS), ids=list(_ACTIONS))
def test_an_edit_does_not_crash_the_creator(action):
    script = _SCENARIO.format(recipe=_RECIPE, action=textwrap.dedent(_ACTIONS[action]))
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert "survived" in result.stdout


# -- the step form ------------------------------------------------------------------


def test_a_wait_step_shows_its_wait_time(window):
    window._model.load_yaml(_RECIPE)
    _select(window._list_view, 0)
    form = window._list_view._form
    assert list(form._specific_editors) == ["wait_time"]
    assert form._specific_editors["wait_time"].value() == 2


def test_a_python_module_step_shows_module_and_method(window):
    window._model.load_yaml(_RECIPE)
    _select(window._list_view, 1)
    editors = window._list_view._form._specific_editors
    assert editors["module"].text() == "my_tests.py"
    assert editors["method_name"].text() == "measure"


def test_editing_a_field_keeps_the_form_and_its_editor(window):
    window._model.load_yaml(_RECIPE)
    _select(window._list_view, 0)
    form = window._list_view._form
    spin = form._specific_editors["wait_time"]
    spin.setValue(3)
    QApplication.processEvents()
    assert window._list_view._form is form
    assert form._specific_editors["wait_time"] is spin
    assert window._model.steps(0)[0]["wait_time"] == 3


def test_a_wait_time_that_is_not_a_number_shows_as_zero(window):
    # The model refuses one as a tree; the form must still not raise on it.
    window._model.load_yaml(_RECIPE)
    _select(window._list_view, 0)
    form = window._list_view._form
    form._fill_specific_rows({"steptype": "Wait", "wait_time": "soon"})
    assert form._specific_editors["wait_time"].value() == 0


def test_add_step_offers_the_steptypes_as_authors_write_them(window):
    names = [action.text() for action in window._add_step_menu.actions()]
    assert "PythonModule" in names
    assert "Wait" in names
    assert "wait" not in names


def test_a_step_added_from_the_menu_gets_its_required_fields(window):
    window._model.load_yaml(_RECIPE)
    window._add_step("Wait")
    step = window._model.steps(0)[-1]
    assert step["steptype"] == "Wait"
    assert "wait_time" in step


def test_only_the_open_card_builds_a_form(window):
    from pypts.helper_applications.recipe_creator.rc_widgets import StepFormWidget

    window._model.load_yaml(_RECIPE)
    window._act_card_view.trigger()
    QApplication.processEvents()
    assert window._card_view.findChildren(StepFormWidget) == []


# -- the empty state ----------------------------------------------------------------


def test_with_no_recipe_the_tree_is_grayed_out(window):
    from pypts.helper_applications.recipe_creator.recipe_creator_new import EMPTY_TEXT

    assert window._model.is_empty()
    assert not window._left.isEnabled()
    assert not window._invalid_overlay.isHidden()
    assert window._invalid_overlay._text == EMPTY_TEXT
    assert not window._act_save.isEnabled()
    assert not window._add_step_menu.isEnabled()


def test_a_header_edit_with_no_recipe_is_ignored(window):
    window._model.set_header_field("name", "X")
    assert window._model.is_empty()


def test_new_makes_the_tree_usable(window):
    window._on_new()
    assert window._left.isEnabled()
    assert window._invalid_overlay.isHidden()
    assert window._act_save.isEnabled()


def test_invalid_text_names_the_problem_not_the_empty_state(window):
    from pypts.helper_applications.recipe_creator.recipe_creator_new import INVALID_TEXT

    window._model.set_from_text("name: [unclosed\n")
    assert window._invalid_overlay._text == INVALID_TEXT
    assert window._act_save.isEnabled()


# -- layout and the small pieces ----------------------------------------------------


def test_the_editors_take_the_spare_height(window):
    window.resize(1400, 900)
    window.show()
    QApplication.processEvents()
    editors, bottom = window._vsplit.sizes()
    assert editors > 2 * bottom


def test_small_buttons_are_named_for_the_stylesheet_and_explained(window):
    from pypts.helper_applications.recipe_creator.rc_widgets import SMALL_BUTTON_NAME

    window._model.load_yaml(_RECIPE)
    small = [
        button
        for button in window.findChildren(QPushButton)
        if button.objectName() == SMALL_BUTTON_NAME
    ]
    assert small
    for button in small:
        assert button.toolTip()
    assert "QPushButton#" + SMALL_BUTTON_NAME in window.styleSheet()


def test_warnings_alone_get_a_warning_sign_not_a_cross(window):
    from pypts.helper_applications.recipe_creator.issue import ValidationIssue

    warning = ValidationIssue(severity="warning", field="header.version", message="m", hint="h")
    window._verification.update_issues([warning])
    assert "❌" not in window._verification._summary_label.text()
    assert "⚠" in window._verification._summary_label.text()


def test_the_log_box_takes_plain_lines(window):
    window._log_msg("Opened: x.yml")
    assert window._log.toPlainText().endswith("Opened: x.yml")


def test_no_spin_box_is_left_behind_after_a_steptype_change(window):
    window._model.load_yaml(_RECIPE)
    _select(window._list_view, 0)
    form = window._list_view._form
    window._model.set_step_field(0, 0, "steptype", "UserWrite")
    QApplication.processEvents()
    QApplication.sendPostedEvents(None, 0)
    assert "message" in form._specific_editors
    assert not [s for s in form.findChildren(QDoubleSpinBox) if s.isVisible()]


def test_undo_to_last_valid_is_on_the_toolbar_only_while_invalid(window):
    window._model.load_yaml(_RECIPE)
    assert not window._act_undo_valid_toolbar.isVisible()
    window._model.set_from_text("name: [unclosed\n")
    assert window._act_undo_valid_toolbar.isVisible()
    # The Edit menu keeps its own entry all the time.
    assert window._act_undo_valid.isVisible()
