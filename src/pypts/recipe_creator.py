from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
from datetime import datetime
import webbrowser
import sys
import yaml
from PyQt6.QtGui import QAction ,QTextCursor, QTextCharFormat, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QLabel, QStackedLayout, QScrollArea, QPlainTextEdit
)
from PyQt6.QtGui import QPixmap, QPainter
from PyQt6.QtCore import Qt
from styles import *

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


class YamlTreeEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.yaml_documents = []  # Store parsed YAML data (necessary for runtime cache)
        self.current_file_path = ""  # Track original file path (necessary for saving)
        self.item_to_line = {}

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
        self.tree.itemClicked.connect(self.on_item_clicked)

        # defining the yaml overview widget
        self.yaml_viewer = QPlainTextEdit()
        # self.yaml_viewer = QTextEdit()
        self.yaml_viewer.setReadOnly(True)
        # self.yaml_viewer.setFixedHeight(120)
        # self.yaml_viewer.setFixedWidth(120)

        # Create container widget for tree + yaml
        self.tree_and_yaml_widget = QWidget()
        self.tree_and_yaml_layout = QHBoxLayout(self.tree_and_yaml_widget)
        self.tree_and_yaml_layout.addWidget(self.tree)
        self.tree_and_yaml_layout.addWidget(self.yaml_viewer)

        # Placing widgets into the stacked layout
        self.stacked_layout.addWidget(self.watermark_widget)        # index 0
        self.stacked_layout.addWidget(self.tree_and_yaml_widget)    # index 1

        # Defining log console (multi-line status output)
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFixedHeight(120)

        self.main_layout.addLayout(self.stacked_layout)
        # below the stacked layout there is a status bar
        self.main_layout.addWidget(self.log_console)

        self.log("Application started 👍")

    def get_line_mappings(yaml_text):
        yaml = YAML()
        yaml.preserve_quotes = True
        data = yaml.load(StringIO(yaml_text))

        def walk(d, parent_path=[]):
            if isinstance(d, dict):
                for k, v in d.items():
                    key_path = parent_path + [str(k)]
                    yield ('.'.join(key_path), d.lc.line(k) + 1)
                    yield from walk(v, key_path)
            elif isinstance(d, list):
                for idx, item in enumerate(d):
                    yield from walk(item, parent_path + [str(idx)])

        return dict(walk(data))

    def setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        open_action = QAction("Open Recipe", self)
        open_action.triggered.connect(self.load_yaml)
        file_menu.addAction(open_action)
        exit_action = QAction("Clear view", self)
        exit_action.triggered.connect(self.clear_yaml)
        file_menu.addAction(exit_action)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menubar.addMenu("Edit")
        open_action = QAction("Save Recipe", self)
        open_action.triggered.connect(self.save_yaml)
        edit_menu.addAction(open_action)

        view_menu = menubar.addMenu("View")
        toggle_dark_mode_action = QAction("Toggle Dark Mode", self)
        toggle_dark_mode_action.setCheckable(True)
        toggle_dark_mode_action.triggered.connect(self.toggle_dark_mode)
        view_menu.addAction(toggle_dark_mode_action)

        about_menu = menubar.addMenu("About")
        open_action = QAction("Gitlab", self)
        open_action.triggered.connect(self.open_gitlab)
        about_menu.addAction(open_action)
        open_action = QAction("Wiki", self)
        open_action.triggered.connect(self.open_wiki)
        about_menu.addAction(open_action)

        dev_menu = menubar.addMenu("Development")
        highlight_line = QAction("Highlight 10", self)
        highlight_line.triggered.connect(lambda: self.highlight_line(10))
        dev_menu.addAction(highlight_line)

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

    def load_yaml(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open recipe file", "", "YAML Files (*.yml *.yaml)")
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    raw_text = f.read()

                self.current_file_path = file_path
                self.yaml_documents = list(yaml.safe_load_all(raw_text))
                self.yaml_viewer.setPlainText(raw_text)  # Set in QTextEdit
                self.tree.clear()

                for idx, doc in enumerate(self.yaml_documents):
                    doc_root = QTreeWidgetItem([f"Document {idx + 1}"])
                    self.tree.addTopLevelItem(doc_root)
                    self.populate_tree(doc, doc_root)
                    doc_root.setExpanded(True)

                # Reset cursor to start (optional)
                cursor = self.yaml_viewer.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                self.yaml_viewer.setTextCursor(cursor)

                self.stacked_layout.setCurrentIndex(1)
                self.log(f"✅ Loaded {len(self.yaml_documents)} document(s) from: {file_path}")
            except yaml.YAMLError as e:
                self.log(f"❌ YAML parse error: {e}")

    def highlight_line(self, line_number: int):
        cursor = self.yaml_viewer.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(line_number - 1):
            cursor.movePosition(QTextCursor.MoveOperation.Down)

        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        extra_selection = QTextEdit.ExtraSelection()
        format = QTextCharFormat()
        format.setBackground(QColor("#FFFF00"))  # yellow
        extra_selection.cursor = cursor
        extra_selection.format = format

        self.yaml_viewer.setExtraSelections([extra_selection])

    def clear_yaml(self):
        self.tree.clear()
        self.stacked_layout.setCurrentIndex(0)  # Show logo
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

    def populate_tree(self, data, parent):
        if isinstance(data, dict):
            for key, value in data.items():
                item = QTreeWidgetItem([str(key), ""])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                parent.addChild(item)
                self.populate_tree(value, item)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                item = QTreeWidgetItem([f"[{i}]", ""])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                parent.addChild(item)
                self.populate_tree(value, item)
        else:
            item = QTreeWidgetItem(["", str(data)])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            parent.addChild(item)

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

    def on_item_clicked(self, item, column):
        key_path = self.get_item_key_path(item)
        line = self.item_to_line.get(key_path)
        if line:
            self.highlight_line(line)

    def get_item_key_path(self, item):
        path = []
        while item is not None:
            path.insert(0, item.text(0).strip("[]"))  # Remove list brackets for consistency
            item = item.parent()
        return ".".join(path)


#todo 1.0 - SIMPLE EDITOR
#done 1.0 - Show some indicator that the changes are unsaved
#done 1.0 - allow to clear any field
#todo 1.0 - indicate optional and required fields (with star?)
#todo 1.0 - gray out save option if recipe is not opened
#todo 1.0 - allow saving
#todo 1.0 - add button to automatically verify the recipe
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
#todo 1.2 - right-hand side panel with descriptions on the selected field
#todo 1.2 - on the log, show which line of the yaml was edited
#todo 1.2 - Expert live view of the yaml file on the right hand side panel
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
    sys.exit(app.exec())
