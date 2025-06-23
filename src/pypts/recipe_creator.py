from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QLabel,
    QPushButton,
    QFileDialog,
    QToolBar,
    QStyle,
    QScrollArea,
    QPlainTextEdit,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPixmap,
    QPainter,
    QTextCursor,
    QTextCharFormat,
)
from PySide6.QtCore import QSize, Qt
# from PyQt5.Qsci import QsciScintilla, QsciLexerYAML
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.compat import StringIO
from datetime import datetime
import sys
import webbrowser
import yaml
from pypts.styles import *
from pypts.rules import RECIPE_HEADER_REQUIRED_FIELDS, RECIPE_SEQUENCE_REQUIRED_FIELDS, STEP_REQUIRED_FIELDS
from pypts.verify_recipe import *

class ScintillaYamlEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Basic editor setup
        font = QFont("Courier", 10)
        self.setFont(font)
        
        # For compatibility with original QsciScintilla interface
        self.length = lambda: len(self.toPlainText())
        
    def setText(self, text):
        # Compatibility method for QsciScintilla
        self.setPlainText(text)
        
    def SendScintilla(self, *args):
        # Stub for QsciScintilla compatibility
        pass
        
    def positionFromLineIndex(self, line_num, index):
        # Simple implementation for basic functionality
        lines = self.toPlainText().split('\n')
        if line_num < len(lines):
            pos = sum(len(line) + 1 for line in lines[:line_num]) + index
            return pos
        return 0
        
    def text(self, line_num):
        # Return text of specific line
        lines = self.toPlainText().split('\n')
        if line_num < len(lines):
            return lines[line_num]
        return ""
        
    def setCursorPosition(self, line_num, col):
        # Set cursor to specific line and column
        lines = self.toPlainText().split('\n')
        if line_num < len(lines):
            pos = sum(len(line) + 1 for line in lines[:line_num]) + col
            cursor = self.textCursor()
            cursor.setPosition(pos)
            self.setTextCursor(cursor)
            
    def ensureLineVisible(self, line_num):
        # Make sure line is visible (stub implementation)
        pass

class WatermarkWidget(QWidget):
    """Widget showing a watermark image in the center."""
    def __init__(self, image_path: str):
        super().__init__()
        self.image_path = image_path
        self.pixmap = QPixmap(image_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(0.2)
        x = (self.width() - self.pixmap.width()) // 2
        y = (self.height() - self.pixmap.height()) // 2
        painter.drawPixmap(x, y, self.pixmap)

class HashableTreeItem:
    def __init__(self, item):
        self.item = item

    def __hash__(self):
        return id(self.item)

    def __eq__(self, other):
        return isinstance(other, HashableTreeItem) and self.item is other.item

class YamlTreeEditor(QMainWindow):
# Methods related to initialization and set up of GUI
    def __init__(self):
        super().__init__()
        self.yaml_documents = []  # Store parsed YAML data (necessary for runtime cache)
        self.current_file_path = ""  # Track original file path (necessary for saving)
        self.item_to_line = {}
        self.yaml_parser = None
        self.data = None

        self.setWindowTitle("Recipe Editor")
        self.setGeometry(200, 200, 1600, 1000)

        self.setup_menu()
        self.setStyleSheet(light_style)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # main application layout
        self.main_layout = QVBoxLayout(self.central_widget)

        # Stacked layout (watermark + YAML tree)
        self.stacked_layout = QStackedLayout()

        # Watermark logo on the back
        self.watermark_widget = WatermarkWidget("logo.png")  # <-- place your transparent logo here

        # yaml table widget
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Field", "Value"])
        self.tree.setColumnWidth(0, 200)  # Fix width of the "Field" column
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)

        # defining the yaml overview widget
        self.yaml_viewer = ScintillaYamlEditor(self)
        self.yaml_viewer.setReadOnly(True)

        # Create container widget for tree + yaml
        self.tree_and_yaml_widget = QWidget()
        self.tree_and_yaml_hlayout = QHBoxLayout(self.tree_and_yaml_widget)
        self.tree_and_yaml_hlayout.addWidget(self.tree)
        self.tree_and_yaml_hlayout.addWidget(self.yaml_viewer)

        # Create toolbar
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(16, 16))  # small icons
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        # Example buttons for the toolbar
        action_refresh = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Validate recipe", self)
        action_save = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "Save", self)
        action_add = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), "Add", self)

        # Add actions to toolbar
        self.toolbar.addAction(action_refresh)
        self.toolbar.addAction(action_save)
        self.toolbar.addAction(action_add)

        # Connect buttons if needed
        action_refresh.triggered.connect(self.on_revalidate_clicked)
        action_save.triggered.connect(self.on_save_clicked)
        action_add.triggered.connect(self.on_add_clicked)

        # Create a vertical layout container for toolbar + tree_and_yaml_widget
        self.tree_and_yaml_container = QWidget()
        self.tree_and_yaml_layout = QVBoxLayout(self.tree_and_yaml_container)
        self.tree_and_yaml_layout.setContentsMargins(0, 0, 0, 0)
        self.tree_and_yaml_layout.setSpacing(2)
        self.tree_and_yaml_layout.addWidget(self.toolbar)
        self.tree_and_yaml_layout.addWidget(self.tree_and_yaml_widget)

        # Placing widgets into the stacked layout
        self.stacked_layout.addWidget(self.watermark_widget)  # index 0
        self.stacked_layout.addWidget(self.tree_and_yaml_container)  # index 1

        # Defining log console (multi-line status output)
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFixedHeight(120)

        self.main_layout.addLayout(self.stacked_layout)
        # below the stacked layout there is a status bar
        self.main_layout.addWidget(self.log_console)

        self.log("Application started 👍")

    def setup_menu(self):
        menubar = self.menuBar()

        self.file_menu = menubar.addMenu("File")
        self.open_gitlab = QAction("Open Recipe", self)
        self.open_gitlab.triggered.connect(self.load_yaml_path)
        self.file_menu.addAction(self.open_gitlab)
        self.close_recipe = QAction("Close Recipe", self)
        self.close_recipe.triggered.connect(self.on_close_recipe_clicked)
        self.close_recipe.setEnabled(False)  # 🔒 Disable it (gray out)
        self.file_menu.addAction(self.close_recipe)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = menubar.addMenu("Edit")
        self.save_action = QAction("Save Recipe", self)
        self.save_action.triggered.connect(self.on_save_recipe_clicked)
        self.edit_menu.addAction(self.save_action)

        self.view_menu = menubar.addMenu("View")
        self.toggle_dark_mode_action = QAction("Toggle Dark Mode", self)
        self.toggle_dark_mode_action.setCheckable(True)
        self.toggle_dark_mode_action.triggered.connect(self.toggle_dark_mode)
        self.view_menu.addAction(self.toggle_dark_mode_action)

        self.about_menu = menubar.addMenu("About")
        self.open_gitlab = QAction("Gitlab", self)
        self.open_gitlab.triggered.connect(self.on_open_gitlab_clicked)
        self.about_menu.addAction(self.open_gitlab)
        self.open_wiki = QAction("Wiki", self)
        self.open_wiki.triggered.connect(self.on_open_wiki_clicked)
        self.about_menu.addAction(self.open_wiki)

        self.dev_menu = menubar.addMenu("Development")

# Helper GUI functions - colouring, viewing
    def mark_required_field(self, tree_item, is_required: bool):
        if is_required:
            # Append star
            original_text = tree_item.text(0)

            tree_item.setForeground(0, QColor(210, 40, 0))  # orange star
            # if "★" not in original_text:
            #     tree_item.setText(0, "★ " + original_text)
        else:
            pass

    def toggle_dark_mode(self, enabled):
        if enabled:
            self.setStyleSheet(dark_style)
            self.log("🌙 Dark Mode enabled.")
        else:
            self.setStyleSheet(light_style)
            self.log("☀️ Light Mode restored.")

    def highlight_line(self, line_num):
        # Simple highlighting for QPlainTextEdit
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
        format.setBackground(QColor(220, 220, 255))  # Light blue background
        cursor.mergeCharFormat(format)
        
        # Set cursor position for visibility
        self.yaml_viewer.setCursorPosition(line_num, 0)

# Methods related to handling actions
    def on_revalidate_clicked(self):
        self.validate_recipe()

    def on_save_clicked(self):
        self.log("Save clicked (not implemented yet)")

    def on_add_clicked(self):
        self.log("Add clicked (not implemented yet)")

    def on_open_wiki_clicked(self):
        url = "https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/master/"
        webbrowser.open(url)

    def on_open_gitlab_clicked(self):
        url = "https://gitlab.cern.ch/pts/framework/pypts"
        webbrowser.open(url)

    def on_close_recipe_clicked(self):
        self.tree.clear()
        self.stacked_layout.setCurrentIndex(0)  # Show logo
        self.close_recipe.setEnabled(False)  # 🔒 Disable it - gray out
        self.log("🧹 Recipe view cleared.")

    def on_save_recipe_clicked(self):
        if not self.current_file_path:
            self.log("❌ No YAML file loaded.")
            return
        try:
            data = self.extract_treeView_to_data()
            return True
            with open(self.current_file_path, 'w') as f:
                yaml.dump_all(data, f, sort_keys=False)
            self.log(f"💾 Saved to {self.current_file_path}")
            self.setWindowTitle("Recipe Editor")
        except Exception as e:
            self.log(f"❌ Failed to save: {e}")

    def on_create_recipe_clicked(self):
        self.log("Todo: 1.1")

    def on_tree_item_clicked(self, item, column):
        key = HashableTreeItem(item)
        if key in self.item_to_line:
            line = self.item_to_line[key]
            self.highlight_line(line)
        else:
            pass

    def on_item_changed(self, item, column):
        line_info = ""
        line_number = self.item_to_line.get(HashableTreeItem(item))
        if line_number is not None:
            line_info = f" (line {line_number + 1})"  # +1 for human-readable line number

        if item.text(1) == "":
            self.log(f"✏️ Cleared a field...{line_info}")
        else:
            self.log(f"✏️ Edited: {item.text(1)}{line_info}")

        self.setWindowTitle("Recipe Editor *unsaved changes*")

# Recipe handling
    def validate_recipe(self):
        try:
            if (validate_recipe(self.current_file_path)):
                self.log("✅ Recipe file validated successfully.")
            else:
                self.log("❌ Summary: Recipe file failed the validation!")
        except Exception as e:
            self.tree.blockSignals(False)  # Safety catch
            self.log(f"❌ Unhandled expception while validating the recipe: {e}")

    def load_yaml_path(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open recipe file", "", "YAML Files (*.yml *.yaml)")
        self.load_yaml(file_path)

    def load_yaml(self, file_path):
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    raw_text = f.read()

                self.current_file_path = file_path
                self.yaml_viewer.setText(raw_text)

                self.yaml_parser = YAML()
                self.yaml_parser.preserve_quotes = True
                self.yaml_documents = list(self.yaml_parser.load_all(raw_text))

                self.tree.blockSignals(True)  # ⛔ Block signals while populating
                self.tree.clear()
                self.item_to_line.clear()  # Clear previous mappings

                for idx, doc in enumerate(self.yaml_documents):
                    doc_root = QTreeWidgetItem([f"Document {idx + 1}"])
                    self.tree.addTopLevelItem(doc_root)
                    self.populate_tree(doc, doc_root)
                    doc_root.setExpanded(True)

                self.tree.blockSignals(False)  # ✅ Re-enable signals

                self.stacked_layout.setCurrentIndex(1)
                self.close_recipe.setEnabled(True)  # 🔒 Enable it
                self.log(f"✅ Loaded {len(self.yaml_documents)} document(s) from: {file_path}")

            except YAMLError as e:
                self.tree.blockSignals(False)  # Safety catch
                self.log(f"❌ YAML parse error: {e}")
            QApplication.processEvents()
            self.validate_recipe()

    def populate_tree(self, data, parent_item, path=()):
        from ruamel.yaml.comments import CommentedMap, CommentedSeq

        if isinstance(data, CommentedMap):
            # Determine context to select required fields list
            context_required_fields = set()

            if path == ():  # Top-level document
                context_required_fields = set(RECIPE_HEADER_REQUIRED_FIELDS)
            elif path and path[-1] == "steps":
                pass  # The "steps" key contains a list — children are handled separately
            elif path and isinstance(path[-1], int):
                # We are inside a step dictionary
                step_dict = data
                steptype = step_dict.get("steptype")
                if steptype == "UserInteractionStep":
                    context_required_fields = {"steptype", "step_name", "description"}
                elif steptype == "WaitStep":
                    context_required_fields = {"steptype", "step_name", "description"}
                else:
                    context_required_fields = {"steptype", "step_name", "action_type", "module", "method_name"}

            for key, value in data.items():
                # Show scalar values in the second column
                if isinstance(value, (str, int, float, bool, type(None))):
                    child_item = QTreeWidgetItem(parent_item, [str(key), str(value)])
                else:
                    child_item = QTreeWidgetItem(parent_item, [str(key), ""])
                parent_item.addChild(child_item)

                # Store line number if available
                line_number = None
                if hasattr(data, 'lc'):
                    try:
                        line_info = data.lc.key(key)
                        if line_info is not None:
                            line_number = line_info[0]
                    except Exception:
                        pass
                if line_number is not None:
                    self.item_to_line[HashableTreeItem(child_item)] = line_number

                # Mark required field
                is_required = key in context_required_fields
                self.mark_required_field(child_item, is_required)

                # Recurse for nested structures
                if not isinstance(value, (str, int, float, bool, type(None))):
                    self.populate_tree(value, child_item, path + (key,))

        elif isinstance(data, CommentedSeq):
            for idx, value in enumerate(data):
                child_item = QTreeWidgetItem(parent_item, [f"[{idx}]", ""])
                parent_item.addChild(child_item)

                # Line number for sequence item
                line_number = None
                if hasattr(data, 'lc'):
                    try:
                        line_info = data.lc.item(idx)
                        if line_info is not None:
                            line_number = line_info[0]
                    except Exception:
                        pass
                if line_number is not None:
                    self.item_to_line[HashableTreeItem(child_item)] = line_number

                self.populate_tree(value, child_item, path + (idx,))

        else:
            # Scalar value directly under a sequence or map
            leaf_item = QTreeWidgetItem(parent_item, [str(data), ""])
            parent_item.addChild(leaf_item)

        # Expand all items after population
        self.tree.expandAll()

    def extract_treeView_to_data(self):
        documents = []
        for i in range(self.tree.topLevelItemCount()):
            doc_item = self.tree.topLevelItem(i)
            data = self.extract_item_data(doc_item)
            documents.append(data)
        return documents

    def extract_item_data(self, item):
        if item.childCount() == 0:
            return item.text(1)  # Leaf node: return value
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

# Misc
    def log(self, message: str):
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.log_console.append(f"[{timestamp}] {message}")


#done 1.0 - VIEWER
#done 1.0 - Show some indicator that the changes are unsaved
#done 1.0 - allow to clear any field
#done 1.0 - indicate optional and required fields (with star?)
#done 1.0 - gray out save option if recipe is not opened
#done 1.0 - add button to automatically verify the recipe
#done 1.0 - right-hand side panel with descriptions on the selected field
#done 1.0 - Expert live view of the yaml file on the right hand side panel
#done 1.0 - on the log, show which line of the yaml was edited
#done 1.0 - Bugfix - make the right panel read only
#done 1.0 - Clear view shall be grayed if the view is already cleared (logo visible)
#done 1.0 - 1.0 unit tests

#todo 1.1 - GENERATION, EDITING, PARTIAL SUPPORT
#todo 1.1 - allow saving
#todo 1.1 - button toolbox to allow editing (just add few buttons and design the helper GUI)
#todo 1.1 - Create new recipe, ask for its name
#todo 1.1 - create a new helper file yaml_description.py, where we can have yaml field type descriptions etc
#todo 1.1 - Recipe generator
#todo 1.1 - Populate generator with headers
#todo 1.1 - Ask how many sequences to make
#todo 1.1 - Step generator
#todo 1.1 - allow deletion of the whole steps
#todo 1.1 - allow deletion of the whole sequences
#todo 1.1 - 1.1 unit tests

#todo 1.2 - UX REFINEMENT
#todo 1.2 - Add possibility to open recent files
#todo 1.2 - Handle possibility that the recent file is not present anymore
#todo 1.2 - Add parsing of the recipe_version fieldand inform if the recipe is up to correct version
#todo 1.2 - increase 1st column size
#todo 1.2 - Bugfix - sometimes after opening new recipe for editing, the GUI is not refreshing (it does after clicking on the window)
#todo 1.2 - 1.2 unit tests

#todo 1.3 - FULL SUPPORT
#todo 1.3 - creator - number of sequences, steps etc
#todo 1.3 - all fields programatically described in the yaml_description.py helper file
#todo 1.3 - clean up documentation

#todo 2.0 - AI based yaml generation based on prompt (answers to fixed questions)

#todo 3.0 - check possibility to generate the recipe from test plan using AI

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YamlTreeEditor()

    window.show()
    # automation - adding the automatic recipe opening
        # file_path="/home/pts/dev/pypts/src/pypts/recipes/simple_recipe.yml"
        # window.load_yaml(file_path)
    sys.exit(app.exec())


# from ruamel.yaml import YAML
# from ruamel.yaml.error import YAMLError
#
# def save_yaml(self, file_path=None):
#     if file_path is None:
#         file_path = self.current_file_path
#
#     if file_path and self.yaml_documents:
#         try:
#             yaml_writer = YAML()
#             yaml_writer.preserve_quotes = True
#             yaml_writer.width = 4096  # prevent auto line wrapping
#             yaml_writer.indent(mapping=2, sequence=4, offset=2)
#
#             with open(file_path, 'w') as f:
#                 yaml_writer.dump_all(self.yaml_documents, f)
#
#             self.log(f"✅ YAML saved to: {file_path}")
#         except YAMLError as e:
#             self.log(f"❌ YAML write error: {e}")
