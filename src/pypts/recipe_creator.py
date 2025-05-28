from PyQt6.Qsci import QsciScintilla, QsciLexerYAML
from PyQt6.QtGui import QColor, QFont

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
from datetime import datetime
import webbrowser
import yaml
from PyQt6.QtGui import QAction ,QTextCursor, QTextCharFormat, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QLabel, QStackedLayout, QScrollArea, QPlainTextEdit
)
from PyQt6.QtGui import QPixmap, QPainter
from PyQt6.QtCore import Qt
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtGui import QFont, QColor
from PyQt6.Qsci import QsciScintilla, QsciLexerYAML
from styles import *
from ruamel.yaml import YAML

class ScintillaYamlEditor(QsciScintilla):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Basic editor setup
        self.setUtf8(True)
        self.setMarginsFont(QFont("Courier", 10))
        self.setMarginWidth(0, "0000")  # Line number margin
        self.setMarginLineNumbers(0, True)

        # Highlight the current line
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#e6f7ff"))

        # Font and syntax highlighting
        font = QFont("Courier", 10)
        self.setFont(font)
        self.setMarginsFont(font)

        lexer = QsciLexerYAML()
        lexer.setFont(font)
        self.setLexer(lexer)

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
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)

        # defining the yaml overview widget
        self.yaml_viewer = QPlainTextEdit()
        self.yaml_viewer.setReadOnly(True)

        self.yaml_viewer = ScintillaYamlEditor(self)

        # Create container widget for tree + yaml
        self.tree_and_yaml_widget = QWidget()
        self.tree_and_yaml_layout = QHBoxLayout(self.tree_and_yaml_widget)
        self.tree_and_yaml_layout.addWidget(self.tree)
        self.tree_and_yaml_layout.addWidget(self.yaml_viewer)

        # Placing widgets into the stacked layout
        self.stacked_layout.addWidget(self.watermark_widget)        # index 0
        self.stacked_layout.addWidget(self.tree_and_yaml_widget)    # index 1

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
        self.open_action = QAction("Open Recipe", self)
        self.open_action.triggered.connect(self.load_yaml_path)
        self.file_menu.addAction(self.open_action)
        self.clean_action = QAction("Clear view", self)
        self.clean_action.triggered.connect(self.clear_yaml)
        self.clean_action.setEnabled(False)  # 🔒 Disable it (gray out)
        self.file_menu.addAction(self.clean_action)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = menubar.addMenu("Edit")
        self.edit_action = QAction("Save Recipe", self)
        self.edit_action.triggered.connect(self.save_yaml)
        self.edit_menu.addAction(self.edit_action)

        self.view_menu = menubar.addMenu("View")
        self.toggle_dark_mode_action = QAction("Toggle Dark Mode", self)
        self.toggle_dark_mode_action.setCheckable(True)
        self.toggle_dark_mode_action.triggered.connect(self.toggle_dark_mode)
        self.view_menu.addAction(self.toggle_dark_mode_action)

        self.about_menu = menubar.addMenu("About")
        self.open_action = QAction("Gitlab", self)
        self.open_action.triggered.connect(self.open_gitlab)
        self.about_menu.addAction(self.open_action)
        self.open_action = QAction("Wiki", self)
        self.open_action.triggered.connect(self.open_wiki)
        self.about_menu.addAction(self.open_action)

        self.dev_menu = menubar.addMenu("Development")

    def toggle_dark_mode(self, enabled):
        if enabled:
            self.setStyleSheet(dark_style)
            self.log("🌙 Dark Mode enabled.")
        else:
            self.setStyleSheet(light_style)
            self.log("☀️ Light Mode restored.")

    def open_wiki(self):
        url = "https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/master/"
        webbrowser.open(url)

    def open_gitlab(self):
        url = "https://gitlab.cern.ch/pts/framework/pypts"
        webbrowser.open(url)

    def log(self, message: str):
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.log_console.append(f"[{timestamp}] {message}")

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

                self.tree.clear()
                self.item_to_line.clear()  # Clear previous mappings

                for idx, doc in enumerate(self.yaml_documents):
                    doc_root = QTreeWidgetItem([f"Document {idx + 1}"])
                    self.tree.addTopLevelItem(doc_root)
                    self.populate_tree(doc, doc_root)
                    doc_root.setExpanded(True)

                self.stacked_layout.setCurrentIndex(1)
                self.clean_action.setEnabled(True)  # 🔒 Enable it
                self.log(f"✅ Loaded {len(self.yaml_documents)} document(s) from: {file_path}")

            except YAMLError as e:
                self.log(f"❌ YAML parse error: {e}")

    def clear_yaml(self):
        self.tree.clear()
        self.stacked_layout.setCurrentIndex(0)  # Show logo
        self.clean_action.setEnabled(False)  # 🔒 Disable it - gray out
        self.log("🧹 Recipe view cleared.")

    def save_yaml(self):
        if not self.current_file_path:
            self.log("❌ No YAML file loaded.")
            return
        try:
            data = self.extract_tree_to_data()
            print(data)
            return True
            with open(self.current_file_path, 'w') as f:
                yaml.dump_all(data, f, sort_keys=False)
            self.log(f"💾 Saved to {self.current_file_path}")
            self.setWindowTitle("Recipe Editor")
        except Exception as e:
            self.log(f"❌ Failed to save: {e}")

    def create_yaml(self):
        self.log("Todo: 1.1")

    def highlight_line(self, line_num):
        # Clear previous highlights
        self.yaml_viewer.SendScintilla(self.yaml_viewer.SCI_INDICATORCLEARRANGE, 0, self.yaml_viewer.length())

        # Set indicator 0
        self.yaml_viewer.SendScintilla(self.yaml_viewer.SCI_SETINDICATORCURRENT, 0)

        # Use FULLBOX to fill the entire line background (no border, just fill)
        self.yaml_viewer.SendScintilla(self.yaml_viewer.SCI_INDICSETSTYLE, 0, QsciScintilla.INDIC_FULLBOX)

        highlight_color = QColor(100, 0, 255)
        self.yaml_viewer.SendScintilla(self.yaml_viewer.SCI_INDICSETFORE, 0, highlight_color.rgb())

        # Highlight the full line from line start to line end including newline
        start_pos = self.yaml_viewer.positionFromLineIndex(line_num, 0)
        line_length = len(self.yaml_viewer.text(line_num))

        self.yaml_viewer.SendScintilla(self.yaml_viewer.SCI_INDICATORFILLRANGE, start_pos, line_length)

        # Scroll and set cursor position for visibility
        self.yaml_viewer.setCursorPosition(line_num, 0)
        self.yaml_viewer.ensureLineVisible(line_num)

    def on_tree_item_clicked(self, item, column):
        key = HashableTreeItem(item)
        if key in self.item_to_line:
            line = self.item_to_line[key]
            self.highlight_line(line)
        else:
            print("Item not found in item_to_line mapping.")

    def populate_tree(self, data, parent_item):
        if isinstance(data, CommentedMap):
            for key, value in data.items():
                child_item = QTreeWidgetItem(parent_item, [str(key)])
                parent_item.addChild(child_item)

                # Try to get line number for this key
                line_number = None
                if hasattr(data, 'lc'):
                    try:
                        # lc.key returns (line, col) for key
                        line_info = data.lc.key(key)
                        if line_info is not None:
                            line_number = line_info[0]  # line number is the first element
                    except Exception:
                        pass

                if line_number is not None:
                    self.item_to_line[HashableTreeItem(child_item)] = line_number

                # Recursively populate children
                self.populate_tree(value, child_item)

        elif isinstance(data, CommentedSeq):
            for idx, value in enumerate(data):
                child_item = QTreeWidgetItem(parent_item, [f"[{idx}]"])
                parent_item.addChild(child_item)

                line_number = None
                if hasattr(data, 'lc'):
                    try:
                        # For sequences, lc.item(idx) returns (line, col)
                        line_info = data.lc.item(idx)
                        if line_info is not None:
                            line_number = line_info[0]
                    except Exception:
                        pass

                if line_number is not None:
                    self.item_to_line[HashableTreeItem(child_item)] = line_number

                self.populate_tree(value, child_item)

        else:
            # For scalar values, just add as a leaf node
            leaf_item = QTreeWidgetItem(parent_item, [str(data)])
            parent_item.addChild(leaf_item)

            # Scalars don't have children, but can have line info
            line_number = None
            if hasattr(data, 'lc'):
                # Usually scalars inside sequences or mappings won't have lc,
                # but just in case - you could check or skip here
                pass
            # Optionally store line info if applicable here

    def on_item_changed(self, item, column):
        if (item.text(1)) == "":
            self.log(f"✏️ Cleared a field...")
        else:
            self.log(f"✏️ Edited:  {item.text(1)}")
        self.setWindowTitle("Recipe Editor *unsaved changes*")

    def extract_tree_to_data(self):
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

#todo 1.0 - SIMPLE EDITOR
#done 1.0 - Show some indicator that the changes are unsaved
#done 1.0 - allow to clear any field
#todo 1.0 - indicate optional and required fields (with star?)
#done 1.0 - gray out save option if recipe is not opened
#todo 1.0 - allow saving
#todo 1.0 - add button to automatically verify the recipe
#done 1.0 - right-hand side panel with descriptions on the selected field
#done 1.0 - Expert live view of the yaml file on the right hand side panel
#todo 1.0 - on the log, show which line of the yaml was edited
#todo 1.0 - Bugfix - make the right panel read only
#todo 1.0 - 1.0 unit tests

#todo 1.1 - GENERATION, PARTIAL SUPPORT
#todo 1.1 - button toolbox to allow editing (just add few buttons and design the helper GUI)
#todo 1.1 - Create new recipe, ask for its name
#todo 1.1 - create a new helper file yaml_description.py, where we can have yaml field type descriptions etc
#todo 1.1 - Recipe generator
#todo 1.1 - Populate it with header
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
#todo 1.2 - Clear view shall be grayed if the view is already cleared (logo visible)
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
    file_path="/home/pts/dev/pypts/src/pypts/recipes/simple_recipe.yml"
    window.load_yaml(file_path)
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
