# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
from pypts.YamVIEW.customGUIModules import (
    ScintillaYamlEditor,
    WatermarkWidget,
    HashableTreeItem,
    RecipeCreatorApp
)

import re
import io, uuid
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedLayout,
    QMessageBox,
    QTextEdit,
    QLabel,
    QWidgetAction,
    QFileDialog,
    QToolBar,
    QStyle,
    QSizePolicy,
)
from PySide6.QtGui import (
    QAction,
    QTextCursor,
    QPixmap
)
from PySide6.QtCore import QSize, QMargins, Qt
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from datetime import datetime
import webbrowser
from pypts.YamVIEW.styles import *
from pypts.YamVIEW.verify_recipe import *
import sys
from PySide6.QtGui import QTextCharFormat, QFont
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from pypts.YamVIEW.recipe_sequencer_setup import *


class RecipeEditorMainMenu(QMainWindow):
# Initialization methods
    def __init__(self):
        super().__init__()
        self.dark_mode = False
        self.yaml_documents = []
        self.temporary_recipe_contents = ""
        self.last_valid_recipe = ""
        self.current_file_path = ""
        self.item_to_line = {}
        self.line_to_item = {}
        self.yaml_parser = YAML()
        self.data = None
        self.enable_recipe_verification = True
        self.title = "YamVIEW 1.0.0"
        self.setWindowTitle(f"{self.title} recipe editor")
        self.setGeometry(200, 200, 1600, 1000)

        self.setup_menu()
        self.setup_central_widget()
        self.setup_toolbar()
        self.setup_tree_and_yaml()
        self.setup_status_and_layouts()

        # Define the shortcut activation action
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.on_save_clicked)

        self.log("✅ Application started.")

    def setup_menu(self):
        menubar = self.menuBar()
        # File menu
        self.file_menu = menubar.addMenu("File")

        self.new_recipe_action = QAction("New Recipe", self)
        self.open_recipe_action = QAction("Open Recipe", self)
        self.close_recipe = QAction("Close Recipe", self)
        self.exit_action = QAction("Exit", self)

        self.file_menu.addAction(self.new_recipe_action)
        self.file_menu.addAction(self.open_recipe_action)
        self.file_menu.addAction(self.close_recipe)
        self.file_menu.addAction(self.exit_action)
        self.close_recipe.setEnabled(False)

        self.new_recipe_action.triggered.connect(self.on_add_clicked)
        self.open_recipe_action.triggered.connect(self.open_recipe)
        self.close_recipe.triggered.connect(self.on_close_recipe_clicked)
        self.exit_action.triggered.connect(self.close)

        # Edit menu
        self.edit_menu = menubar.addMenu("Edit")

        self.save_action = QAction("Save Recipe", self)
        self.save_as_action = QAction("Save Recipe As", self)

        self.edit_menu.addAction(self.save_action)
        self.edit_menu.addAction(self.save_as_action)

        self.save_action.triggered.connect(self.on_save_clicked)
        self.save_as_action.triggered.connect(self.on_save_as_clicked)

        # View menu
        self.view_menu = menubar.addMenu("View")
        self.toggle_dark_mode_action = QAction("Toggle Dark Mode", self)
        self.toggle_dark_mode_action.setCheckable(True)
        self.toggle_dark_mode_action.triggered.connect(self.toggle_dark_mode)
        self.view_menu.addAction(self.toggle_dark_mode_action)

        # About menu
        self.about_menu = menubar.addMenu("About")
        self.open_gitlab = QAction("Gitlab", self)
        self.open_wiki = QAction("Wiki", self)

        self.about_menu.addAction(self.open_gitlab)
        self.about_menu.addAction(self.open_wiki)

        self.open_wiki.triggered.connect(self.on_open_wiki_clicked)
        self.open_gitlab.triggered.connect(self.on_open_gitlab_clicked)

        # Development menu
        self.dev_menu = menubar.addMenu("Development")
        for i in range(1, 5):
            action = QAction(f"Dev Tool {i}", self)
            action.triggered.connect(getattr(self, f"on_dev_{i}_clicked"))
            self.dev_menu.addAction(action)
            self.dev_menu.addAction(action)

    def setup_central_widget(self):
        self.setStyleSheet(light_style)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

    def setup_toolbar(self):
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(28, 28))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.action_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Create recipe from the template", self)
        self.action_save = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Save", self)
        self.action_save_as = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Save as", self)
        self.action_restore_recipe = QAction(self.style().standardIcon(QStyle.SP_BrowserReload),
                                             "Restore last working recipe state", self)

        self.toolbar.addAction(self.action_add)
        self.toolbar.addAction(self.action_save)
        self.toolbar.addAction(self.action_save_as)
        self.toolbar.addAction(self.action_restore_recipe)

        self.action_add.triggered.connect(self.on_add_clicked)
        self.action_save.triggered.connect(self.on_save_clicked)
        self.action_save_as.triggered.connect(self.on_save_as_clicked)
        self.action_restore_recipe.triggered.connect(self.on_action_restore_recipe_clicked)

        self.save_as_action.setEnabled(False)
        self.save_action.setEnabled(False)
        self.action_save.setEnabled(False)
        self.action_save_as.setEnabled(False)

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


    def setup_tree_and_yaml(self):
        # YAML Viewer (custom ScintillaYamlEditor)
        self.yaml_viewer = ScintillaYamlEditor(self)
        self.yaml_viewer.setReadOnly(False)
        self.yaml_viewer.textChanged.connect(self.on_yamlview_item_changed)
        self.yaml_viewer.cursorPositionChanged.connect(self.on_yaml_cursor_changed)
        font = QFont("Fira Code", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.yaml_viewer.setFont(font)

        #Sequencer
        self.sequencer = SequencerWidget(yaml_viewer=self.yaml_viewer)
        self.sequencer.yaml_update_callback = self.on_sequencer_updated

        # Horizontal container for tree + yaml viewer
        self.tree_and_yaml_widget = QWidget()
        self.tree_and_yaml_hlayout = QHBoxLayout(self.tree_and_yaml_widget)
        self.tree_and_yaml_hlayout.addWidget(self.sequencer)
        self.tree_and_yaml_hlayout.addWidget(self.yaml_viewer)

    def setup_status_and_layouts(self):
        # Recipe status bar
        self.recipeStatus = QTextEdit()
        self.recipeStatus.setReadOnly(True)
        self.recipeStatus.setFixedHeight(30)
        self.recipeStatus.setViewportMargins(QMargins(5, 0, 0, 0))
        self.recipeStatus.setStyleSheet("""
            QTextEdit {
                border: none;
                background-color: transparent;
                color: #333;
                font-style: italic;
                font-size: 12pt;
            }
        """)

        # Container for status + tree+yaml
        self.tree_status_container = QWidget()
        self.tree_status_layout = QVBoxLayout(self.tree_status_container)
        self.tree_status_layout.setContentsMargins(0, 0, 0, 0)
        self.tree_status_layout.setSpacing(0)
        self.tree_status_layout.addWidget(self.recipeStatus)
        self.tree_status_layout.addWidget(self.tree_and_yaml_widget)

        # Container for toolbar + status + main content
        self.tree_and_yaml_container = QWidget()
        self.tree_and_yaml_layout = QVBoxLayout(self.tree_and_yaml_container)
        self.tree_and_yaml_layout.setContentsMargins(0, 0, 0, 0)
        self.tree_and_yaml_layout.setSpacing(0)
        self.tree_and_yaml_layout.addWidget(self.toolbar)
        self.tree_and_yaml_layout.addWidget(self.tree_status_container)

        # Watermark widget (your logo)
        self.watermark_widget = WatermarkWidget("../images/CERN_Logo.png")  # Replace with your logo

        # Stacked layout to switch between watermark and main editor
        self.stacked_layout = QStackedLayout()
        self.stacked_layout.addWidget(self.watermark_widget)  # index 0
        self.stacked_layout.addWidget(self.tree_and_yaml_container)  # index 1

        # Log console below everything
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFixedHeight(200)

        # Add layouts to main layout
        self.main_layout.addLayout(self.stacked_layout)
        self.main_layout.addWidget(self.log_console)

# Helper GUI methods - colouring, viewing

    def toggle_dark_mode(self, enabled):
        if enabled:
            self.dark_mode = True
            self.setStyleSheet(dark_style)
            self.yaml_viewer.set_dark_mode(True)
            self.log("🌙 Dark Mode enabled.")
        else:
            self.dark_mode = False
            self.setStyleSheet(light_style)
            self.yaml_viewer.set_dark_mode(False)
            self.log("☀️ Light Mode restored.")

    def highlight_line(self, line_num):
        cursor = self.yaml_viewer.textCursor()

        # Clear any existing selections
        cursor.clearSelection()
        # Move to the specified line
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(line_num):
            cursor.movePosition(QTextCursor.MoveOperation.Down)

        # Select the entire line
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)

        # Apply highlighting
        format = QTextCharFormat()

        self.enable_recipe_verification = False
        cursor.mergeCharFormat(format)
        self.enable_recipe_verification = True

        # Scroll and set cursor position for visibility
        self.yaml_viewer.setCursorPosition(line_num, 0)
        self.yaml_viewer.ensureLineVisible(line_num)
        pass

    def update_yaml_viewer(self):
        self.temporary_recipe_contents = self.sanitize_booleans(self.temporary_recipe_contents)
        self.yaml_viewer.setText(self.temporary_recipe_contents)
    
    def update_yaml_treeview(self):
        """Load YAML documents and populate the sequencer with folders for setup, main, and teardown steps."""
        try:
            self.yaml_documents = list(self.yaml_parser.load_all(self.temporary_recipe_contents))
            if not self.yaml_documents:
                self.log("⚠️ No YAML documents found.")
                self.sequencer.set_yaml_data([])
                return False

            sequencer_steps = []

            # First document → Preamble
            first_doc = self.yaml_documents[0]
            sequencer_steps.append({
                "step_name": "Preamble",
                "description": str(first_doc),
                "steptype": "preamble",
                "_node": first_doc,
                "_id": str(uuid.uuid4())
            })

            # Process remaining documents
            for doc_index, doc in enumerate(self.yaml_documents[1:], start=1):
                sequence_name = doc.get("sequence_name", f"Sequence {doc_index}")
                sequence_block = {
                    "step_name": f"Sequence: {sequence_name}",
                    "description": doc.get("description", ""),
                    "steptype": "sequence_folder",
                    "children": [],
                    "_node": doc,
                    "_doc_index": doc_index,
                    "_id": str(uuid.uuid4())
                }

                def build_folder(folder_name, folder_type, steps_list):
                    """Create a folder dict with child steps."""
                    folder = {
                        "step_name": folder_name,
                        "steptype": folder_type,
                        "children": [],
                        "_node": steps_list,  # original YAML list
                        "_expanded": False
                    }
                    for s in steps_list:
                        if isinstance(s, dict) and s.get("step_name"):
                            folder["children"].append({
                                "step_name": s.get("step_name", "Unnamed Step"),
                                "steptype": s.get("steptype", "unknown"),
                                "_node": s,
                                "_parent": folder_type,
                                "_id": s.get("_id", str(uuid.uuid4()))
                            })
                    return folder

                # Build folders in chronological order: setup → main → teardown
                folders = [
                    build_folder("Setup Steps", "setup_folder", doc.get("setup_steps", [])),
                    build_folder("Main Steps", "main_folder", doc.get("steps", [])),
                    build_folder("Teardown Steps", "teardown_folder", doc.get("teardown_steps", [])),
                ]

                sequence_block["children"].extend(folders)
                sequencer_steps.append(sequence_block)

            self.sequencer.set_yaml_data(sequencer_steps)
            self.sequencer.receive_globals(self.yaml_documents[0].get("globals", {}))
            self.log(f"✅ Sequencer received {len(sequencer_steps)} steps including preamble/setup.")
            return True

        except Exception as e:
            self.log(f"❌ Unexpected error during TreeView update: {e}")
            return False


    def on_sequencer_updated(self, steps):
        """Update the YAML document with the current sequencer order."""
        if len(self.yaml_documents) < 2:
            return
        
        if self.sequencer.updated_preamble_globals:
            yaml_globals = self.yaml_documents[0].get("globals", {})
            yaml_globals.update(self.sequencer.updated_preamble_globals)
            self.yaml_documents[0]["globals"] = yaml_globals
            self.sequencer.receive_globals(yaml_globals)
            self.sequencer.updated_preamble_globals = {}

        doc2 = self.yaml_documents[1]

        # Walk all sequences → update their YAML lists
        for seq_step in steps:
            if seq_step.get("steptype") != "sequence_folder":
                continue

            for folder in seq_step.get("children", []):
                folder_type = folder.get("steptype")
                children_nodes = [child["_node"] for child in folder.get("children", [])]

                if folder_type == "setup_folder":
                    doc2["setup_steps"] = children_nodes
                elif folder_type == "main_folder":
                    doc2["steps"] = children_nodes
                elif folder_type == "teardown_folder":
                    doc2["teardown_steps"] = children_nodes

        # Dump YAML in order: preamble → setup → main → teardown
        from ruamel.yaml import YAML
        import io

        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)
        stream = io.StringIO()
        yaml.dump_all(self.yaml_documents, stream)
        new_yaml = stream.getvalue()

        self.yaml_viewer.setText(new_yaml)
        self.temporary_recipe_contents = new_yaml
        self.log("✅ Sequencer order updated and YAML synced.")


    def set_recipe_status(self, message: str, color: str = "#333"):
        """Sets the status message and text color in the top recipe status field."""
        escaped_message = (
            message.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        self.recipeStatus.setHtml(f'<span style="color: {color};">{escaped_message}</span>')

    def show_recipe_ok(self, message: str = "✅ Recipe is valid"):
        self.set_recipe_status(message, color="green")

    def show_recipe_error(self, message: str):
        self.set_recipe_status(f"❌ {message}", color="red")

    def show_recipe_info(self, message: str):
        self.set_recipe_status(f"ℹ️ {message}", color="gray")

    def on_yaml_cursor_changed(self):
        try:
            cursor = self.yaml_viewer.textCursor()
            current_line = cursor.blockNumber()

            wrapper = self.line_to_item.get(current_line)
            item = wrapper.item if isinstance(wrapper, HashableTreeItem) else wrapper

            if item:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                # self.log(f"🧭 Cursor at line {current_line}, highlighting: {item.text(0)}")
            else:
                # self.log(f"🧭 Cursor at line {current_line}, no matching tree item found.")
                pass
        except Exception as e:
            self.log(f"❌ Error in on_yaml_cursor_changed: {e}")

    # Methods related to handling GUI actions
    def on_action_restore_recipe_clicked(self):
        if self.last_valid_recipe == "":
            self.log("️⚠️ ️Unable to restore, no working version in the history")
            return
        self.temporary_recipe_contents = self.last_valid_recipe
        self.update_yaml_viewer()
        #self.collapse_inside_steps()

    def on_save_as_clicked(self):
        try:
            # Validate recipe
            validation_result, description = self.validate_temporary_recipe_contents()
            if not validation_result:
                if not self.ask_save_invalid_file():
                    self.log("⚠️ Save aborted.")
                    return

        except Exception as e:
            self.log(f"❌ Recipe validation failed: {e}")

        # Open the file dialog for the user to choose the save location
        new_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            self.current_file_path or "",  # start dir
            "YAML Files (*.yaml *.yml);;All Files (*)"
        )

        if not new_path:
            self.log("⚠️ Save aborted, no YAML file selected.")
            return

        try:
            # Extract data from the text view
            try:
                # data = self.extract_treeView_to_data()
                data = self.temporary_recipe_contents
            except Exception as e:
                raise RuntimeError(f"Failed to extract data from the text editor: {e}")
            try:
                base, _ = os.path.splitext(new_path)
                new_path_fixed = f"{base}.yml"
                with open(new_path_fixed, 'w') as f:
                    # yaml.dump_all(data, f, sort_keys=False)
                    f.write(data)
            except Exception as e:
                raise IOError(f"Failed to save YAML file '{new_path_fixed}': {e}")

            # Update UI state and log success
            self.current_file_path = new_path_fixed
            self.save_action.setEnabled(True)
            self.action_save.setEnabled(True)
            self.log(f"💾 Saved to {new_path_fixed}")
            self.setWindowTitle(f"Recipe Editor - {os.path.basename(new_path_fixed)}")

            try:
                self.load_yaml_recipe(new_path_fixed)
            except Exception as e:
                self.log(f"⚠️ Saved but failed to reload: {e}")
        except Exception as e:
            error_message = f"❌ Save failed: {e}"
            self.log(error_message)

    def on_save_clicked(self):
        if not self.current_file_path:
            self.on_save_as_clicked()  # Fallback
            return

        try:
            # Validate recipe
            validation_result, description = self.validate_temporary_recipe_contents()
            if not validation_result:
                if not self.ask_save_invalid_file():
                    self.log("⚠️ Save aborted.")
                    return

            if not self.current_file_path:
                self.log("⚠️ Save aborted, no YAML file selected.")
                return

            # Extract data from text view
            try:
                # data = self.extract_treeView_to_data()
                data = self.temporary_recipe_contents
            except Exception as e:
                raise RuntimeError(f"Failed to extract data from the text view: {e}")

            # Construct filename and write data
            try:
                base, ext = os.path.splitext(self.current_file_path)
                new_path = f"{base}{ext}"
                with open(new_path, 'w') as f:
                    # yaml.dump_all(data, f, sort_keys=False)
                    f.write(data)
            except Exception as e:
                raise IOError(f"Failed to save YAML file '{new_path}': {e}")

            # Log success and reload
            self.log(f"💾 Saved to {new_path}")
            self.setWindowTitle(f"Recipe Editor - {os.path.basename(new_path)}")

            try:
                self.load_yaml_recipe(new_path)
            except Exception as e:
                self.log(f"⚠️ Saved but failed to reload: {e}")
        except Exception as e:
            self.log(f"❌ Save failed: {e}")

    def on_add_clicked(self):
        generator_pop_up = RecipeCreatorApp()
        result = generator_pop_up.open_creator_dialog(self.dark_mode)
        if result == None:
            return

        filename = os.path.basename(self.current_file_path)
        if filename == "":
            self.setWindowTitle(f"Recipe Editor - *unnamed recipe* *unsaved changes*")
        else:
            self.setWindowTitle(f"Recipe Editor - {filename} *unsaved changes*")
        self.close_recipe.setEnabled(True)
        self.action_restore_recipe.setEnabled(True)
        yaml_string = generator_pop_up.get_generated_recipe()
        self.temporary_recipe_contents = yaml_string
        self.update_yaml_viewer()

        # Mark as unsaved
        self.current_file_path = None
        self.stacked_layout.setCurrentIndex(1)

        #self.collapse_inside_steps()

        self.action_save.setEnabled(False)
        self.action_save_as.setEnabled(True)
        self.save_action.setEnabled(False)
        self.save_as_action.setEnabled(True)

    def on_open_wiki_clicked(self):
        url = "https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/master/"
        webbrowser.open(url)

    def on_dev_1_clicked(self):
        self.log("clicked Dev1 tool (no action implemented)")

    def on_dev_2_clicked(self):
        self.log("clicked Dev2 tool (no action implemented)")

    def on_dev_3_clicked(self):
        self.log("clicked Dev3 tool (no action implemented)")

    def on_dev_4_clicked(self):
        self.log("clicked Dev4 tool (no action implemented)")

    def on_open_gitlab_clicked(self):
        url = "https://gitlab.cern.ch/pts/framework/pypts"
        webbrowser.open(url)

    def on_close_recipe_clicked(self):
        #self.tree.clear()
        self.sequencer.clear()
        self.stacked_layout.setCurrentIndex(0)  # Show logo
        self.close_recipe.setEnabled(False)  # 🔒 Disable it - gray out
        self.action_save.setEnabled(False)
        self.action_save_as.setEnabled(False)
        self.save_as_action.setEnabled(False)
        self.save_action.setEnabled(False)

        self.yaml_documents = []
        self.temporary_recipe_contents = ""
        self.last_valid_recipe = ""
        self.current_file_path = ""
        self.setWindowTitle(f"{self.title} recipe editor")
        self.log("️ℹ️ Recipe view cleared.")
        self.reset_recovery_history()

    def on_create_recipe_clicked(self):
        self.log("️ℹ️ Todo: 0.2")

    def on_tree_item_clicked(self, item, column):
        key = HashableTreeItem(item)
        if key in self.item_to_line:
            line = self.item_to_line[key]
            self.highlight_line(line)
        else:
            pass

    def on_treeview_item_changed(self, item, column):
        if self.enable_recipe_verification == True:
            line_info = ""
            line_number = self.item_to_line.get(HashableTreeItem(item))
            if line_number is not None:
                line_info = f" (line {line_number + 1})"  # +1 for human-readable line number

            if item.text(1) == "":
                self.log(f"✏️ Cleared a field...{line_info}")
            else:
                self.log(f"✏️ Recipe in Tree editor updated")

            self.extract_treeView_to_data()
            self.temporary_recipe_contents = self.sanitize_booleans(self.temporary_recipe_contents)
            self.update_yaml_viewer()
            print(self.temporary_recipe_contents)
            result, description = self.validate_yaml_documents()
            if result == True:
                self.show_recipe_ok()
            else:
                self.show_recipe_error("Recipe in Tree Edit View is invalid!")
                self.log(description)
            try:
                filename = ""
                filename = os.path.basename(self.current_file_path)
            except Exception as e:
                pass
            if filename == "":
                self.setWindowTitle(f"Recipe Editor - *unnamed recipe* *unsaved changes*")
            else:
                self.setWindowTitle(f"Recipe Editor - {filename} *unsaved changes*")
        pass

    def on_yamlview_item_changed(self):
        if self.enable_recipe_verification == True:
            try:
                self.temporary_recipe_contents = self.yaml_viewer.toPlainText()
                validation_result, description = self.validate_temporary_recipe_contents()
            except Exception as e:
                self.log(f"❌ Unable to parse YAML contents")
                return
            try:
                if (validation_result == True):
                    self.update_yaml_treeview()
                    self.show_recipe_ok()
                    self.log("✏️️ Recipe in YAML editor updated")
                else:
                    self.show_recipe_error("Recipe in Text Edit View is invalid!")
                    self.log(f"❌ YAML edit failure, the YAML format got corrupted!")

            except Exception as e:
                self.log(f"❌ Could not update the view. {e}")
            try:
                filename = os.path.basename(self.current_file_path)
                if filename == "":
                    self.setWindowTitle(f"Recipe Editor - *unnamed recipe* *unsaved changes*")
                else:
                    self.setWindowTitle(f"Recipe Editor - {filename} *unsaved changes*")
            except Exception as e:
                pass
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_selected_items()
        else:
            super().keyPressEvent(event)
    
# Recipe parsing and processing
    def sanitize_booleans(self, yaml_str: str) -> str:
        sanitized_lines = []

        for line in yaml_str.splitlines():
            # Convert the line to lowercase
            line = line.lower()

            # Remove quotes around 'true' or 'false'
            line = re.sub(r"(['\"])\s*(true|false)\s*\1", r"\2", line)

            sanitized_lines.append(line)

        return "\n".join(sanitized_lines)

    def validate_recipe(self):
        try:
            if (validate_recipe_filepath(self.current_file_path)):
                self.log("✅ Recipe file validated successfully.")
                self.show_recipe_ok()
            else:
                self.log("❌ Recipe file failed the validation!")
                self.show_recipe_error("❌ Recipe file is invalid!")
                return False
        except Exception as e:
            self.sequencer.blockSignals(False)  # Safety catch
            self.log(f"❌ Expception while validating the recipe, recipe might be corrupted.")
            return False

    def validate_yaml_documents(self):
        self.extract_treeView_to_data()
        validation_result = self.validate_temporary_recipe_contents()
        if validation_result == True:
            self.last_valid_recipe = self.temporary_recipe_contents
            self.action_restore_recipe.setEnabled(True)
        return validation_result

    def validate_temporary_recipe_contents(self):
        result, description = validate_recipe_string_variable(self.temporary_recipe_contents)
        if result == True:
            self.last_valid_recipe = self.temporary_recipe_contents
        return result, description

    def open_recipe(self):
        if getattr(self, "current_file_path", None):
            file_path = self.current_file_path
            
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, "Open recipe file", "", "YAML Files (*.yml *.yaml)")
        self.load_yaml_recipe(file_path)
        self.save_as_action.setEnabled(True)
        self.save_action.setEnabled(True)
        self.action_save.setEnabled(True)
        self.action_save_as.setEnabled(True)
        #self.collapse_inside_steps()

        filename = os.path.basename(file_path)
        if filename == "":
            return
        else:
            self.setWindowTitle(f"Recipe Editor - {filename}")

    def reset_recovery_history(self):
        self.last_valid_recipe = ""
        self.action_restore_recipe.setEnabled(False)

    def load_yaml_recipe(self, file_path):
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    raw_text = f.read()
                    self.temporary_recipe_contents = raw_text
                    self.current_file_path = file_path


                self.yaml_parser.preserve_quotes = True

                self.enable_recipe_verification = False
                self.update_yaml_viewer()
                self.update_yaml_treeview()
                self.enable_recipe_verification = True

                self.log(f"✅ Loaded {len(self.yaml_documents)} document(s) from: {file_path}")

                try:
                    self.temporary_recipe_contents = self.yaml_viewer.toPlainText()
                    validation_result, description = self.validate_temporary_recipe_contents()
                    if (validation_result == True):
                        self.show_recipe_ok("✅ Recipe is valid")
                    else:
                        self.show_recipe_error("Opened recipe is invalid!")
                        self.log(description)
                except Exception as e:
                    self.log(f"❌ YAML verification failed, {e}")


                self.stacked_layout.setCurrentIndex(1)
                self.close_recipe.setEnabled(True)  # 🔒 Enable it

            except YAMLError as e:
                #self.tree.blockSignals(False)  # Safety catch
                self.log(f"❌ YAML parse error: {e}")
            #self.collapse_inside_steps()
            QApplication.processEvents()

    def on_steps_reordered(self, parent, start, end, destination, row):
        new_order = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            block = self.list_widget.itemWidget(item)
            step = block.step_data
            step["step_name"] = block.step_name
            new_order.append(step)

        self.steps = new_order
        if callable(self.yaml_update_callback):
            self.yaml_update_callback(self.steps)


    def extract_treeView_to_data(self):
        documents = []
        for i in range(self.tree.topLevelItemCount()):
            doc_item = self.tree.topLevelItem(i)
            data = self.extract_item_data(doc_item)

            doc_item = self.strip_star_prefix(doc_item)
            data = self.strip_star_prefix(data)

            # Sanitize empty strings to empty dicts for specific keys
            data = self.sanitize_empty_fields(data)

            documents.append(data)

        buffer = io.StringIO()
        yaml.dump_all(documents, buffer, sort_keys=False)
        yaml_string = buffer.getvalue()
        buffer.close()
        self.temporary_recipe_contents = yaml_string
        self.temporary_recipe_contents = self.sanitize_booleans(self.temporary_recipe_contents)
        return documents

    def extract_item_data(self, item):
        if item.childCount() == 0:
            text = item.text(1)
            # Try to infer empty dict or list from context
            if text == '':
                # Try to guess from the key
                key = item.text(0).strip().lower()
                if key in ('globals'):
                    return {}  # known dict-like keys
                elif key.endswith('steps') or key.endswith('teardown_steps') or key.endswith('setup_steps'):
                    return []  # likely list-like
            return text
        # Check if it's a list (e.g. keys like [0], [1])
        is_list = all(item.child(j).text(0).startswith("[") for j in range(item.childCount()))
        if is_list:
            return [self.extract_item_data(item.child(j)) for j in range(item.childCount())]
        else:
            result = {}
            for j in range(item.childCount()):
                key = item.child(j).text(0)
                value = self.extract_item_data(item.child(j))
                result[key] = value
            return result

    def delete_selected_items(self):
        selected_items = self.tree.selectedItems()

        for item in selected_items:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                # Top-level item
                index = self.indexOfTopLevelItem(item)
                self.takeTopLevelItem(index)
            # Manually trigger the handler after deletion
            self.on_treeview_item_changed(item, 0)

    def sanitize_empty_fields(self, data: dict) -> dict:
        # For RECIPE_HEADER_REQUIRED_FIELDS, force "globals" to be dict if empty string
        if "globals" in data and (data["globals"] == "" or data["globals"] is None):
            data["globals"] = {}

        # For sequences inside main_sequence or others, you can add similar logic:
        seq_fields = ["setup_steps", "steps", "teardown_steps"]
        for seq in seq_fields:
            if seq in data and (data[seq] == "" or data[seq] is None):
                data[seq] = []

        # Similarly for dict fields in sequence:
        dict_fields = ["parameters", "outputs", "locals", "input_mapping", "output_mapping"]
        for dfield in dict_fields:
            if dfield in data and (data[dfield] == "" or data[dfield] is None):
                data[dfield] = {}

        return data

# Misc
    def log(self, message: str):
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.log_console.append(f"[{timestamp}] {message}")

    def ask_save_invalid_file(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Save Corrupted Recipe")
        msg.setText("The recipe content is invalid.\n"
                    "Do you want to save it anyway?\n "
                    "The contents of the Text View (right) would be saved.")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)

        # Force button text color to black
        msg.setStyleSheet("""
            QPushButton {
                color: black;
            }
        """)

        ret = msg.exec()

        if ret == QMessageBox.Yes:
            return True
        else:
            return False

    def strip_star_prefix(self, data):
        if isinstance(data, str):
            if data.startswith("* "):
                return data[2:]
            return data
        elif isinstance(data, list):
            return [self.strip_star_prefix(item) for item in data]
        elif isinstance(data, dict):
            return {self.strip_star_prefix(k): self.strip_star_prefix(v) for k, v in data.items()}
        else:
            # Other types (int, float, bool, None, etc) returned as is
            return data


# done 0.1 - VIEWER
# done 0.1 - Show some indicator that the changes are unsaved
# done 0.1 - allow to clear any field
# done 0.1 - indicate optional and required fields (with star?)
# done 0.1 - gray out save option if recipe is not opened
# done 0.1 - add button to automatically verify the recipe
# done 0.1 - right-hand side panel with descriptions on the selected field
# done 0.1 - Expert live view of the yaml file on the right hand side panel
# done 0.1 - on the log, show which line of the yaml was edited
# done 0.1 - Bugfix - make the right panel read only
# done 0.1 - Clear view shall be grayed if the view is already cleared (logo visible)
# done 0.1 - 1.0 unit tests

# done 0.2 - GENERATION, EDITING, PARTIAL SUPPORT
# done 0.2 - allow saving
# done 0.2 - allow editing on the tree-view panel
# done 0.2 - allow editing on the yaml-editing panel
# done 0.2 - auto-verification on save, pop-up confirming save, when verification fails
# done 0.2 - add <save as> option
# done 0.2 - add CTRL+S shortcut
# done 0.2 - add recipe status indicator (only to show the current recipe state), inform if the treeview is not updated.
# done 0.2 - button toolbox to allow editing (just add few buttons and design the helper GUI)
# done 0.2 - add auto-conversion flag and disable it when the yaml have errors
# done 0.2 - add button allowing to revert to the last valid format (recreate last working state)
# done 0.2 - allow deletion of the whole steps
# done 0.2 - allow deletion of the whole sequences
# done 0.2 - print the faults found in recipe verification - on the status bar in the bottom
# done 0.2 - mark the text on red only if required + is not filled
# done 0.2 - allow full control over the YAML editor
# done 0.2 - bugfixing, unittests

# done 1.0 - Create new recipe
# done 1.0 - fix the small gui imperfections
# done 1.0 - Some gui and UX improvements
# done 1.0 - Create new recipe from the template
# done 1.0 - create a new helper file recipe_rules.py, where we can have yaml field type descriptions etc
# done 1.0 - Recipe interactive generator - one sequence, multiple steps
# done 1.0 - increase 1st column size
# done 1.0 - easy way to set the YamView application
# done 1.0 - change the required field to be a star or warning emoji, instead of red colour
# done 1.0 - check if it possible to fold only selected branches
# done 1.0 - bugfix - do not close previous recipe on cancelling the add_new
# done 1.0 - point automatically to the tree view on the yaml editor click
# done 1.0 - bugfix - fix the exceptions so they are parsed instead of shown
# done 1.0 - bugfix - exception on YAML edit failure
# done 1.0 - bugfix - if recipe is not saved, (just generated) we cannot close it
# done 1.0 - bugfix - if there is opened template recipe, trying to open and close, the title is wrong (try to reproduce first)
# done 1.0 - bugfix - title not updated on close recipe click
# done 1.0 - bugfix - invalid cleaning application state on close recipe click
# done 1.0 - bugfix - ask for saving invalid recipe in save as, the same way as save
# done 1.0 - bugfix - ensure, that the textview is saved
# done 1.0 - 1.0 unit tests

# todo fix the module recognition, so we expect either file, path or name


# todo 1.1 - if i delete whole recipe - its valid - well shout not be
# todo 1.1 - database of valid recipes
# todo 1.1 - include more information about what is missing in the structure
# todo 1.1 - bug [17/07/2025 12:00:41] ❌ Error in on_yaml_cursor_changed: Internal C++ object (PySide6.QtWidgets.QTreeWidgetItem) already deleted.
# todo 1.1 - generate the steps, but also have a way to recreate from template, based on instrument used or test type
# todo 1.1 - test with whitespaces, cross platform compatibility
# todo 1.1 - UX REFINEMENT
# todo 1.1 - Add possibility to open recent files
# todo 1.1 - Handle possibility that the recent file is not present anymore
# todo 1.1 - Add parsing of the recipe_version field and inform if the recipe is up to correct version
# todo 1.1 - Add recipe config file, where we can track the version (and maybe something more later)
# todo 1.1 - Bugfix - sometimes after opening new recipe for editing, the GUI is not refreshing (it does after clicking on the window)
# todo 1.1 - 1.1 unit tests
# todo 1.1 - autocomplete or helper to write down the tests

# todo 1.2 - FULL SUPPORT
# todo 1.2 - creator - number of sequences, steps etc
# todo 1.2 - all fields programatically described in the yaml_description.py helper file
# todo 1.2 - clean up documentation
# todo 1.2 - add drop down lists on the treeview
# todo 1.2 - refined way of generating the recipe - the tree yaml view is not too intuitive

# todo 2.0 - AI based yaml generation based on prompt (answers to fixed questions - how many sequences, how many steps etc)

# todo 3.0 - check possibility to generate the recipe from the test plan

# Nice features to show in 1.0:
# Shortcuts - redo, undo,
# YAML parser - if I put some undefined globals, it will define it for me
# Automatic recipe recovery
# Automatic cross-verification
# Verification on save, save as
# Unsaved changes
# Generate from the template


if __name__ == "__main__":
    
    app = QApplication(sys.argv)
    window = RecipeEditorMainMenu()

    window.show()

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        window.current_file_path = file_path
        print("Loaded a recipe from gui")
        window.open_recipe()

    sys.exit(app.exec())
