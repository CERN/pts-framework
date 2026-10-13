"""
Recipe Editor v2: the recipe as the operator will see it, the YAML, and a form.

Three columns, built from pypts' own pieces so the window reads like the operator
window: on the left pypts' step table (`StepTableContent`), filled exactly the way
pypts fills it when a recipe is loaded, with PROBLEMS under it where pypts has
LOG OUTPUT; in the middle the recipe text; on the right a form generated from
the recipe schema (`schema_form.SchemaForm`).

**One source of truth: the text, in the Recipe Creator's `RecipeModel`.** The
YAML editor, the form and the toolbar all edit through it, so there is one undo
history and the file's comments survive a form edit. After every change the text
is parsed as pypts parses a file (`recipe_parser.parse_recipe`) and the chosen
sequence's `to_summary()` goes into the table; while the text does not load, the
table keeps its last rows, grayed. `row_map` takes a clicked row to the step it
was authored as, and a line of the YAML to the step around it.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pypts._version import __version__
from pypts.helper_applications.recipe_creator import verify_string
from pypts.helper_applications.recipe_creator.issue import ValidationIssue
from pypts.helper_applications.recipe_creator.rc_logging import start_logging
from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_creator.rc_widgets import (
    InvalidOverlay,
    YamlEditor,
    creator_stylesheet,
)
from pypts.helper_applications.recipe_editor.problems_panel import (
    PROBLEMS_LIST_NAME,
    ProblemsPanel,
)
from pypts.helper_applications.recipe_editor.row_map import (
    StepRef,
    all_refs,
    first_row_of,
    ref_at_line,
    refs_for_rows,
)
from pypts.helper_applications.recipe_editor.schema_form import SchemaForm
from pypts.hmi.gui.gui_theme import (
    configured_theme,
    detect_system_dark_mode,
    install_system_theme_sync,
)
from pypts.hmi.gui.palette import get_palette
from pypts.hmi.gui.step_table import StepTableContent
from pypts.hmi.gui.styles import get_stylesheet
from pypts.hmi.gui.top_bar import svg_icon
from pypts.messages.run_events import SequenceSummary
from pypts.recipe import recipe_parser
from pypts.recipe.recipe_schema import STEP_TYPE_NAMES
from pypts.recipe.step_source import step_sources_from_text

log = logging.getLogger(__name__)

WINDOW_TITLE = "Recipe Editor v2"

#: Over the grayed-out table while there is no recipe at all.
EMPTY_TEXT = "No recipe open: File > New or File > Open, or type one in the editor"

#: What File > New starts from: one step, so it loads from the first moment.
NEW_RECIPE = (
    'name: New recipe\n'
    'version: "1.0"\n'
    "---\n"
    "sequence_name: Main\n"
    "steps:\n"
    "  - steptype: Wait\n"
    "    step_name: First step\n"
    "    wait_time: 1\n"
)

# 16 px toolbar icons in the operator toolbar's style (top_bar.py), {color} filled in.
_FOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round">'
    '<path d="M2 12V5a1 1 0 011-1h3.5l1.5 1.5H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1z"/>'
    "</svg>"
)
_SAVE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round">'
    '<path d="M2.5 2.5h9l2 2v9h-11z"/><path d="M5 2.5v4h6v-4"/><path d="M5 13.5v-4h6v4"/>'
    "</svg>"
)
_UNDO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M5 3L2 6l3 3"/><path d="M2 6h7.5a4 4 0 010 8H6"/></svg>'
)
_REDO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M11 3l3 3-3 3"/><path d="M14 6H6.5a4 4 0 000 8H10"/></svg>'
)
_PLUS_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round">'
    '<path d="M8 3v10M3 8h10"/></svg>'
)
_DELETE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M3 4.5h10M6.5 4.5V3h3v1.5"/>'
    '<path d="M4.5 4.5l.7 9h5.6l.7-9"/></svg>'
)
_UP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M8 13V3M4 7l4-4 4 4"/></svg>'
)
_DOWN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"'
    ' stroke-linejoin="round"><path d="M8 3v10M4 9l4 4 4-4"/></svg>'
)
_COPY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round">'
    '<rect x="5" y="5" width="8.5" height="8.5" rx="1"/>'
    '<path d="M3 10.5V3.5a1 1 0 011-1h6.5"/></svg>'
)


def editor_stylesheet(dark: bool) -> str:
    """The editor's own rules, after pypts' stylesheet and the Creator's."""
    p = get_palette(dark)
    return f"""
QListWidget#{PROBLEMS_LIST_NAME} {{
    background-color: {p.log_background};
    color: {p.log_text};
    border: 1px solid {p.border};
    border-radius: 6px;
    font-family: "Courier New", monospace;
    font-size: 11px;
    padding: 4px 6px;
}}
QLabel#formTitle {{
    font-size: 16px;
    font-weight: 600;
    color: {p.accent_text};
}}
QLabel#formHelp {{
    color: {p.text_muted};
}}
QLabel#formProblem {{
    color: {p.danger};
}}
*[problem="true"] {{
    border: 1px solid {p.danger};
}}
"""


def _fold_keys(summary: SequenceSummary) -> list[tuple[str, ...]]:
    """Each row's name together with the names of the groups it is in."""
    keys: list[tuple[str, ...]] = []
    stack: list[str] = []
    for step in summary.steps:
        del stack[step.depth :]
        keys.append((*stack, step.step_name))
        stack.append(step.step_name)
    return keys


class RecipeEditorWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._theme = configured_theme()
        if self._theme == "dark":
            self._dark = True
        elif self._theme == "system":
            self._dark = detect_system_dark_mode()
        else:
            self._dark = False

        self._model = RecipeModel()
        self._file_path = ""
        self._sequence_index = 0
        # Per table row: the authored step it comes from. And every authored step.
        self._refs: list[StepRef | None] = []
        self._all_refs: list[StepRef] = []
        self._summary: SequenceSummary | None = None
        self._selected: StepRef | None = None
        # A step to select once the table is rebuilt (after add, move, duplicate).
        self._select_after_refresh: tuple[int, str, int] | None = None
        # Set while the window moves the YAML cursor itself.
        self._moving_cursor = False

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh_view)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.setInterval(150)
        self._cursor_timer.timeout.connect(self._follow_cursor)

        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(1100, 700)
        self.resize(1600, 1000)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

        self._model.changed.connect(self._on_model_changed)
        self._toggle_dark(self._dark)
        if self._theme == "system":
            install_system_theme_sync(QApplication.instance(), self._follow_system_theme)
        self._apply_state()
        self._refresh_view()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_actions(self) -> None:
        self._act_new = QAction("New", self, shortcut=QKeySequence.StandardKey.New)
        self._act_open = QAction("Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction("Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction("Save As…", self)
        self._act_exit = QAction("Exit", self)
        self._act_undo = QAction("Undo", self, shortcut=QKeySequence.StandardKey.Undo)
        self._act_redo = QAction("Redo", self)
        # Both, explicitly: StandardKey.Redo gives an action only its first binding.
        self._act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self._act_add_step = QAction("Add Step", self)
        self._act_delete = QAction("Delete Step", self)
        self._act_up = QAction("Move Up", self)
        self._act_down = QAction("Move Down", self)
        self._act_duplicate = QAction("Duplicate Step", self)
        self._act_add_sequence = QAction("Add Sequence…", self)
        self._act_dark = QAction("Toggle Dark Mode", self, checkable=True, checked=self._dark)

        self._act_open.setToolTip("Open a recipe file")
        self._act_save.setToolTip("Save the recipe")
        self._act_undo.setToolTip("Undo the last edit - text, form or step")
        self._act_redo.setToolTip("Redo")
        self._act_add_step.setToolTip("Add a step after the selected one")
        self._act_delete.setToolTip("Delete the selected step")
        self._act_up.setToolTip("Move the selected step up")
        self._act_down.setToolTip("Move the selected step down")
        self._act_duplicate.setToolTip("Duplicate the selected step")

        self._add_step_menu = QMenu(self)
        for name in STEP_TYPE_NAMES.values():
            action = self._add_step_menu.addAction(name)
            action.triggered.connect(lambda _checked=False, t=name: self._add_step(t))
        self._act_add_step.setMenu(self._add_step_menu)

        self._act_new.triggered.connect(self._on_new)
        self._act_open.triggered.connect(self._on_open)
        self._act_save.triggered.connect(self._on_save)
        self._act_save_as.triggered.connect(self._on_save_as)
        self._act_exit.triggered.connect(self.close)
        self._act_undo.triggered.connect(self._model.undo_stack.undo)
        self._act_redo.triggered.connect(self._model.undo_stack.redo)
        self._act_delete.triggered.connect(self._delete_step)
        self._act_up.triggered.connect(lambda: self._move_step(-1))
        self._act_down.triggered.connect(lambda: self._move_step(1))
        self._act_duplicate.triggered.connect(self._duplicate_step)
        self._act_add_sequence.triggered.connect(self._add_sequence)
        self._act_dark.triggered.connect(self._toggle_dark)
        # Signal to slot, no lambda: Qt drops these when the stack is destroyed.
        self._model.undo_stack.canUndoChanged.connect(self._act_undo.setEnabled)
        self._model.undo_stack.canRedoChanged.connect(self._act_redo.setEnabled)
        self._act_undo.setEnabled(False)
        self._act_redo.setEnabled(False)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        for action in (self._act_new, self._act_open):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self._act_save)
        file_menu.addAction(self._act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self._act_exit)

        edit_menu = bar.addMenu("Edit")
        edit_menu.setToolTipsVisible(True)
        edit_menu.addAction(self._act_undo)
        edit_menu.addAction(self._act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_add_step)
        edit_menu.addAction(self._act_delete)
        edit_menu.addAction(self._act_up)
        edit_menu.addAction(self._act_down)
        edit_menu.addAction(self._act_duplicate)
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_add_sequence)

        view_menu = bar.addMenu("View")
        view_menu.addAction(self._act_dark)

        about_menu = bar.addMenu("About")
        gitlab = about_menu.addAction("GitLab")
        wiki = about_menu.addAction("Wiki")
        gitlab.triggered.connect(
            lambda: webbrowser.open("https://gitlab.cern.ch/pts-framework/pts-framework")
        )
        wiki.triggered.connect(
            lambda: webbrowser.open("https://gitlab.cern.ch/pts-framework/pts-framework/-/wikis")
        )

    def _build_toolbar(self) -> None:
        # The operator toolbar's look: its objectName, 16 px icon-only buttons.
        bar = QToolBar("Main")
        bar.setObjectName("PtsToolBar")
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(bar)
        self._toolbar = bar

        bar.addAction(self._act_open)
        bar.addAction(self._act_save)
        bar.addSeparator()
        bar.addAction(self._act_undo)
        bar.addAction(self._act_redo)
        bar.addSeparator()
        bar.addAction(self._act_add_step)
        add_button = bar.widgetForAction(self._act_add_step)
        if isinstance(add_button, QToolButton):
            add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bar.addAction(self._act_delete)
        bar.addAction(self._act_up)
        bar.addAction(self._act_down)
        bar.addAction(self._act_duplicate)

        self.sequence_combo = QComboBox()
        self.sequence_combo.setMinimumWidth(160)
        self.sequence_combo.currentIndexChanged.connect(self._on_sequence_chosen)
        chooser = QWidget()
        chooser_layout = QHBoxLayout(chooser)
        chooser_layout.setContentsMargins(4, 0, 4, 0)
        chooser_layout.setSpacing(4)
        chooser_layout.addWidget(QLabel("Sequence:"))
        chooser_layout.addWidget(self.sequence_combo)
        bar.addWidget(chooser)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

    def _build_central(self) -> None:
        central = QWidget()
        body = QVBoxLayout(central)
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(8)

        self.recipe_label = QLabel()
        self.recipe_label.setObjectName("recipeLabel")
        body.addWidget(self.recipe_label)

        columns = QSplitter(Qt.Orientation.Horizontal)
        columns.setChildrenCollapsible(False)

        # Left: the step table as pypts shows it, PROBLEMS under it.
        self.step_table = StepTableContent()
        self.step_table.set_click_panel_enabled(False)
        # Before a run every result is "Pending": nothing to read for an author.
        self.step_table.set_result_column_visible(False)
        self.step_table.row_clicked.connect(self._on_row_clicked)
        self.step_table.context_menu_extender = self._extend_table_menu
        self.problems = ProblemsPanel()
        self.problems.issue_activated.connect(self._on_issue_activated)
        left = QSplitter(Qt.Orientation.Vertical)
        left.setChildrenCollapsible(False)
        left.addWidget(self.step_table)
        left.addWidget(self.problems)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 1)
        left.setSizes([600, 200])
        self._overlay = InvalidOverlay(self.step_table, EMPTY_TEXT)

        # Middle: the recipe text.
        self.yaml_editor = YamlEditor()
        self.yaml_editor.text_committed.connect(self._model.set_from_text)
        self.yaml_editor.cursorPositionChanged.connect(self._on_cursor_moved)
        middle = self._titled("RECIPE YAML", self.yaml_editor)

        # Right: the form.
        self.form = SchemaForm(self._model)
        right = self._titled("EDIT", self.form)

        columns.addWidget(left)
        columns.addWidget(middle)
        columns.addWidget(right)
        columns.setStretchFactor(0, 4)
        columns.setStretchFactor(1, 3)
        columns.setStretchFactor(2, 3)
        columns.setSizes([640, 480, 480])
        self._columns = columns
        body.addWidget(columns, 1)
        self.setCentralWidget(central)

    def _titled(self, title: str, widget: QWidget) -> QWidget:
        """A column under a section label, as pypts titles its log."""
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(title)
        label.setObjectName("sectionLabel")
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return column

    def _build_status_bar(self) -> None:
        self.status_label = QLabel("Status: no recipe")
        self.status_label.setObjectName("statusLabel")
        self.statusBar().addWidget(self.status_label, 1)
        version = QLabel(f"pypts {__version__}")
        version.setObjectName("versionLabel")
        faint = QGraphicsOpacityEffect(version)
        faint.setOpacity(0.5)
        version.setGraphicsEffect(faint)
        self.statusBar().addPermanentWidget(version)

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _toggle_dark(self, dark: bool) -> None:
        self._dark = dark
        self._act_dark.setChecked(dark)
        self.setStyleSheet(
            get_stylesheet(dark) + creator_stylesheet(dark) + editor_stylesheet(dark)
        )
        self.yaml_editor.set_dark(dark)
        self.step_table.set_dark(dark)
        self._overlay.set_dark(dark)
        self._refresh_icons()
        if self._selected is not None:
            self._highlight_selected()

    def _follow_system_theme(self, dark: bool) -> None:
        self._toggle_dark(dark)

    def _refresh_icons(self) -> None:
        palette = get_palette(self._dark)
        if self._dark:
            colour = palette.accent_text
        else:
            colour = palette.toolbutton
        icons = (
            (self._act_open, _FOLDER_SVG),
            (self._act_save, _SAVE_SVG),
            (self._act_undo, _UNDO_SVG),
            (self._act_redo, _REDO_SVG),
            (self._act_add_step, _PLUS_SVG),
            (self._act_delete, _DELETE_SVG),
            (self._act_up, _UP_SVG),
            (self._act_down, _DOWN_SVG),
            (self._act_duplicate, _COPY_SVG),
        )
        for action, svg in icons:
            icon = QIcon()
            normal = svg_icon(svg.format(color=colour)).pixmap(16, 16)
            greyed = svg_icon(svg.format(color=palette.icon_disabled)).pixmap(16, 16)
            icon.addPixmap(normal, QIcon.Mode.Normal)
            icon.addPixmap(greyed, QIcon.Mode.Disabled)
            action.setIcon(icon)

    # ── Model → view ────────────────────────────────────────────────────────────

    def _on_model_changed(self) -> None:
        text = self._model.to_yaml()
        # Rewriting identical text would only move the cursor while the user types.
        if text != self.yaml_editor.toPlainText():
            self._moving_cursor = True
            self.yaml_editor.set_content(text)
            self._moving_cursor = False
        self._sync_sequence_chooser()
        self.form.refresh()
        self._apply_state()
        self._update_title()
        self._refresh_timer.start()

    def _sync_sequence_chooser(self) -> None:
        names = [str(seq.get("sequence_name", "")) for seq in self._model.sequences()]
        shown = [self.sequence_combo.itemText(i) for i in range(self.sequence_combo.count())]
        if names == shown:
            return
        self.sequence_combo.blockSignals(True)
        self.sequence_combo.clear()
        self.sequence_combo.addItems(names)
        if self._sequence_index >= len(names):
            self._sequence_index = 0
        self.sequence_combo.setCurrentIndex(self._sequence_index)
        self.sequence_combo.blockSignals(False)

    def _refresh_view(self) -> None:
        """The table, PROBLEMS, the gutter, the form's problems and the status, from the text."""
        self._refresh_timer.stop()
        if self._model.is_empty() and self._model.is_valid():
            self.step_table.clear()
            self._refs = []
            self._all_refs = []
            self.problems.show_message("No recipe open.")
            self.status_label.setText("Status: no recipe")
            self.form.set_issues([])
            return
        if not self._model.is_valid():
            # The text cannot be shown as a tree: the last rows stay, grayed.
            line = self._model.invalid_line()
            where = f" (line {line})" if line else ""
            self.problems.show_message(
                f"ERROR    The recipe text cannot be read: {self._model.invalid_reason()}{where}"
            )
            if line:
                self.yaml_editor.set_error_lines({line})
            self.status_label.setText("Status: the recipe text cannot be read")
            return

        text = self._model.to_yaml()
        issues = verify_string(text)
        self.problems.show_issues(issues)
        self.form.set_issues(issues)
        self.yaml_editor.set_error_lines({i.line for i in issues if i.line and i.is_error})
        self.status_label.setText("Status: " + _issue_summary(issues))

        try:
            recipe = recipe_parser.parse_recipe(text, self._file_path, check_version=False)
        except Exception as error:  # noqa: BLE001 - any refusal: keep the last good rows
            log.debug("Recipe Editor v2: the text does not load yet: %s", error)
            self.step_table.setEnabled(False)
            return
        self.step_table.setEnabled(True)

        names = [str(seq.get("sequence_name", "")) for seq in self._model.sequences()]
        if self._sequence_index >= len(names):
            self._sequence_index = 0
        wanted = names[self._sequence_index].lower() if names else ""
        summary = None
        for one in recipe.to_summary():
            if one.sequence_name.lower() == wanted:
                summary = one
        if summary is None:
            self.step_table.clear()
            self._refs = []
            return

        base_dir = str(Path.cwd())
        if self._file_path:
            base_dir = str(Path(self._file_path).resolve().parent)
        sources = step_sources_from_text(text, base_dir, self._file_path or "<editor>")
        rows = ()
        for name, sequence_rows in sources.items():
            if name.lower() == wanted:
                rows = sequence_rows

        expanded = self._expanded_keys()
        self.step_table.show_sequence(summary, rows)
        self._summary = summary
        self._restore_expanded(expanded)
        self._refs = refs_for_rows(rows, names)
        self._all_refs = all_refs(sources, names)

        if self._select_after_refresh is not None:
            wanted_step = self._select_after_refresh
            self._select_after_refresh = None
            for ref in self._all_refs:
                if (ref.sequence_index, ref.list_name, ref.step_index) == wanted_step:
                    self._select(ref)
                    return
        if self._selected is not None:
            # Same step, new lines and rows.
            for ref in self._all_refs:
                same = (ref.sequence_index, ref.list_name, ref.step_index) == (
                    self._selected.sequence_index,
                    self._selected.list_name,
                    self._selected.step_index,
                )
                if same:
                    self._selected = ref
                    self.yaml_editor.set_step_lines(ref.first_line, ref.last_line)
            self._highlight_selected()

    def _expanded_keys(self) -> set[tuple[str, ...]]:
        if self._summary is None:
            return set()
        keys = _fold_keys(self._summary)
        expanded = set()
        for row, key in enumerate(keys):
            if row < self.step_table.table.rowCount() and self.step_table.is_expanded(row):
                expanded.add(key)
        return expanded

    def _restore_expanded(self, expanded: set[tuple[str, ...]]) -> None:
        if self._summary is None:
            return
        for row, key in enumerate(_fold_keys(self._summary)):
            if key in expanded:
                self.step_table.set_expanded(row, True)

    def _apply_state(self) -> None:
        """What can be used: nothing but File and the text while there is no recipe."""
        valid = self._model.is_valid()
        empty = self._model.is_empty()
        usable = valid and not empty
        self._overlay.set_shown(empty and valid)
        self.step_table.setEnabled(usable)
        self.form.setEnabled(usable)
        selected_step = self._selected is not None and self._selected.list_name == "steps"
        self._act_add_step.setEnabled(usable)
        self._act_add_sequence.setEnabled(usable)
        self._act_delete.setEnabled(usable and selected_step)
        self._act_up.setEnabled(usable and selected_step)
        self._act_down.setEnabled(usable and selected_step)
        self._act_duplicate.setEnabled(usable and selected_step)
        self._act_save.setEnabled(not empty or not valid)
        self._act_save_as.setEnabled(not empty or not valid)
        self.sequence_combo.setEnabled(usable)

    def _update_title(self) -> None:
        name = self._file_path or "Unsaved"
        modified = " *" if self._model.is_modified() else ""
        self.setWindowTitle(f"{WINDOW_TITLE} — {name}{modified}")
        header = self._model.header()
        recipe_name = str(header.get("name") or "") if isinstance(header, dict) else ""
        if recipe_name:
            where = self._file_path or "not saved yet"
            self.recipe_label.setText(f"Editing {recipe_name}\n{where}")
        else:
            self.recipe_label.setText("No recipe open")

    # ── Selection ──────────────────────────────────────────────────────────────

    def _on_row_clicked(self, row: int) -> None:
        if row < 0 or row >= len(self._refs):
            return
        ref = self._refs[row]
        if ref is not None:
            self._select(ref, row=row)

    def _select(self, ref: StepRef | None, row: int = -1, move_cursor: bool = True) -> None:
        self._selected = ref
        self._apply_state()
        if ref is None:
            self.step_table.clear_highlight()
            self.yaml_editor.set_step_lines(-1, -1)
            self.form.show_step(None, self._sequence_index)
            return
        self._highlight_selected(row)
        if move_cursor:
            self._show_lines(ref.first_line, ref.last_line)
        else:
            self.yaml_editor.set_step_lines(ref.first_line, ref.last_line)
        if self.form.current_ref() != ref:
            self.form.show_step(ref, self._sequence_index)

    def _highlight_selected(self, row: int = -1) -> None:
        if self._selected is None:
            return
        if row < 0:
            row = first_row_of(self._refs, self._selected)
        if row >= 0 and not self.step_table.table.isRowHidden(row):
            self.step_table.highlight_row(row)
        else:
            self.step_table.clear_highlight()

    def _show_lines(self, first: int, last: int) -> None:
        """Tint a step's lines in the YAML, put the cursor on its first, bring it into view."""
        self.yaml_editor.set_step_lines(first, last)
        start = self.yaml_editor.document().findBlockByNumber(first)
        if not start.isValid():
            return
        self._moving_cursor = True
        self.yaml_editor.setTextCursor(QTextCursor(start))
        self.yaml_editor.centerCursor()
        self._moving_cursor = False

    def _on_cursor_moved(self) -> None:
        if self._moving_cursor:
            return
        self._cursor_timer.start()

    def _follow_cursor(self) -> None:
        """The step around the YAML cursor becomes the selected one."""
        if not self._model.is_valid() or self._model.is_empty():
            return
        line = self.yaml_editor.textCursor().blockNumber()
        ref = ref_at_line(self._all_refs, line)
        if ref == self._selected:
            return
        if ref is not None and first_row_of(self._refs, ref) < 0:
            # A step of a sequence the table is not showing: show that sequence.
            self._sequence_index = ref.sequence_index
            self.sequence_combo.blockSignals(True)
            self.sequence_combo.setCurrentIndex(ref.sequence_index)
            self.sequence_combo.blockSignals(False)
            self._selected = ref
            self._refresh_view()
            self.yaml_editor.set_step_lines(ref.first_line, ref.last_line)
            self.form.show_step(ref, ref.sequence_index)
            self._apply_state()
            return
        self._select(ref, move_cursor=False)

    def _on_sequence_chosen(self, index: int) -> None:
        if index < 0:
            return
        self._sequence_index = index
        self._select(None)
        self._refresh_view()

    def _on_issue_activated(self, issue: ValidationIssue) -> None:
        if issue.line:
            self.yaml_editor.go_to_line(issue.line)
            self.yaml_editor.setFocus()

    def _extend_table_menu(self, menu: QMenu, row: int) -> None:
        """The step-editing entries, on the authored step the row comes from."""
        ref = None
        if 0 <= row < len(self._refs):
            ref = self._refs[row]
        menu.addSeparator()
        add = menu.addMenu("Add step after")
        for name in STEP_TYPE_NAMES.values():
            action = add.addAction(name)
            action.triggered.connect(
                lambda _checked=False, t=name, r=ref: self._add_step(t, after=r)
            )
        for title, handler in (
            ("Delete step", self._delete_step),
            ("Move up", lambda: self._move_step(-1)),
            ("Move down", lambda: self._move_step(1)),
            ("Duplicate step", self._duplicate_step),
        ):
            action = menu.addAction(title)
            usable = ref is not None and ref.list_name == "steps"
            action.setEnabled(usable)
            action.triggered.connect(
                lambda _checked=False, r=ref, h=handler: (self._select(r), h())
            )

    # ── Step and sequence edits ──────────────────────────────────────────────────

    def _add_step(self, steptype: str, after: StepRef | None = None) -> None:
        anchor = after if after is not None else self._selected
        sequence = self._sequence_index
        position = len(self._model.steps(sequence))
        if anchor is not None and anchor.list_name == "steps":
            sequence = anchor.sequence_index
            position = anchor.step_index + 1
        self._select_after_refresh = (sequence, "steps", position)
        self._model.add_step(sequence, steptype, position)
        self._refresh_view()

    def _delete_step(self) -> None:
        ref = self._selected
        if ref is None or ref.list_name != "steps":
            return
        self._select(None)
        self._model.remove_step(ref.sequence_index, ref.step_index)
        self._refresh_view()

    def _move_step(self, offset: int) -> None:
        ref = self._selected
        if ref is None or ref.list_name != "steps":
            return
        target = ref.step_index + offset
        if target < 0 or target >= len(self._model.steps(ref.sequence_index)):
            return
        self._select_after_refresh = (ref.sequence_index, "steps", target)
        self._model.move_step(ref.sequence_index, ref.step_index, target)
        self._refresh_view()

    def _duplicate_step(self) -> None:
        ref = self._selected
        if ref is None or ref.list_name != "steps":
            return
        self._select_after_refresh = (ref.sequence_index, "steps", ref.step_index + 1)
        self._model.duplicate_step(ref.sequence_index, ref.step_index)
        self._refresh_view()

    def _add_sequence(self) -> None:
        name, ok = QInputDialog.getText(self, "Add sequence", "Sequence name:")
        if not ok or not name.strip():
            return
        self._model.add_sequence(name.strip())
        self._sequence_index = len(self._model.sequences()) - 1
        self._sync_sequence_chooser()
        self.sequence_combo.setCurrentIndex(self._sequence_index)

    # ── Files ──────────────────────────────────────────────────────────────────

    def _on_new(self) -> None:
        if not self._may_discard():
            return
        self._file_path = ""
        self._selected = None
        self._sequence_index = 0
        self._model.load_yaml(NEW_RECIPE)
        self.form.show_step(None, 0)
        self._update_title()
        self._refresh_view()
        log.info("New recipe created.")

    def _on_open(self) -> None:
        if not self._may_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open recipe", "", "YAML Files (*.yml *.yaml)"
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        """Load one recipe file - also what pypts' Edit > Recipe Editor v2 passes."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            log.error("Recipe '%s' could not be opened: %s", path, error)
            QMessageBox.critical(self, "Open failed", str(error))
            return
        self._file_path = path
        self._selected = None
        self._sequence_index = 0
        self._model.load_yaml(text)
        self.form.show_step(None, 0)
        self._update_title()
        self._refresh_view()
        log.info("Opened: %s", path)

    def _on_save(self) -> None:
        if not self._file_path:
            self._on_save_as()
            return
        self._save_to(self._file_path)

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", self._file_path or "", "YAML Files (*.yml *.yaml)"
        )
        if path:
            self._file_path = path
            self._save_to(path)

    def _save_to(self, path: str) -> bool:
        try:
            Path(path).write_text(self._model.to_yaml(), encoding="utf-8")
        except OSError as error:
            log.error("Recipe '%s' could not be saved: %s", path, error)
            QMessageBox.critical(self, "Save failed", str(error))
            return False
        self._model.undo_stack.setClean()
        self._update_title()
        log.info("Saved: %s", path)
        return True

    def _may_discard(self) -> bool:
        """True when there is nothing unsaved, or the user lets it go (or saves it)."""
        if not self._model.is_modified():
            return True
        # No recipe at all (start-up, or everything typed was deleted): nothing to lose.
        if self._model.is_empty() and not self._model.to_yaml().strip():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "The recipe has unsaved changes. Save them first?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            self._on_save()
            return not self._model.is_modified()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        if self._may_discard():
            event.accept()
        else:
            event.ignore()


def _issue_summary(issues: list[ValidationIssue]) -> str:
    errors = sum(1 for issue in issues if issue.is_error)
    warnings = sum(1 for issue in issues if issue.is_warning)
    if not errors and not warnings:
        return "recipe valid"
    parts = []
    if errors:
        parts.append(f"{errors} error{'s' if errors != 1 else ''}")
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    return " · ".join(parts)


def main() -> int:
    log_path = start_logging(prefix="recipe_editor", program_name="Recipe Editor v2")
    log.info("Recipe Editor v2 started.")
    log.debug("Recipe Editor v2 log file: %s; arguments: %s", log_path, sys.argv[1:])
    app = QApplication(sys.argv)
    window = RecipeEditorWindow()
    window.show()
    # `python -m pypts.helper_applications.recipe_editor [recipe.yml]` - pypts'
    # Edit > Recipe Editor v2 passes the recipe it has loaded.
    if len(sys.argv) > 1:
        window.open_file(sys.argv[1])
    exit_code = app.exec()
    log.info("Recipe Editor v2 stopped.")
    return exit_code
