# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_creator.rc_widgets import (
    CardStepView,
    HeaderStrip,
    ListStepView,
    PanelsStepView,
    VerificationPanel,
    YamlEditor,
)
from pypts.helper_applications.recipe_verificator import verify_string
from pypts.hmi.gui.styles import get_stylesheet
from pypts.recipe.rules import STEP_TYPE_REQUIRED


class RecipeCreatorNewWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._dark = self._detect_dark()
        self._file_path: str = ""
        self._model = RecipeModel()
        self._current_seq_idx = 0
        self._selected_step: tuple[int, int] | None = None
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

        self.setStyleSheet(get_stylesheet(self._dark))

        self._model.changed.connect(self._on_model_changed)

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
        add_step_menu = edit_menu.addMenu("Add Step")
        for steptype in STEP_TYPE_REQUIRED:
            act = QAction(steptype, self)
            act.triggered.connect(lambda checked, t=steptype: self._add_step(t))
            add_step_menu.addAction(act)
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

        # About
        about_menu = mb.addMenu("About")
        act_gitlab = QAction("GitLab", self)
        act_wiki = QAction("Wiki", self)
        about_menu.addAction(act_gitlab)
        about_menu.addAction(act_wiki)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        for act in [self._act_new, self._act_open, self._act_save, self._act_save_as]:
            tb.addAction(act)
        tb.addSeparator()
        tb.addAction(self._act_undo)
        tb.addAction(self._act_redo)
        tb.addSeparator()

        validate_btn = QAction("Validate", self)
        validate_btn.triggered.connect(self._run_verification)
        tb.addAction(validate_btn)

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
        left.setMinimumWidth(340)
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
        left_layout.addWidget(self._view_stack)

        for view in [self._list_view, self._card_view, self._panels_view]:
            view.step_selected.connect(self._on_step_selected)
            view.step_action_requested.connect(self._on_step_action)

        # Step toolbar
        step_bar = QWidget()
        step_bar_layout = QVBoxLayout(step_bar)
        step_bar_layout.setContentsMargins(4, 4, 4, 4)
        add_btn = QPushButton("+ Add Step \u25bc")
        add_btn.clicked.connect(lambda: self._add_step("wait"))
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_selected_step)
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        step_bar_layout.addLayout(btn_row)
        left_layout.addWidget(step_bar)

        self._hsplit.addWidget(left)

        # Right panel: YAML editor
        self._yaml_editor = YamlEditor()
        self._yaml_editor.set_dark(self._dark)
        self._yaml_editor.text_committed.connect(self._on_yaml_committed)
        self._hsplit.addWidget(self._yaml_editor)
        self._hsplit.setStretchFactor(0, 0)
        self._hsplit.setStretchFactor(1, 1)

        root_layout.addWidget(self._hsplit)

        # Verification panel
        self._verification = VerificationPanel()
        self._verification.line_requested.connect(self._yaml_editor.go_to_line)
        root_layout.addWidget(self._verification)

        # Log console
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        root_layout.addWidget(self._log)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_model_changed(self) -> None:
        self._sync_yaml_from_model()
        self._verify_timer.start()
        self._update_title()

    def _sync_yaml_from_model(self) -> None:
        self._yaml_editor.set_content(self._model.to_yaml())

    def _on_yaml_committed(self, text: str) -> None:
        self._model.set_from_text(text)

    def _on_seq_changed(self, idx: int) -> None:
        self._current_seq_idx = idx
        for view in [self._list_view, self._card_view, self._panels_view]:
            view.set_seq_idx(idx)

    def _on_step_selected(self, seq_idx: int, step_idx: int) -> None:
        self._selected_step = (seq_idx, step_idx)

    def _on_step_action(self, action: str, seq_idx: int, step_idx: int) -> None:
        if action == "delete":
            self._model.remove_step(seq_idx, step_idx)

    def _switch_view(self, idx: int) -> None:
        self._view_stack.setCurrentIndex(idx)
        for i, act in enumerate(
            [self._act_list_view, self._act_card_view, self._act_panels_view]
        ):
            act.setChecked(i == idx)

    def _toggle_dark(self, dark: bool) -> None:
        self._dark = dark
        self.setStyleSheet(get_stylesheet(dark))
        self._yaml_editor.set_dark(dark)
        for view in [self._list_view, self._card_view, self._panels_view]:
            view.set_dark(dark)

    def _run_verification(self) -> None:
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
        try:
            text = Path(path).read_text(encoding="utf-8")
            issues = self._model.load_yaml(text)
            self._file_path = path
            self._update_title()
            self._log_msg(f"Opened: {path}")
            self._verification.update_issues(issues)
        except Exception as exc:
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
        self._log.append(msg)

    @staticmethod
    def _detect_dark() -> bool:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        return scheme == Qt.ColorScheme.Dark


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> int:
    app = QApplication(sys.argv)
    win = RecipeCreatorNewWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
