# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pypts.helper_applications.recipe_creator.rc_logging import start_logging
from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_creator.rc_widgets import (
    CardStepView,
    HeaderStrip,
    InvalidOverlay,
    ListStepView,
    PanelsStepView,
    VerificationPanel,
    YamlEditor,
    creator_stylesheet,
)
from pypts.helper_applications.recipe_creator import verify_string
from pypts.hmi.gui.gui_theme import (
    configured_theme,
    detect_system_dark_mode,
    install_system_theme_sync,
)
from pypts.hmi.gui.styles import get_stylesheet
from pypts.recipe.recipe_schema import STEP_TYPE_NAMES

log = logging.getLogger(__name__)

#: Over the grayed-out tree while the recipe text cannot be shown as one.
INVALID_TEXT = "Recipe format invalid, fix the recipe via editor or undo"
#: Over the grayed-out tree while there is no recipe at all.
EMPTY_TEXT = "No recipe open: File > New or File > Open, or type one in the editor"


class RecipeCreatorNewWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # The same [gui] theme as pypts, from the same config.ini: light unless
        # the operator chose otherwise in pypts' Edit > Settings. "system"
        # follows the operating system, now and whenever it changes.
        self._theme = configured_theme()
        if self._theme == "dark":
            self._dark = True
        elif self._theme == "system":
            self._dark = detect_system_dark_mode()
        else:
            self._dark = False
        self._file_path: str = ""
        self._model = RecipeModel()
        self._current_seq_idx = 0
        self._selected_step: tuple[int, int] | None = None
        self._logged_invalid_reason = ""
        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.setInterval(200)
        self._verify_timer.timeout.connect(self._run_verification)

        self.setWindowTitle("Recipe Creator")
        self.setGeometry(200, 100, 1600, 1000)
        self.setMinimumWidth(900)

        self._build_menus()
        self._build_toolbar()
        self._build_central()

        # Through _toggle_dark rather than the stylesheet alone, so the step
        # views are painted in the starting theme too, not only after a toggle.
        self._toggle_dark(self._dark)
        if self._theme == "system":
            install_system_theme_sync(QApplication.instance(), self._follow_system_theme)

        self._model.changed.connect(self._on_model_changed)
        # The window starts with no recipe: grayed out until New, Open or typing.
        self._apply_validity()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        self._act_new = QAction("New", self, shortcut=QKeySequence.StandardKey.New)
        self._act_open = QAction("Open\u2026", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction("Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction("Save As\u2026", self)
        self._act_exit = QAction("Exit", self)
        file_menu.addAction(self._act_new)
        file_menu.addAction(self._act_open)
        file_menu.addSeparator()
        file_menu.addAction(self._act_save)
        file_menu.addAction(self._act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self._act_exit)
        self._act_new.triggered.connect(self._on_new)
        self._act_open.triggered.connect(self._on_open)
        self._act_save.triggered.connect(self._on_save)
        self._act_save_as.triggered.connect(self._on_save_as)
        self._act_exit.triggered.connect(self.close)

        # Edit
        edit_menu = mb.addMenu("Edit")
        self._act_undo = QAction("Undo", self, shortcut=QKeySequence.StandardKey.Undo)
        self._act_redo = QAction("Redo", self, shortcut=QKeySequence.StandardKey.Redo)
        edit_menu.addAction(self._act_undo)
        edit_menu.addAction(self._act_redo)
        edit_menu.addSeparator()
        self._act_undo_valid = QAction("Undo to Last Valid", self)
        self._act_undo_valid.setToolTip(
            "Undo until the recipe can be shown in the tree again"
        )
        edit_menu.insertAction(self._act_redo, self._act_undo_valid)
        self._act_undo_valid.triggered.connect(self._model.undo_to_last_valid)
        self._act_undo_valid.setEnabled(False)
        self._add_step_menu = edit_menu.addMenu("Add Step")
        for steptype in STEP_TYPE_NAMES.values():
            act = QAction(steptype, self)
            act.triggered.connect(lambda checked, t=steptype: self._add_step(t))
            self._add_step_menu.addAction(act)
        self._act_del_step = QAction("Delete Step", self)
        edit_menu.addAction(self._act_del_step)
        self._act_del_step.triggered.connect(self._delete_selected_step)
        self._act_undo.triggered.connect(self._model.undo_stack.undo)
        self._act_redo.triggered.connect(self._model.undo_stack.redo)
        self._model.undo_stack.canUndoChanged.connect(self._act_undo.setEnabled)
        self._model.undo_stack.canRedoChanged.connect(self._act_redo.setEnabled)
        self._act_undo.setEnabled(False)
        self._act_redo.setEnabled(False)

        # View
        view_menu = mb.addMenu("View")
        self._act_dark = QAction(
            "Toggle Dark Mode", self, checkable=True, checked=self._dark
        )
        self._act_dark.triggered.connect(self._toggle_dark)
        view_menu.addAction(self._act_dark)
        view_menu.addSeparator()
        self._act_list_view = QAction("List View", self, checkable=True, checked=True)
        self._act_card_view = QAction("Card View", self, checkable=True)
        self._act_panels_view = QAction("Panels View", self, checkable=True)
        for act in [self._act_list_view, self._act_card_view, self._act_panels_view]:
            view_menu.addAction(act)
        self._act_list_view.triggered.connect(lambda: self._switch_view(0))
        self._act_card_view.triggered.connect(lambda: self._switch_view(1))
        self._act_panels_view.triggered.connect(lambda: self._switch_view(2))
        view_menu.addSeparator()
        self._act_toggle_header = QAction("Toggle Header", self)
        self._act_toggle_log = QAction("Toggle Log", self)
        view_menu.addAction(self._act_toggle_header)
        view_menu.addAction(self._act_toggle_log)
        self._act_toggle_header.triggered.connect(self._toggle_header)
        self._act_toggle_log.triggered.connect(self._toggle_log)

        # About
        about_menu = mb.addMenu("About")
        act_gitlab = QAction("GitLab", self)
        act_wiki = QAction("Wiki", self)
        about_menu.addAction(act_gitlab)
        about_menu.addAction(act_wiki)
        act_gitlab.triggered.connect(
            lambda: webbrowser.open("https://gitlab.cern.ch/pts-framework/pts-framework")
        )
        act_wiki.triggered.connect(
            lambda: webbrowser.open("https://gitlab.cern.ch/pts-framework/pts-framework/-/wikis")
        )

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        for act in [self._act_new, self._act_open, self._act_save, self._act_save_as]:
            tb.addAction(act)
        tb.addSeparator()
        tb.addAction(self._act_undo)
        # On the toolbar only while the recipe is invalid - the one time it does
        # anything. Its own action: hiding the menu's would hide it in Edit too.
        self._act_undo_valid_toolbar = QAction("Undo to Last Valid", self)
        self._act_undo_valid_toolbar.setToolTip(self._act_undo_valid.toolTip())
        self._act_undo_valid_toolbar.triggered.connect(self._model.undo_to_last_valid)
        self._act_undo_valid_toolbar.setVisible(False)
        tb.addAction(self._act_undo_valid_toolbar)
        tb.addAction(self._act_redo)
        tb.addSeparator()

        self._act_validate = QAction("Validate", self)
        self._act_validate.triggered.connect(self._run_verification)
        tb.addAction(self._act_validate)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer_action = QWidgetAction(self)
        spacer_action.setDefaultWidget(spacer)
        tb.addAction(spacer_action)

        logo_path = (
            Path(__file__).parent.parent.parent.parent
            / "resources"
            / "images"
            / "CERN_Logo.png"
        )
        if logo_path.exists():
            logo = QLabel()
            logo.setPixmap(
                QPixmap(str(logo_path)).scaledToHeight(
                    28, Qt.TransformationMode.SmoothTransformation
                )
            )
            logo_action = QWidgetAction(self)
            logo_action.setDefaultWidget(logo)
            tb.addAction(logo_action)

    def _build_central(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        # Main horizontal splitter: left panel | YAML editor
        self._hsplit = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        left = QWidget()
        left.setMinimumWidth(420)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._header_strip = HeaderStrip(self._model)
        self._header_strip.sequence_changed.connect(self._on_seq_changed)
        left_layout.addWidget(self._header_strip)

        # Step view stack
        self._view_stack = QStackedWidget()
        self._list_view = ListStepView(self._model)
        self._card_view = CardStepView(self._model)
        self._panels_view = PanelsStepView(self._model)
        self._view_stack.addWidget(self._list_view)
        self._view_stack.addWidget(self._card_view)
        self._view_stack.addWidget(self._panels_view)
        left_layout.addWidget(self._view_stack, 1)

        for view in [self._list_view, self._card_view, self._panels_view]:
            view.step_selected.connect(self._on_step_selected)
            view.step_action_requested.connect(self._on_step_action)

        # Step toolbar
        step_bar = QWidget()
        step_bar_layout = QVBoxLayout(step_bar)
        step_bar_layout.setContentsMargins(4, 4, 4, 4)
        # Qt draws the menu arrow itself.
        add_btn = QPushButton("+ Add Step")
        add_menu = QMenu(self)
        for _st in STEP_TYPE_NAMES.values():
            _act = add_menu.addAction(_st)
            _act.triggered.connect(lambda checked=False, t=_st: self._add_step(t))
        add_btn.setMenu(add_menu)
        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete the selected step")
        del_btn.setEnabled(False)
        del_btn.clicked.connect(self._delete_selected_step)
        self._del_btn = del_btn
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        step_bar_layout.addLayout(btn_row)
        left_layout.addWidget(step_bar)

        self._hsplit.addWidget(left)
        self._left = left
        self._invalid_overlay = InvalidOverlay(left, INVALID_TEXT)

        # Right panel: YAML editor
        self._yaml_editor = YamlEditor()
        self._yaml_editor.set_dark(self._dark)
        self._yaml_editor.text_committed.connect(self._on_yaml_committed)
        self._hsplit.addWidget(self._yaml_editor)
        self._hsplit.setStretchFactor(0, 2)
        self._hsplit.setStretchFactor(1, 3)
        self._hsplit.setSizes([560, 840])

        # Bottom strip: problems and messages side by side
        self._verification = VerificationPanel()
        self._verification.line_requested.connect(self._yaml_editor.go_to_line)

        # A QPlainTextEdit, which pypts' stylesheet frames as its log panel.
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)

        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.addWidget(self._verification)
        bottom.addWidget(self._log)
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 2)

        # Editors on top take every spare pixel; the strip keeps its size.
        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        self._vsplit.addWidget(self._hsplit)
        self._vsplit.addWidget(bottom)
        self._vsplit.setStretchFactor(0, 1)
        self._vsplit.setStretchFactor(1, 0)
        self._vsplit.setCollapsible(0, False)
        self._vsplit.setSizes([10000, 200])
        root_layout.addWidget(self._vsplit)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_model_changed(self) -> None:
        self._sync_yaml_from_model()
        self._apply_validity()
        if self._model.is_valid():
            self._verify_timer.start()
        self._update_title()

    def _sync_yaml_from_model(self) -> None:
        text = self._model.to_yaml()
        # Rewriting identical text would only move the cursor to the start
        # while the user is typing.
        if text != self._yaml_editor.toPlainText():
            self._yaml_editor.set_content(text)

    def _apply_validity(self) -> None:
        """
        Gray out the tree and verification while the text cannot be shown as a
        tree, or while there is no recipe at all (start-up, before New or Open).
        """
        valid = self._model.is_valid()
        empty = valid and self._model.is_empty()
        usable = valid and not empty
        self._left.setEnabled(usable)
        if empty:
            self._invalid_overlay.set_text(EMPTY_TEXT)
        else:
            self._invalid_overlay.set_text(INVALID_TEXT)
        self._invalid_overlay.set_shown(not usable)
        self._verification.setEnabled(usable)
        self._act_undo_valid.setEnabled(not valid)
        self._act_undo_valid_toolbar.setVisible(not valid)
        self._add_step_menu.setEnabled(usable)
        self._act_del_step.setEnabled(usable)
        self._act_validate.setEnabled(usable)
        # Nothing to write; an invalid text is still saved as it is.
        self._act_save.setEnabled(not empty)
        self._act_save_as.setEnabled(not empty)
        if valid:
            self._logged_invalid_reason = ""
            return
        self._verify_timer.stop()
        self._verification.show_invalid()
        line = self._model.invalid_line()
        if line:
            self._yaml_editor.set_error_lines({line})
        else:
            self._yaml_editor.set_error_lines(set())
        reason = self._model.invalid_reason()
        if reason != self._logged_invalid_reason:
            self._logged_invalid_reason = reason
            self._log_msg(f"Recipe format invalid: {reason}")

    def _on_yaml_committed(self, text: str) -> None:
        self._model.set_from_text(text)

    def _on_seq_changed(self, idx: int) -> None:
        self._current_seq_idx = idx
        for view in [self._list_view, self._card_view, self._panels_view]:
            view.set_seq_idx(idx)

    def _on_step_selected(self, seq_idx: int, step_idx: int) -> None:
        self._selected_step = (seq_idx, step_idx)
        self._del_btn.setEnabled(True)

    def _on_step_action(self, action: str, seq_idx: int, step_idx: int) -> None:
        if action == "delete":
            self._model.remove_step(seq_idx, step_idx)

    def _switch_view(self, idx: int) -> None:
        self._view_stack.setCurrentIndex(idx)
        for i, act in enumerate(
            [self._act_list_view, self._act_card_view, self._act_panels_view]
        ):
            act.setChecked(i == idx)

    def _toggle_header(self) -> None:
        self._header_strip.setVisible(not self._header_strip.isVisible())

    def _toggle_log(self) -> None:
        self._log.setVisible(not self._log.isVisible())

    def _follow_system_theme(self, dark: bool) -> None:
        self._act_dark.setChecked(dark)
        self._toggle_dark(dark)

    def _toggle_dark(self, dark: bool) -> None:
        self._dark = dark
        self.setStyleSheet(get_stylesheet(dark) + creator_stylesheet(dark))
        self._yaml_editor.set_dark(dark)
        self._invalid_overlay.set_dark(dark)
        for view in [self._list_view, self._card_view, self._panels_view]:
            view.set_dark(dark)

    def _run_verification(self) -> None:
        if not self._model.is_valid():
            return
        issues = verify_string(self._model.to_yaml())
        self._verification.update_issues(issues)
        error_lines: set[int] = {i.line for i in issues if i.line and i.is_error}
        self._yaml_editor.set_error_lines(error_lines)

    def _add_step(self, steptype: str) -> None:
        steps = self._model.steps(self._current_seq_idx)
        self._model.add_step(self._current_seq_idx, steptype, len(steps))

    def _delete_selected_step(self) -> None:
        if self._selected_step is not None:
            seq_idx, step_idx = self._selected_step
            self._model.remove_step(seq_idx, step_idx)
            self._selected_step = None
            self._del_btn.setEnabled(False)

    def _update_title(self) -> None:
        name = self._file_path or "Unsaved"
        mod = " *" if self._model.is_modified() else ""
        self.setWindowTitle(f"Recipe Creator \u2014 {name}{mod}")

    def _on_new(self) -> None:
        if self._model.is_modified():
            if not self._ask_discard():
                return
        self._model.load_yaml(
            'name: New Recipe\nversion: "0.1"\n---\nsequence_name: Main\nsteps: []\n'
        )
        self._file_path = ""
        self._update_title()
        self._log_msg("New recipe created.")

    def _on_open(self) -> None:
        if self._model.is_modified():
            if not self._ask_discard():
                return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open recipe", "", "YAML Files (*.yml *.yaml)"
        )
        if not path:
            return
        self.open_file(path)

    def open_file(self, path: str) -> None:
        """
        Load one recipe file into the editor.

        Split out of the Open dialog so a path given on the command line -
        what pypts' Edit > Recipe Editor passes - opens the same way.
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
            issues = self._model.load_yaml(text)
            self._file_path = path
            self._update_title()
            self._log_msg(f"Opened: {path}")
            self._verification.update_issues(issues)
        except Exception as exc:
            log.error("Recipe '%s' could not be opened: %s", path, exc)
            log.debug("Traceback for the failed open:", exc_info=True)
            QMessageBox.critical(self, "Open failed", str(exc))

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

    def _save_to(self, path: str) -> None:
        try:
            Path(path).write_text(self._model.to_yaml(), encoding="utf-8")
            self._model.undo_stack.setClean()
            self._update_title()
            self._log_msg(f"Saved: {path}")
        except Exception as exc:
            log.error("Recipe '%s' could not be saved: %s", path, exc)
            log.debug("Traceback for the failed save:", exc_info=True)
            QMessageBox.critical(self, "Save failed", str(exc))

    def _ask_discard(self) -> bool:
        result = QMessageBox.question(
            self,
            "Unsaved changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Discard

    def _log_msg(self, msg: str) -> None:
        """A line for the window's message box, and the same line in the log file."""
        self._log.appendPlainText(msg)
        log.info("%s", msg)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> int:
    log_path = start_logging()
    log.info("Recipe Creator started.")
    log.debug("Recipe Creator log file: %s; arguments: %s", log_path, sys.argv[1:])
    app = QApplication(sys.argv)
    win = RecipeCreatorNewWindow()
    win.show()
    # `python -m pypts.helper_applications.recipe_creator [recipe.yml]` - pypts'
    # Edit > Recipe Editor passes the recipe it has loaded.
    if len(sys.argv) > 1:
        win.open_file(sys.argv[1])
    exit_code = app.exec()
    log.info("Recipe Creator stopped.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
