"""
Recipe Editor v2: the table as pypts shows it, rows to authored steps, the window.

Edits that commit from inside their own widget's signal run in a process of
their own: a native crash there would take pytest down with it.
"""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from pypts.config_handler import ConfigHandler, file_locations
from pypts.helper_applications.recipe_editor.row_map import (
    StepRef,
    all_refs,
    first_row_of,
    ref_at_line,
    refs_for_rows,
)
from pypts.recipe import recipe_parser, step_source

SHOWCASE = Path(__file__).resolve().parents[2] / (
    "resources/recipes/showcase_recipes/showcase_full.yml"
)

_RECIPE = """\
name: Window test
version: "1.0"
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Settle
    wait_time: 2
  - steptype: Sequence
    sequence_name: Inner
  - steptype: Indexed
    step_name: Add
    template:
      steptype: PythonModule
      module: m.py
      method_name: add
    parameter_sets:
      - inputs: {a: 1}
      - inputs: {a: 2}
---
sequence_name: Inner
steps:
  - steptype: Wait
    step_name: Inside
    wait_time: 1
"""


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """No test here may read or write the user's config.ini or recent-recipes lists."""
    monkeypatch.setattr(
        file_locations, "config_file_path", lambda: tmp_path / "config" / "config.ini"
    )
    monkeypatch.setattr(
        file_locations, "recent_recipes_path", lambda: tmp_path / "state" / "recent.json"
    )
    monkeypatch.setattr(
        file_locations, "editor_recent_recipes_path", lambda: tmp_path / "state" / "editor.json"
    )
    ConfigHandler.reset_for_testing()
    yield
    ConfigHandler.reset_for_testing()


def a_config_file(settings=None):
    """A real config.ini in the test's folder, some values replaced; this process its writer."""
    path = file_locations.config_file_path()
    ConfigHandler.bootstrap()
    text = path.read_text(encoding="utf-8")
    for dotted, value in (settings or {}).items():
        section, _, key = dotted.rpartition(".")
        head, header, rest = text.partition(f"[{section}]")
        rest = re.sub(rf"^{key} = .*$", f"{key} = {value}", rest, count=1, flags=re.MULTILINE)
        text = head + header + rest
    path.write_text(text, encoding="utf-8")
    ConfigHandler.reset_for_testing()
    ConfigHandler.bootstrap()
    return path


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from pypts.helper_applications.recipe_editor.editor_window import RecipeEditorWindow

    win = RecipeEditorWindow()
    yield win
    win._model.undo_stack.setClean()
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _load(window, text: str = _RECIPE) -> None:
    window._model.load_yaml(text)
    window._refresh_view()


# -- step_source from text, and its origins ---------------------------------------------


def test_sources_from_text_equal_sources_from_the_file():
    text = SHOWCASE.read_text(encoding="utf-8")
    from_file = step_source.step_sources_by_sequence(str(SHOWCASE))
    from_text = step_source.step_sources_from_text(text, str(SHOWCASE.parent))
    assert from_text == from_file


def test_every_showcase_row_maps_to_an_authored_step():
    text = SHOWCASE.read_text(encoding="utf-8")
    sources = step_source.step_sources_from_text(text, str(SHOWCASE.parent))
    recipe = recipe_parser.parse_recipe(text, str(SHOWCASE), check_version=False)
    names = list(recipe.sequences)
    lines = text.split("\n")
    for name, rows in sources.items():
        refs = refs_for_rows(rows, names)
        assert None not in refs, name
        for ref in refs:
            assert lines[ref.first_line].lstrip().startswith("- "), (name, ref)


def test_expanded_indexed_rows_map_to_their_indexed_step():
    sources = step_source.step_sources_from_text(_RECIPE, ".")
    refs = refs_for_rows(sources["Main"], ["Main", "Inner"])
    # Settle, the call, Inside, then the two generated Add rows.
    assert len(refs) == 5
    assert refs[3] == refs[4]
    assert refs[3].step_index == 2


def test_a_call_row_maps_to_the_sequence_step_and_its_rows_to_the_called_steps():
    sources = step_source.step_sources_from_text(_RECIPE, ".")
    refs = refs_for_rows(sources["Main"], ["Main", "Inner"])
    assert (refs[1].sequence_index, refs[1].step_index) == (0, 1)
    assert (refs[2].sequence_index, refs[2].step_index) == (1, 0)


def test_a_line_finds_the_step_around_it():
    sources = step_source.step_sources_from_text(_RECIPE, ".")
    refs = all_refs(sources, ["Main", "Inner"])
    lines = _RECIPE.split("\n")
    wait_time_line = lines.index("    wait_time: 2")
    found = ref_at_line(refs, wait_time_line)
    assert found is not None and found.step_index == 0
    assert ref_at_line(refs, 0) is None


def test_first_row_of_a_step():
    ref = StepRef(0, "steps", 2, 0, 0)
    other = StepRef(0, "steps", 1, 0, 0)
    assert first_row_of([other, None, ref, ref], ref) == 2
    assert first_row_of([other], ref) == -1


# -- the table is what pypts shows ------------------------------------------------------


def test_the_table_is_the_recipes_own_summary(window):
    text = SHOWCASE.read_text(encoding="utf-8")
    window.open_file(str(SHOWCASE))
    summary = recipe_parser.parse_recipe(text, str(SHOWCASE), check_version=False).to_summary()
    main = summary[0]
    table = window.step_table.table
    assert table.rowCount() == len(main.steps)
    for row, step in enumerate(main.steps):
        assert window.step_table.table.item(row, 1).text() == step.description
        assert table.item(row, 2).text() == "Pending"


def test_a_row_click_selects_its_step_tints_its_lines_and_fills_the_form(window):
    _load(window)
    window.step_table._clicked_cell(3, 0)  # a generated Indexed row
    assert window._selected is not None
    assert window._selected.step_index == 2
    assert window.form.current_ref() == window._selected
    selected = window._selected
    assert window.yaml_editor._step_lines == (selected.first_line, selected.last_line)


def test_the_click_panel_is_off_in_the_editor(window):
    _load(window)
    window.step_table._clicked_cell(0, 0)
    assert not window.step_table.yaml_popup.isVisible()


def test_the_yaml_cursor_selects_the_step_around_it(window):
    _load(window)
    line = _RECIPE.split("\n").index("    step_name: Inside")
    block = window.yaml_editor.document().findBlockByNumber(line)
    window.yaml_editor.setTextCursor(QTextCursor(block))
    window._follow_cursor()
    assert window._selected is not None
    assert (window._selected.sequence_index, window._selected.step_index) == (1, 0)


def test_text_that_does_not_load_keeps_the_last_rows_grayed(window):
    _load(window)
    rows = window.step_table.table.rowCount()
    window._model.set_from_text("name: [unclosed\n")
    window._refresh_view()
    assert window.step_table.table.rowCount() == rows
    assert not window.step_table.isEnabled()
    assert "cannot be read" in window.problems.item_text(0)
    assert window.problems.badge_text() == "ERROR"


def test_a_loading_problem_keeps_the_rows_and_names_it(window):
    _load(window)
    rows = window.step_table.table.rowCount()
    # Every field valid, but pypts would refuse it: main_sequence names nothing.
    refused = _RECIPE.replace('version: "1.0"', 'version: "1.0"\nmain_sequence: Nope')
    window._model.set_from_text(refused)
    window._refresh_view()
    assert window.step_table.table.rowCount() == rows
    assert not window.step_table.isEnabled()
    assert "Nope" in window.problems.item_text(0)


def test_the_window_starts_empty_and_grayed(window):
    from pypts.helper_applications.recipe_editor.editor_window import EMPTY_TEXT

    assert window._model.is_empty()
    assert not window.step_table.isEnabled()
    assert not window._overlay.isHidden()
    assert window._overlay._text == EMPTY_TEXT
    assert not window._act_save.isEnabled()


def test_new_starts_from_a_recipe_that_loads(window):
    window._on_new()
    assert window.step_table.table.rowCount() == 1
    assert "recipe valid" in window.status_label.text()


def test_folded_groups_stay_unfolded_across_an_edit(window):
    _load(window)
    window.step_table.set_expanded(1, True)
    window._model.set_path(1, ("steps", 0, "wait_time"), 3)
    window._refresh_view()
    assert window.step_table.is_expanded(1)


# -- step edits -----------------------------------------------------------------------------


def test_add_step_goes_after_the_selected_one_and_is_selected(window):
    _load(window)
    window.step_table._clicked_cell(0, 0)
    window._add_step("Wait")
    steps = window._model.steps(0)
    assert steps[1]["steptype"] == "Wait"
    assert window._selected is not None and window._selected.step_index == 1


def test_move_duplicate_and_delete(window):
    _load(window)
    window.step_table._clicked_cell(0, 0)
    window._duplicate_step()
    assert window._model.steps(0)[1]["step_name"] == "Settle (copy)"
    window._move_step(1)
    assert window._model.steps(0)[2]["step_name"] == "Settle (copy)"
    window._delete_step()
    assert [s.get("step_name") for s in window._model.steps(0)].count("Settle (copy)") == 0
    assert window._selected is None


def test_the_sequence_chooser_shows_another_sequence(window):
    _load(window)
    window.sequence_combo.setCurrentIndex(1)
    assert window.step_table.table.rowCount() == 1
    assert window.step_table.table.item(0, 0).text().strip() == "Inside"


# -- edits that commit from inside their own signal -------------------------------------------

_SCENARIO = """
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton
from pypts.helper_applications.recipe_editor.editor_window import RecipeEditorWindow

app = QApplication([])
w = RecipeEditorWindow()
w.show()
w._model.load_yaml({recipe!r})
w._refresh_view()

def settle():
    for _ in range(5):
        app.processEvents()

def field(name):
    return [f for f in w.form._fields if f.path[-1] == name][0].editor

{action}
settle()
w._model.undo_stack.setClean()
print("survived", flush=True)
"""

_MODULE_RECIPE = _RECIPE.replace(
    """  - steptype: Wait
    step_name: Settle
    wait_time: 2
""",
    """  - steptype: PythonModule
    step_name: Measure
    module: m.py
    method_name: f
    inputs:
      voltage: 5
    outputs:
      result: {type: equals, value: 5}
""",
)

_ACTIONS = {
    "step name, Enter": """
w.step_table._clicked_cell(0, 0); settle()
edit = field("step_name")
edit.setFocus(); edit.setText("Renamed"); QTest.keyClick(edit, Qt.Key.Key_Return)
""",
    "output type changed": """
w.step_table._clicked_cell(0, 0); settle()
combo = [c for c in w.form.widget().findChildren(QComboBox) if c.findText("range") >= 0][0]
combo.setCurrentText("range"); combo.activated.emit(combo.currentIndex())
""",
    "input renamed, Enter": """
w.step_table._clicked_cell(0, 0); settle()
edit = [e for e in w.form.widget().findChildren(QLineEdit) if e.text() == "voltage"][0]
edit.setFocus(); edit.setText("volts"); QTest.keyClick(edit, Qt.Key.Key_Return)
""",
    "input removed": """
w.step_table._clicked_cell(0, 0); settle()
[b for b in w.form.widget().findChildren(QPushButton) if b.toolTip() == "Remove voltage"][0].click()
""",
    "header name, Enter": """
edit = field("name")
edit.setFocus(); edit.setText("X"); QTest.keyClick(edit, Qt.Key.Key_Return)
""",
}


@pytest.mark.parametrize("action", list(_ACTIONS), ids=list(_ACTIONS))
def test_an_edit_does_not_crash_the_editor(action):
    script = _SCENARIO.format(recipe=_MODULE_RECIPE, action=textwrap.dedent(_ACTIONS[action]))
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert "survived" in result.stdout


# -- what the user reported on first use (2026-10-13) ----------------------------------------


def test_starting_up_is_not_an_edit(window, qapp):
    # Re-colouring the empty editor used to commit "" as an edit after 400 ms.
    window.yaml_editor._on_debounce()
    window._apply_theme(True)
    window.yaml_editor._on_debounce()
    assert window._model.undo_stack.count() == 0
    assert not window._model.is_modified()


def test_nothing_to_lose_asks_nothing(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    asked: list[object] = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args))
    assert window._may_discard() is True
    assert asked == []


def test_a_row_click_shows_no_window_of_its_own(window, qapp):
    from PySide6.QtCore import QEvent, QObject

    _load(window)
    window.show()
    shown: list[str] = []

    class Spy(QObject):
        def eventFilter(self, watched, event):  # noqa: N802 - Qt's name
            is_window = watched.isWidgetType() and watched.isWindow()
            if event.type() == QEvent.Type.Show and is_window and watched is not window:
                shown.append(type(watched).__name__)
            return False

    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        for row in range(window.step_table.table.rowCount()):
            window.step_table._clicked_cell(row, 0)
            qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    assert shown == []


def test_the_result_column_is_not_shown(window):
    _load(window)
    assert window.step_table.table.isColumnHidden(2)


@pytest.mark.parametrize("keys", ["Ctrl+Y", "Ctrl+Shift+Z"])
def test_redo_answers_both_shortcuts(window, qapp, keys):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    _load(window)
    window.show()
    window._model.set_path(1, ("steps", 0, "wait_time"), 5)
    window._model.undo_stack.undo()
    assert window._model.steps(0)[0]["wait_time"] == 2
    window.step_table.table.setFocus()
    qapp.processEvents()

    QTest.keySequence(window, QKeySequence(keys))

    assert window._model.steps(0)[0]["wait_time"] == 5


# -- second round (2026-10-13): views, Add step, drag-and-drop, menus ------------------------

_THREE = """\
name: Three
version: "1.0"
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: A
    wait_time: 1
  - steptype: Wait
    step_name: B
    wait_time: 2
  - steptype: Wait
    step_name: C
    wait_time: 3
  - steptype: Sequence
    sequence_name: Inner
---
sequence_name: Inner
steps:
  - steptype: Wait
    step_name: Inside
    wait_time: 1
"""


def _names(window, sequence=0):
    return [step.get("step_name") for step in window._model.steps(sequence)]


def test_dropping_a_row_below_another_moves_its_step_there(window):
    _load(window, _THREE)
    window._on_row_dropped(0, 2, True)
    assert _names(window)[:3] == ["B", "C", "A"]
    assert window._selected is not None and window._selected.step_index == 2


def test_dropping_a_row_above_another_moves_its_step_there(window):
    _load(window, _THREE)
    window._on_row_dropped(2, 0, False)
    assert _names(window)[:3] == ["C", "A", "B"]


def test_dropping_a_row_on_itself_changes_nothing(window):
    _load(window, _THREE)
    window._on_row_dropped(1, 1, True)
    window._on_row_dropped(1, 2, False)
    assert window._model.undo_stack.count() == 0


def test_a_step_cannot_be_dropped_into_another_sequence(window):
    _load(window, _THREE)
    window.step_table.expand_all()
    # Row 3 is the call, row 4 the called sequence's own step.
    window._on_row_dropped(0, 4, True)
    assert _names(window)[:3] == ["A", "B", "C"]
    assert "own sequence" in window.statusBar().currentMessage()


def test_the_drop_target_is_above_or_below_by_the_rows_half(window):
    _load(window, _THREE)
    window.show()
    table = window.step_table.table
    rect = table.visualRect(table.model().index(1, 0))
    assert window._dragger.drop_target(rect.top() + 2) == (1, False)
    assert window._dragger.drop_target(rect.bottom() - 2) == (1, True)


def test_add_step_is_in_the_toolbar_with_words_under_the_table_and_the_form(window):
    from PySide6.QtCore import Qt as _Qt

    _load(window, _THREE)
    toolbar_button = window._toolbar.widgetForAction(window._act_add_step)
    assert toolbar_button.toolButtonStyle() == _Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert window.add_step_button.isEnabled()
    assert window.add_step_button.menu() is window._add_step_menu
    assert window.form_add_button.menu() is window._add_step_menu


def test_menus_get_the_stylesheet_with_room_at_the_left(window, qapp):
    assert "QMenu::item" in qapp.styleSheet()
    assert "padding: 7px 28px 7px 18px" in qapp.styleSheet()


def test_a_drop_event_on_the_table_moves_the_step(window, qapp):
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QDropEvent

    from pypts.helper_applications.recipe_editor.row_drag import ROW_MIME

    _load(window, _THREE)
    window.show()
    table = window.step_table.table
    mime = QMimeData()
    mime.setData(ROW_MIME, b"0")
    rect = table.visualRect(table.model().index(2, 0))
    drop = QDropEvent(
        QPointF(rect.center().x(), rect.bottom() - 2),
        _Qt.DropAction.MoveAction,
        mime,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
    )
    # Through the filter itself: Qt delivers a drop only inside a real drag session.
    assert window._dragger.eventFilter(table.viewport(), drop) is True
    assert _names(window)[:3] == ["B", "C", "A"]


# -- third round (2026-10-13): the form only, a badge on PROBLEMS ------------------------------


def test_the_right_column_is_the_form_only(window):
    from PySide6.QtWidgets import QMenu, QTabBar

    menus = window.menuBar().findChildren(QMenu)
    view_menu = next(menu for menu in menus if menu.title() == "View")
    assert [a.text() for a in view_menu.actions()] == ["Appearance", "Full Screen"]
    assert window.form.parent() is not None
    assert not window.form.parentWidget().findChildren(QTabBar)


def test_the_problems_badge_says_ok_warning_or_error(window):
    from pypts.helper_applications.recipe_creator.issue import ValidationIssue
    from pypts.helper_applications.recipe_editor.problems_panel import (
        STATE_ERROR,
        STATE_NONE,
        STATE_OK,
        STATE_WARNING,
    )

    window._refresh_view()
    assert window.problems.state() == STATE_NONE
    assert window.problems._badge.isHidden()
    _load(window, _THREE)
    assert window.problems.state() == STATE_OK
    assert window.problems.badge_text() == "OK"
    assert not window.problems._badge.isHidden()
    warning = ValidationIssue(severity="warning", field="x", message="m", hint="h")
    error = ValidationIssue(severity="error", field="x", message="m", hint="h")
    window.problems.show_issues([warning])
    assert (window.problems.state(), window.problems.badge_text()) == (STATE_WARNING, "!")
    window.problems.show_issues([warning, error])
    assert (window.problems.state(), window.problems.badge_text()) == (STATE_ERROR, "ERROR")


def test_the_badge_is_coloured_by_the_stylesheet(window, qapp):
    sheet = qapp.styleSheet()
    assert 'QLabel#problemsBadge[state="ok"]' in sheet
    assert 'QLabel#problemsBadge[state="warning"]' in sheet
    assert 'QLabel#problemsBadge[state="error"]' in sheet


# -- fourth round (2026-10-13): the editor's own settings and recent recipes -----------------


def _section(text: str, name: str) -> str:
    """One section of an INI text, up to the next header."""
    rest = text.split(f"[{name}]", 1)[1]
    return rest.split("\n[", 1)[0]


def test_the_window_takes_its_theme_from_recipe_editor_not_gui(qapp):
    from pypts.helper_applications.recipe_editor.editor_window import RecipeEditorWindow

    a_config_file({"gui.theme": "light", "recipe_editor.theme": "dark"})
    window = RecipeEditorWindow()
    assert window._dark is True
    window.close()

    a_config_file({"gui.theme": "dark", "recipe_editor.theme": "light"})
    window = RecipeEditorWindow()
    assert window._dark is False
    window.close()


def test_the_window_opens_in_its_configured_mode_and_size(qapp):
    from pypts.helper_applications.recipe_editor.editor_window import RecipeEditorWindow

    a_config_file({"recipe_editor.window_width": "1280", "recipe_editor.window_height": "720"})
    window = RecipeEditorWindow()
    assert window._window_state == ("windowed", 1280, 720)
    window.show_window()
    assert (window.width(), window.height()) == (1280, 720)
    assert not window._act_full_screen.isChecked()
    window.close()


def test_with_no_config_the_window_uses_the_template_defaults(window):
    assert window._window_state == ("windowed", 1600, 1000)
    assert window._dark is False


def test_settings_is_in_the_edit_menu(window):
    from PySide6.QtWidgets import QMenu

    menus = window.menuBar().findChildren(QMenu)
    edit_menu = next(menu for menu in menus if menu.title() == "Edit")
    assert "Settings" in [action.text() for action in edit_menu.actions()]


def test_the_settings_dialog_shows_only_the_editor_keys(window, monkeypatch):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    seen = {}

    def look(dialog):
        seen["pages"] = [dialog.nav.item(row).text() for row in range(dialog.nav.count())]
        seen["keys"] = sorted(dialog.editors)
        seen["theme cards"] = sorted(dialog.editors["recipe_editor.theme"].buttons)
        seen["can save"] = dialog.problem is None
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", look)
    window._act_settings.trigger()
    assert seen["pages"] == ["Appearance", "Advanced"]
    assert seen["keys"] == [
        "recipe_editor.theme",
        "recipe_editor.window_height",
        "recipe_editor.window_mode",
        "recipe_editor.window_width",
    ]
    assert seen["theme cards"] == ["dark", "light", "system"]
    assert seen["can save"]


def test_pypts_settings_leave_the_editor_section_out():
    from pypts.hmi.gui.settings_dialog import editable_keys, pages_for_schema

    assert not [key for key in editable_keys() if key.startswith("recipe_editor.")]
    placed = [key for _title, keys in pages_for_schema() for key in keys]
    assert not [key for key in placed if key.startswith("recipe_editor.")]


def test_saving_a_setting_changes_only_the_editor_section(window, qapp):
    path = a_config_file()
    before = path.read_text(encoding="utf-8")
    window._send_setting("recipe_editor.theme", "dark")
    qapp.processEvents()
    after = path.read_text(encoding="utf-8")
    assert "theme = dark" in _section(after, "recipe_editor")
    assert _section(after, "gui") == _section(before, "gui")
    assert "recipe_editor.theme" in window.statusBar().currentMessage()


def test_a_setting_that_cannot_be_written_is_said_so(window, qapp):
    from pypts.helper_applications.recipe_editor.editor_settings import save_setting

    # No config file at all: nothing to write to.
    result = save_setting("recipe_editor.theme", "dark")
    assert result.accepted is False
    assert result.reason


def test_a_saved_answer_reaches_the_open_dialog(window, qapp, monkeypatch):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    seen = {}

    def save_one(dialog):
        dialog.editors["recipe_editor.theme"].set_value("dark")
        dialog.save_button.click()
        for _ in range(5):
            qapp.processEvents()
        seen["saved"] = dialog.saved
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", save_one)
    window._act_settings.trigger()
    assert seen["saved"] is True
    assert ConfigHandler().get_parameter("recipe_editor.theme") == "dark"


def test_opening_a_recipe_remembers_it_in_the_editor_list_only(window, tmp_path):
    from pypts.utilities.recent_recipes import RecentRecipes

    window.open_file(str(SHOWCASE))
    own = RecentRecipes(file_locations.editor_recent_recipes_path())
    assert [entry.path for entry in own.entries()] == [str(SHOWCASE)]
    assert not file_locations.recent_recipes_path().exists()


def test_open_recent_shows_the_editor_recipes_and_pypts(window, tmp_path):
    from pypts.utilities.recent_recipes import RecentRecipes

    pypts_recipe = tmp_path / "pypts_one.yml"
    pypts_recipe.write_text(_RECIPE, encoding="utf-8")
    RecentRecipes().remember(str(pypts_recipe), "From pypts")
    window.open_file(str(SHOWCASE))

    window._rebuild_recent_menu()
    names = [action.text() for action in window.recent_menu.actions()]
    assert names[:2] == [SHOWCASE.name, "pypts_one.yml"]
    assert names[-1] == "Clear list"


def test_clearing_keeps_pypts_list(window, tmp_path):
    from pypts.utilities.recent_recipes import RecentRecipes

    pypts_recipe = tmp_path / "pypts_one.yml"
    pypts_recipe.write_text(_RECIPE, encoding="utf-8")
    RecentRecipes().remember(str(pypts_recipe), "From pypts")
    window.open_file(str(SHOWCASE))

    window._clear_recent_recipes()
    assert RecentRecipes(file_locations.editor_recent_recipes_path()).entries() == []
    assert len(RecentRecipes().entries()) == 1


def test_a_recent_recipe_that_is_gone_is_dropped_from_the_editor_list(window, tmp_path):
    from pypts.utilities.recent_recipes import RecentRecipes

    gone = tmp_path / "gone.yml"
    gone.write_text(_RECIPE, encoding="utf-8")
    window.open_file(str(gone))
    gone.unlink()
    window._open_recent(str(gone))
    assert RecentRecipes(file_locations.editor_recent_recipes_path()).entries() == []
    assert "Not found" in window.statusBar().currentMessage()


def test_merged_recents_are_newest_first_each_file_once():
    from pypts.helper_applications.recipe_editor.editor_settings import merged_recents
    from pypts.utilities.recent_recipes import RecentEntry

    class Fixed:
        def __init__(self, entries):
            self._entries = entries

        def entries(self):
            return list(self._entries)

    own = Fixed([RecentEntry("/a.yml", "A", "2026-10-13T10:00:00")])
    pypts = Fixed(
        [
            RecentEntry("/b.yml", "B", "2026-10-13T11:00:00"),
            RecentEntry("/a.yml", "A old", "2026-10-01T09:00:00"),
        ]
    )
    merged = merged_recents(own, pypts)
    assert [(entry.path, entry.recipe_name) for entry in merged] == [
        ("/b.yml", "B"),
        ("/a.yml", "A"),
    ]
