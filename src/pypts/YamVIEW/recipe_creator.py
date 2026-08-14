# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""YamVIEW recipe editor shell and working-document owner."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import yaml
from pydantic import ValidationError
from PySide6.QtCore import QMargins, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedLayout,
    QStyle,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pypts.gui_theme import (
    detect_system_dark_mode,
    get_theme_colors,
    get_yamview_stylesheet,
    install_system_theme_sync,
)
from pypts.recipe_language import Recipe as RecipeDefinition
from pypts.recipe_language import RecipeHeader, Sequence
from pypts.recipe_parser import ParseResult, parse_recipe_text, recipe_to_yaml
from pypts.YamVIEW.customGUIModules import (
    RecipeCreatorApp,
    ScintillaYamlEditor,
    WatermarkWidget,
)
from pypts.YamVIEW.recipe_sequencer_setup import SequencerWidget, _sequence_node
from pypts.YamVIEW.verify_recipe import format_diagnostic

SEMANTIC_DIAGNOSTIC_CODES = {
    "duplicate-sequence",
    "unknown-main-sequence",
    "unknown-sequence-reference",
    "unequal-indexed-inputs",
    "mixed-passthrough",
    "missing-ssh-global",
    "missing-ssh-credential",
    "missing-ssh-connect",
    "missing-ssh-close",
}


class RecipeEditorMainMenu(QMainWindow):
    """Own YamVIEW working text, validation state, recovery, and persistence."""

    def __init__(self):
        super().__init__()
        self.dark_mode = detect_system_dark_mode()
        self.temporary_recipe_contents = ""
        self.last_valid_recipe = ""
        self.current_file_path: str | None = None
        self.current_recipe: RecipeDefinition | None = None
        self.yaml_documents: list[dict] = []
        self.is_recipe_valid = False
        self.enable_recipe_verification = True
        self._setting_text = False
        self.title = "YamVIEW 1.0.0"
        self.setWindowTitle(f"{self.title} recipe editor")
        self.setGeometry(200, 200, 1600, 1000)

        self.setup_menu()
        self.setup_central_widget()
        self.setup_toolbar()
        self.setup_tree_and_yaml()
        self.setup_status_and_layouts()
        self.toggle_dark_mode_action.setChecked(self.dark_mode)
        self.toggle_dark_mode(self.dark_mode, log_change=False)
        self._disconnect_system_theme_sync = install_system_theme_sync(
            QApplication.instance(), self._set_dark_mode
        )
        self._update_actions()
        shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut.activated.connect(self.on_save_clicked)
        self.log("✅ Application started.")

    def closeEvent(self, event) -> None:
        self._disconnect_system_theme_sync()
        super().closeEvent(event)

    def setup_menu(self) -> None:
        menubar = self.menuBar()
        self.file_menu = menubar.addMenu("File")
        self.new_recipe_action = QAction("New Recipe", self)
        self.open_recipe_action = QAction("Open Recipe", self)
        self.close_recipe = QAction("Close Recipe", self)
        self.exit_action = QAction("Exit", self)
        for action in (
            self.new_recipe_action,
            self.open_recipe_action,
            self.close_recipe,
            self.exit_action,
        ):
            self.file_menu.addAction(action)
        self.new_recipe_action.triggered.connect(self.on_add_clicked)
        self.open_recipe_action.triggered.connect(self.open_recipe)
        self.close_recipe.triggered.connect(self.on_close_recipe_clicked)
        self.exit_action.triggered.connect(self.close)

        self.edit_menu = menubar.addMenu("Edit")
        self.save_action = QAction("Save Recipe", self)
        self.save_as_action = QAction("Save Recipe As", self)
        self.edit_menu.addAction(self.save_action)
        self.edit_menu.addAction(self.save_as_action)
        self.save_action.triggered.connect(self.on_save_clicked)
        self.save_as_action.triggered.connect(self.on_save_as_clicked)

        self.view_menu = menubar.addMenu("View")
        self.toggle_dark_mode_action = QAction("Toggle Dark Mode", self)
        self.toggle_dark_mode_action.setCheckable(True)
        self.toggle_dark_mode_action.triggered.connect(self.toggle_dark_mode)
        self.view_menu.addAction(self.toggle_dark_mode_action)

        self.about_menu = menubar.addMenu("About")
        self.open_gitlab = QAction("GitLab", self)
        self.open_wiki = QAction("Documentation", self)
        self.about_menu.addAction(self.open_gitlab)
        self.about_menu.addAction(self.open_wiki)
        self.open_gitlab.triggered.connect(self.on_open_gitlab_clicked)
        self.open_wiki.triggered.connect(self.on_open_wiki_clicked)

    def setup_central_widget(self) -> None:
        self.central_widget = QWidget()
        self.central_widget.setObjectName("yamRoot")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

    def setup_toolbar(self) -> None:
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(28, 28))
        self.action_add = QAction(
            self.style().standardIcon(QStyle.SP_FileDialogNewFolder),
            "Create recipe from template",
            self,
        )
        self.action_save = QAction(
            self.style().standardIcon(QStyle.SP_DialogSaveButton), "Save", self
        )
        self.action_save_as = QAction(
            self.style().standardIcon(QStyle.SP_DialogSaveButton), "Save as", self
        )
        self.action_restore_recipe = QAction(
            self.style().standardIcon(QStyle.SP_BrowserReload),
            "Restore last valid recipe state",
            self,
        )
        for action in (
            self.action_add,
            self.action_save,
            self.action_save_as,
            self.action_restore_recipe,
        ):
            self.toolbar.addAction(action)
        self.action_add.triggered.connect(self.on_add_clicked)
        self.action_save.triggered.connect(self.on_save_clicked)
        self.action_save_as.triggered.connect(self.on_save_as_clicked)
        self.action_restore_recipe.triggered.connect(self.on_action_restore_recipe_clicked)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer_action = QWidgetAction(self)
        spacer_action.setDefaultWidget(spacer)
        self.toolbar.addAction(spacer_action)
        icon_label = QLabel()
        icon_label.setPixmap(QPixmap("../images/YamVIEW_cookie.png"))
        icon_action = QWidgetAction(self)
        icon_action.setDefaultWidget(icon_label)
        self.toolbar.addAction(icon_action)

    def setup_tree_and_yaml(self) -> None:
        self.yaml_viewer = ScintillaYamlEditor(self)
        self.yaml_viewer.setReadOnly(False)
        self.yaml_viewer.textChanged.connect(self.on_yamlview_item_changed)
        font = QFont("Fira Code", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.yaml_viewer.setFont(font)
        self.sequencer = SequencerWidget(self.yaml_viewer)
        self.sequencer.yaml_update_callback = self.on_sequencer_updated
        self.tree_and_yaml_widget = QWidget()
        layout = QHBoxLayout(self.tree_and_yaml_widget)
        layout.addWidget(self.sequencer)
        layout.addWidget(self.yaml_viewer)

    def setup_status_and_layouts(self) -> None:
        self.recipeStatus = QTextEdit()
        self.recipeStatus.setObjectName("recipeStatus")
        self.recipeStatus.setReadOnly(True)
        self.recipeStatus.setFixedHeight(30)
        self.recipeStatus.setViewportMargins(QMargins(5, 0, 0, 0))
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.recipeStatus)
        content_layout.addWidget(self.tree_and_yaml_widget)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_layout.addWidget(self.toolbar)
        editor_layout.addWidget(content)
        self.watermark_widget = WatermarkWidget("../images/CERN_Logo.png")
        self.stacked_layout = QStackedLayout()
        self.stacked_layout.addWidget(self.watermark_widget)
        self.stacked_layout.addWidget(editor)
        self.log_console = QTextEdit()
        self.log_console.setObjectName("yamLogConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setFixedHeight(200)
        self.main_layout.addLayout(self.stacked_layout)
        self.main_layout.addWidget(self.log_console)

    def toggle_dark_mode(self, enabled, log_change=True) -> None:
        self.dark_mode = bool(enabled)
        self.setStyleSheet(get_yamview_stylesheet(self.dark_mode))
        self.yaml_viewer.set_dark_mode(self.dark_mode)
        self.sequencer.set_dark(self.dark_mode)
        colors = get_theme_colors(self.dark_mode)
        self.recipeStatus.document().setDefaultStyleSheet(
            f"body {{ color: {colors['header_text']}; }}"
        )
        if log_change:
            self.log("🌙 Dark Mode enabled." if self.dark_mode else "☀️ Light Mode restored.")

    def _set_dark_mode(self, enabled) -> None:
        self.toggle_dark_mode_action.setChecked(enabled)
        self.toggle_dark_mode(enabled)

    def set_recipe_status(self, message: str, color: str = "#333") -> None:
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.recipeStatus.setHtml(f'<span style="color: {color};">{escaped}</span>')

    def show_recipe_ok(self, message: str = "✅ Recipe is valid") -> None:
        self.set_recipe_status(message, "green")

    def show_recipe_error(self, message: str) -> None:
        self.set_recipe_status(f"❌ {message}", "red")

    def show_recipe_info(self, message: str) -> None:
        self.set_recipe_status(f"ℹ️ {message}", "gray")

    def highlight_diagnostic(self, diagnostic) -> None:
        if diagnostic.span is None:
            return
        selection = QTextEdit.ExtraSelection()
        cursor = self.yaml_viewer.textCursor()
        cursor.setPosition(diagnostic.span.start.offset)
        cursor.setPosition(
            max(diagnostic.span.start.offset + 1, diagnostic.span.end.offset),
            QTextCursor.MoveMode.KeepAnchor,
        )
        selection.cursor = cursor
        selection.format.setBackground(QColor("#ffb3b3"))
        self.yaml_viewer.setExtraSelections([selection])
        self.yaml_viewer.setTextCursor(cursor)
        self.yaml_viewer.ensureCursorVisible()

    def _set_text(self, text: str) -> None:
        self._setting_text = True
        self.temporary_recipe_contents = text
        self.yaml_viewer.setText(text)
        self._setting_text = False

    def update_yaml_viewer(self) -> None:
        """Display working text exactly; YamVIEW performs no silent normalization."""
        self._set_text(self.temporary_recipe_contents)

    @staticmethod
    def _structural_recipe(text: str, parsed: ParseResult) -> RecipeDefinition | None:
        if parsed.is_valid:
            return parsed.recipe
        if not parsed.diagnostics or any(
            item.code not in SEMANTIC_DIAGNOSTIC_CODES for item in parsed.diagnostics
        ):
            return None
        try:
            documents = list(yaml.safe_load_all(text))
            return RecipeDefinition(
                header=RecipeHeader.model_validate(documents[0]),
                sequences=[Sequence.model_validate(item) for item in documents[1:]],
            )
        except (IndexError, TypeError, ValidationError, yaml.YAMLError):
            return None

    def _populate_sequencer(self, recipe: RecipeDefinition) -> None:
        header = recipe.header.model_dump(mode="python", by_alias=True, exclude_none=True)
        nodes = [
            {
                "step_name": "Preamble",
                "steptype": "preamble",
                "_node": header,
                "_id": "preamble",
            }
        ]
        for index, sequence in enumerate(recipe.sequences, start=1):
            document = sequence.model_dump(mode="python", by_alias=True, exclude_none=True)
            nodes.append(_sequence_node(document, f"sequence:{index}"))
        self.sequencer.set_yaml_data(nodes)

    def _update_actions(self) -> None:
        has_recipe = bool(self.temporary_recipe_contents)
        can_save = has_recipe and self.is_recipe_valid
        self.close_recipe.setEnabled(has_recipe)
        self.save_as_action.setEnabled(can_save)
        self.action_save_as.setEnabled(can_save)
        self.save_action.setEnabled(can_save and bool(self.current_file_path))
        self.action_save.setEnabled(can_save and bool(self.current_file_path))
        self.action_restore_recipe.setEnabled(
            bool(self.last_valid_recipe)
            and self.temporary_recipe_contents != self.last_valid_recipe
        )

    def _validate_working_text(self, *, rebuild_sequencer: bool) -> ParseResult:
        parsed = parse_recipe_text(self.temporary_recipe_contents, "<editor>")
        structural = self._structural_recipe(self.temporary_recipe_contents, parsed)
        self.current_recipe = structural
        self.is_recipe_valid = parsed.is_valid
        self.yaml_viewer.setExtraSelections([])
        if parsed.is_valid:
            self.last_valid_recipe = self.temporary_recipe_contents
            self.show_recipe_ok()
        else:
            message = format_diagnostic(parsed.diagnostics[0]) if parsed.diagnostics else "Invalid recipe"
            self.show_recipe_error(message)
            for diagnostic in parsed.diagnostics:
                self.log(format_diagnostic(diagnostic))
            if parsed.diagnostics:
                self.highlight_diagnostic(parsed.diagnostics[0])
        if rebuild_sequencer:
            if structural is None:
                self.sequencer.clear()
                self.sequencer.setEnabled(False)
            else:
                self.sequencer.setEnabled(True)
                self._populate_sequencer(structural)
        self._update_actions()
        return parsed

    def update_yaml_treeview(self) -> bool:
        parsed = parse_recipe_text(self.temporary_recipe_contents, "<editor>")
        structural = self._structural_recipe(self.temporary_recipe_contents, parsed)
        if structural is None:
            self.sequencer.clear()
            self.sequencer.setEnabled(False)
            return False
        self.sequencer.setEnabled(True)
        self._populate_sequencer(structural)
        return True

    def _recipe_from_sequencer(self, nodes) -> RecipeDefinition:
        header_node = next(item for item in nodes if item.get("steptype") == "preamble")
        sequence_documents = []
        for sequence_node in nodes:
            if sequence_node.get("steptype") != "sequence_folder":
                continue
            document = dict(sequence_node["_node"])
            for folder in sequence_node["children"]:
                values = [child["_node"] for child in folder["children"]]
                if folder["steptype"] == "setup_folder":
                    document["setup_steps"] = values
                elif folder["steptype"] == "main_folder":
                    document["steps"] = values
                elif folder["steptype"] == "teardown_folder":
                    document["teardown_steps"] = values
            sequence_documents.append(document)
        return RecipeDefinition.model_validate(
            {"header": header_node["_node"], "sequences": sequence_documents}
        )

    def on_sequencer_updated(self, nodes) -> bool:
        """Commit a structurally valid GUI edit and re-run production semantics."""
        try:
            recipe = self._recipe_from_sequencer(nodes)
        except (StopIteration, ValidationError) as error:
            self.show_recipe_error(str(error))
            if self.current_recipe is not None:
                self._populate_sequencer(self.current_recipe)
            self._update_actions()
            return False
        canonical = recipe_to_yaml(recipe)
        self.current_recipe = recipe
        self._set_text(canonical)
        self._validate_working_text(rebuild_sequencer=False)
        self.log("✏️ Structured edit committed; YAML formatting was normalized.")
        self._mark_unsaved()
        return True

    def on_yamlview_item_changed(self) -> None:
        if self._setting_text or not self.enable_recipe_verification:
            return
        self.temporary_recipe_contents = self.yaml_viewer.toPlainText()
        self._validate_working_text(rebuild_sequencer=True)
        self._mark_unsaved()

    def validate_temporary_recipe_contents(self) -> tuple[bool, str]:
        parsed = self._validate_working_text(rebuild_sequencer=False)
        description = "\n".join(format_diagnostic(item) for item in parsed.diagnostics)
        return parsed.is_valid, description or "Validation passed for the recipe."

    def validate_recipe(self) -> bool:
        valid, _ = self.validate_temporary_recipe_contents()
        return valid

    def _mark_unsaved(self) -> None:
        if not self.temporary_recipe_contents:
            return
        filename = Path(self.current_file_path).name if self.current_file_path else "unnamed recipe"
        self.setWindowTitle(f"Recipe Editor - {filename} *unsaved changes*")

    def on_action_restore_recipe_clicked(self) -> None:
        if not self.last_valid_recipe:
            self.log("⚠️ Unable to restore: no valid version is available.")
            return
        self._set_text(self.last_valid_recipe)
        self._validate_working_text(rebuild_sequencer=True)
        self.log("↩️ Restored the last valid recipe state.")

    def _canonical_text(self) -> str | None:
        parsed = parse_recipe_text(self.temporary_recipe_contents, "<editor>")
        if not parsed.is_valid:
            self._validate_working_text(rebuild_sequencer=False)
            self.log("⚠️ Save is blocked until the recipe validates.")
            return None
        return recipe_to_yaml(parsed.require_recipe())

    def _write_recipe(self, path: Path) -> bool:
        text = self._canonical_text()
        if text is None:
            return False
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as error:
            self.log(f"❌ Save failed: {error}")
            return False
        self.current_file_path = str(path)
        self._set_text(text)
        self._validate_working_text(rebuild_sequencer=True)
        self.setWindowTitle(f"Recipe Editor - {path.name}")
        self.log(f"💾 Saved canonical YAML to {path}")
        return True

    def on_save_as_clicked(self) -> None:
        if not self.is_recipe_valid:
            self.log("⚠️ Save As is blocked until the recipe validates.")
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            self.current_file_path or "",
            "YAML Files (*.yaml *.yml);;All Files (*)",
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() not in {".yaml", ".yml"}:
            path = path.with_suffix(".yml")
        self._write_recipe(path)

    def on_save_clicked(self) -> None:
        if not self.is_recipe_valid:
            self.log("⚠️ Save is blocked until the recipe validates.")
            return
        if not self.current_file_path:
            self.on_save_as_clicked()
            return
        self._write_recipe(Path(self.current_file_path))

    def on_add_clicked(self) -> None:
        generator = RecipeCreatorApp()
        if generator.open_creator_dialog(self.dark_mode) is None:
            return
        self.current_file_path = None
        self.reset_recovery_history()
        self._set_text(generator.get_generated_recipe())
        self.stacked_layout.setCurrentIndex(1)
        self._validate_working_text(rebuild_sequencer=True)
        self._mark_unsaved()

    def open_recipe(self) -> None:
        if self.current_file_path:
            file_path = self.current_file_path
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Open recipe file", "", "YAML Files (*.yml *.yaml)"
            )
        if file_path:
            self.load_yaml_recipe(file_path)

    def load_yaml_recipe(self, file_path) -> bool:
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            self.log(f"❌ Could not open {path}: {error}")
            return False
        self.current_file_path = str(path)
        self.reset_recovery_history()
        self._set_text(text)
        self.stacked_layout.setCurrentIndex(1)
        parsed = self._validate_working_text(rebuild_sequencer=True)
        self.setWindowTitle(f"Recipe Editor - {path.name}")
        self.log(f"Loaded recipe text from: {path}")
        return parsed.is_valid

    def on_close_recipe_clicked(self) -> None:
        self.sequencer.clear()
        self._set_text("")
        self.stacked_layout.setCurrentIndex(0)
        self.current_recipe = None
        self.yaml_documents = []
        self.current_file_path = None
        self.is_recipe_valid = False
        self.reset_recovery_history()
        self.setWindowTitle(f"{self.title} recipe editor")
        self.show_recipe_info("No recipe open")
        self._update_actions()

    def reset_recovery_history(self) -> None:
        self.last_valid_recipe = ""
        self._update_actions()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete and self.sequencer.delete_selected():
            return
        super().keyPressEvent(event)

    def on_open_wiki_clicked(self) -> None:
        webbrowser.open("https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/master/")

    def on_open_gitlab_clicked(self) -> None:
        webbrowser.open("https://gitlab.cern.ch/pts/framework/pypts")

    def log(self, message: str) -> None:
        self.log_console.append(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RecipeEditorMainMenu()
    window.show()
    if len(sys.argv) > 1:
        window.load_yaml_recipe(sys.argv[1])
    sys.exit(app.exec())
