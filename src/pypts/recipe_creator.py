import time
import io
from PyQt6.QtWidgets import (
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
    QWidgetAction,
    QFileDialog,
    QToolBar,
    QStyle,
    QSizePolicy,
    QScrollArea,
    QPlainTextEdit,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QPixmap,
    QPainter,
    QTextCursor,
    QTextCharFormat,
)
from PyQt6.QtCore import QSize, Qt
from PyQt6.Qsci import QsciScintilla, QsciLexerYAML
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
# Methods related to initialization and set up of GUI
    def __init__(self):
        super().__init__()
        self.yaml_documents = []  # Store parsed YAML data (necessary for runtime cache)
        self.temporary_recipe_contents = "" # Store yaml as raw text (necessary for the yaml viewer)
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

        # Top Recipe status indicator
        self.recipeStatus = QTextEdit()
        self.recipeStatus.setReadOnly(True)
        self.recipeStatus.setFixedHeight(30)
        self.recipeStatus.setStyleSheet("""
            QTextEdit {
                border: none;
                background-color: transparent;
                color: #333;
                font-style: italic;
                font-size: 14pt;
            }
        """)

        # yaml table widget
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Field", "Value"])
        self.tree.setColumnWidth(0, 200)  # Fix width of the "Field" column
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self.on_treeview_item_changed)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)

        self.tree.setEditTriggers(
            QTreeWidget.EditTrigger.DoubleClicked |
            QTreeWidget.EditTrigger.SelectedClicked |
            QTreeWidget.EditTrigger.EditKeyPressed
        )

        # defining the yaml overview widget
        self.yaml_viewer = ScintillaYamlEditor(self)
        self.yaml_viewer.setReadOnly(False)
        self.yaml_viewer.textChanged.connect(self.on_yamlview_item_changed)

        #Create container for tree + yaml
        self.tree_and_yaml_widget = QWidget()
        self.tree_and_yaml_hlayout = QHBoxLayout(self.tree_and_yaml_widget)
        self.tree_and_yaml_hlayout.addWidget(self.tree)
        self.tree_and_yaml_hlayout.addWidget(self.yaml_viewer)

                # Create toolbar
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(32, 32))  # small icons
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        # Example buttons for the toolbar
        self.action_refresh = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Validate recipe", self)
        self.action_save = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "Save", self)
        self.action_add = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), "Add", self)

        # Add actions to toolbar
        self.toolbar.addAction(self.action_refresh)
        self.toolbar.addAction(self.action_save)
        self.toolbar.addAction(self.action_add)

        # Connect buttons if needed
        self.action_refresh.triggered.connect(self.on_revalidate_clicked)
        self.action_save.triggered.connect(self.on_save_clicked)
        self.action_add.triggered.connect(self.on_add_clicked)

        # 2. Add spacer to push the next widget to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer_action = QWidgetAction(self)
        spacer_action.setDefaultWidget(spacer)
        self.toolbar.addAction(spacer_action)

        # 3. Add custom image on the far right
        icon_label = QLabel()
        icon_label.setPixmap(QPixmap("logo.png"))
        icon_action = QWidgetAction(self)
        icon_action.setDefaultWidget(icon_label)
        self.toolbar.addAction(icon_action)



        ##
        # Create container for top status + tree+yaml layout
        self.tree_status_container = QWidget()
        self.tree_status_layout = QVBoxLayout(self.tree_status_container)
        self.tree_status_layout.setContentsMargins(0, 0, 0, 0)
        self.tree_status_layout.setSpacing(0)

        # Add recipe status bar (top of the view)
        self.tree_status_layout.addWidget(self.recipeStatus)

        # Add the existing tree + yaml horizontal layout
        self.tree_status_layout.addWidget(self.tree_and_yaml_widget)

        # Create final container with toolbar + top status + tree+yaml
        self.tree_and_yaml_container = QWidget()
        self.tree_and_yaml_layout = QVBoxLayout(self.tree_and_yaml_container)
        self.tree_and_yaml_layout.setContentsMargins(0, 0, 0, 0)
        self.tree_and_yaml_layout.setSpacing(0)
        self.tree_and_yaml_layout.addWidget(self.toolbar)
        self.tree_and_yaml_layout.addWidget(self.tree_status_container)

        # Placing widgets into the stacked layout
        self.stacked_layout.addWidget(self.watermark_widget)  # index 0
        self.stacked_layout.addWidget(self.tree_and_yaml_container)  # index 1

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
        self.open_gitlab.triggered.connect(self.open_recipe)
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
        self.save_action.triggered.connect(self.on_save_clicked)


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
        self.open_dev_1 = QAction("Dev Tool 1", self)
        self.open_dev_2 = QAction("Dev Tool 2", self)
        self.open_dev_3 = QAction("Dev Tool 3", self)
        self.open_dev_4 = QAction("Dev Tool 4", self)

        self.open_dev_1.triggered.connect(self.on_dev_1_clicked)
        self.open_dev_2.triggered.connect(self.on_dev_2_clicked)
        self.open_dev_3.triggered.connect(self.on_dev_3_clicked)
        self.open_dev_4.triggered.connect(self.on_dev_4_clicked)

        self.dev_menu.addAction(self.open_dev_1)
        self.dev_menu.addAction(self.open_dev_2)
        self.dev_menu.addAction(self.open_dev_3)
        self.dev_menu.addAction(self.open_dev_4)

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

    def update_yaml_viewer(self):
        self.yaml_viewer.setText(self.temporary_recipe_contents)

    def update_yaml_treeview(self):
        self.yaml_documents = list(self.yaml_parser.load_all(self.temporary_recipe_contents))
        self.tree.blockSignals(True)  # ⛔ Block signals while populating
        self.tree.clear()
        self.item_to_line.clear()  # Clear previous mappings

        for idx, doc in enumerate(self.yaml_documents):
            doc_root = QTreeWidgetItem([f"Document {idx + 1}"])
            self.tree.addTopLevelItem(doc_root)
            self.populate_tree(doc, doc_root)
            doc_root.setExpanded(True)
        self.tree.blockSignals(False)
        return True

    def set_recipe_status(self, message: str, color: str = "#333"):
        """Sets the status message and text color in the top recipe status field."""
        self.recipeStatus.setHtml(f'<span style="color: {color};">{message}</span>')

    def show_recipe_ok(self, message: str = "✅ Recipe is valid"):
        self.set_recipe_status(message, color="green")

    def show_recipe_error(self, message: str):
        self.set_recipe_status(f"❌ {message}", color="red")

    def show_recipe_info(self, message: str):
        self.set_recipe_status(f"ℹ️ {message}", color="gray")

# Methods related to handling actions
    def on_revalidate_clicked(self):
        self.log("To be implemented, now validation is checking in the file !")

    def on_save_clicked(self):
        if not self.current_file_path:
            self.log("❌ No YAML file loaded.")
            return
        try:
            data = self.extract_treeView_to_data()
            # Construct new filename with suffix
            base, ext = os.path.splitext(self.current_file_path)
            new_path = f"{base}_modified{ext}"

            with open(new_path, 'w') as f:
                yaml.dump_all(data, f, sort_keys=False)

            self.log(f"💾 Saved to {new_path}")
            self.setWindowTitle(f"Recipe Editor - {os.path.basename(new_path)}")
        except Exception as e:
            self.log(f"❌ Failed to save: {e}")

    def on_add_clicked(self):
        self.log("Add clicked (not implemented yet)")

    def on_open_wiki_clicked(self):
        url = "https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/master/"
        webbrowser.open(url)

    def on_dev_1_clicked(self):
        self.show_recipe_ok()

    def on_dev_2_clicked(self):
        self.show_recipe_error("YAML parse failed: expected ':' at line 4")

    def on_dev_3_clicked(self):
        self.show_recipe_info("No recipe loaded yet.")

    def on_dev_4_clicked(self):
        # self.show_recipe_ok()
        pass

    def on_open_gitlab_clicked(self):
        url = "https://gitlab.cern.ch/pts/framework/pypts"
        webbrowser.open(url)

    def on_close_recipe_clicked(self):
        self.tree.clear()
        self.stacked_layout.setCurrentIndex(0)  # Show logo
        self.close_recipe.setEnabled(False)  # 🔒 Disable it - gray out
        self.log("🧹 Recipe view cleared.")

    def on_create_recipe_clicked(self):
        self.log("Todo: 1.1")

    def on_tree_item_clicked(self, item, column):
        key = HashableTreeItem(item)
        if key in self.item_to_line:
            line = self.item_to_line[key]
            self.highlight_line(line)
        else:
            pass

    def on_treeview_item_changed(self, item, column):
        line_info = ""
        line_number = self.item_to_line.get(HashableTreeItem(item))
        if line_number is not None:
            line_info = f" (line {line_number + 1})"  # +1 for human-readable line number

        if item.text(1) == "":
            self.log(f"✏️ Cleared a field...{line_info}")
        else:
            self.log(f"✏️ Edited: {line_info}")

        self.extract_treeView_to_data()

        # if self.validate_yaml_documents() == True:
        #     self.update_yaml_viewer()
        #     self.update_yaml_treeview()
        #     self.show_recipe_ok()
        # else:
        #     self.update_yaml_treeview()
        #     self.show_recipe_error("Recipe in Tree View ( <<< ) is invalid!")

        self.setWindowTitle(f"Recipe Editor - {os.path.basename(self.current_file_path)} *unsaved changes*")

    def on_yamlview_item_changed(self):
        try:
            self.temporary_recipe_contents = self.yaml_viewer.text()
        #     validation_result = self.validate_temporary_recipe_contents()
        #     if (validation_result == True) or (validation_result == None):
        #         self.update_yaml_viewer()
        #         self.update_yaml_treeview()
        #         self.show_recipe_ok()
        #     else:
        #         self.update_yaml_treeview()
        #         self.show_recipe_error("Recipe in Edit View ( >>> ) is invalid!")
        #     self.update_yaml_treeview()
        #     self.log("✍️ Recipe in YAML editor was modified")
        #     self.setWindowTitle(f"Recipe Editor - {os.path.basename(self.current_file_path)} *unsaved changes*")
        except Exception as e:
            self.log(f"❌ Exception on yamlview edit!: {e}")

# Recipe handling
    def validate_recipe(self):
        try:
            if (validate_recipe_filepath(self.current_file_path)):
                self.log("✅ Recipe file validated successfully.")
                self.show_recipe_ok()
            else:
                self.log("❌ Summary: Recipe file failed the validation!")
                self.show_recipe_error("❌ Recipe file is invalid!")
                return False
        except Exception as e:
            self.tree.blockSignals(False)  # Safety catch
            self.log(f"❌ Unhandled expception while validating the recipe: {e}")
            return False

    def validate_yaml_documents(self):
        self.extract_treeView_to_data()
        # self.validate_temporary_recipe_contents()
        pass

    def validate_temporary_recipe_contents(self):
        try:
            if (validate_recipe_string_variable(self.temporary_recipe_contents)):
                self.log("✅ Recipe file validated successfully.")
                self.show_recipe_ok()
            else:
                self.log("❌ Summary: Recipe failed the validation!")
                self.show_recipe_error("Recipe file is invalid!")
                return False
        except Exception as e:
            self.tree.blockSignals(False)  # Safety catch
            self.log(f"❌ Unhandled expception while validating the recipe: {e}")
            return False

    def open_recipe(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open recipe file", "", "YAML Files (*.yml *.yaml)")
        self.load_yaml(file_path)
        self.setWindowTitle(f"Recipe Editor - {os.path.basename(file_path)}")

    def load_yaml(self, file_path):
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    raw_text = f.read()
                    self.temporary_recipe_contents = raw_text
                    self.current_file_path = file_path

                self.yaml_parser = YAML()
                self.yaml_parser.preserve_quotes = True

                self.update_yaml_viewer()
                self.update_yaml_treeview()

                self.stacked_layout.setCurrentIndex(1)
                self.close_recipe.setEnabled(True)  # 🔒 Enable it
                self.log(f"✅ Loaded {len(self.yaml_documents)} document(s) from: {file_path}")

            except YAMLError as e:
                self.tree.blockSignals(False)  # Safety catch
                self.log(f"❌ YAML parse error: {e}")
            QApplication.processEvents()
            self.validate_temporary_recipe_contents()

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

                child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsEditable) # make the field editable
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
                child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsEditable) #make editable
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
            leaf_item.setFlags(leaf_item.flags() | Qt.ItemFlag.ItemIsEditable) #make editable
            parent_item.addChild(leaf_item)

        # Expand all items after population
        self.tree.expandAll()

    def extract_treeView_to_data(self):
        documents = []
        for i in range(self.tree.topLevelItemCount()):
            doc_item = self.tree.topLevelItem(i)
            data = self.extract_item_data(doc_item)
            documents.append(data)

        buffer = io.StringIO()
        yaml.dump_all(documents, buffer, sort_keys=False)
        yaml_string = buffer.getvalue()
        buffer.close()
        self.temporary_recipe_contents = yaml_string
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

#todo 0.1 - GENERATION, EDITING, PARTIAL SUPPORT
#done 1.1 - allow saving
#done 1.1 - allow editing on the tree-view panel
#done 1.1 - allow editing on the yaml-editing panel
#todo 1.1 - auto-verification on save, pop-up confirming save, when verification fails
#todo 1.1 - add save as option
#todo 1.1 - add _invalid at the end of recipe, if verification failed
#todo 1.1 - add buttons on toolbox: <restore from interactive view>, <show validation report> - change existing button
#todo 1.1 - name the views - Interactive view, Raw YAML view
#todo 1.1 - add recipe status indicator (only to show the current recipe state), inform if the treeview is not updated.
#done 1.1 - button toolbox to allow editing (just add few buttons and design the helper GUI)
#todo 1.1 - add auto-conversion flag and disable it when the yaml have errors
#todo 1.1 - add button allowing to revert to the last valid format (recreate from tree)
#todo 1.1 - bugfixing, unittests

#todo 1.1.1 - Create new recipe, ask for its name
#todo 1.1.1 - create a new helper file yaml_description.py, where we can have yaml field type descriptions etc
#todo 1.1.1 - Recipe generator
#todo 1.1.1 - Populate generator with headers
#todo 1.1.1 - Ask how many sequences to make
#todo 1.1.1 - Step generator
#todo 1.1.1 - allow deletion of the whole steps
#todo 1.1.1 - allow deletion of the whole sequences
#todo 1.1.1 - mark the text on red only if required + is not filled
#todo 1.1.1 - 1.1 unit tests

#todo 1.2 - UX REFINEMENT
#todo 1.2 - Add possibility to open recent files
#todo 1.2 - Handle possibility that the recent file is not present anymore
#todo 1.2 - Add parsing of the recipe_version field and inform if the recipe is up to correct version
#todo 1.2 - increase 1st column size
#todo 1.2 - Bugfix - sometimes after opening new recipe for editing, the GUI is not refreshing (it does after clicking on the window)
#todo 1.2 - 1.2 unit tests

#todo 1.3 - FULL SUPPORT
#todo 1.3 - creator - number of sequences, steps etc
#todo 1.3 - all fields programatically described in the yaml_description.py helper file
#todo 1.3 - clean up documentation
#todo 1.3 - add drop down lists on the treeview

#todo 2.0 - AI based yaml generation based on prompt (answers to fixed questions)

#todo 3.0 - check possibility to generate the recipe from test plan using AI

# clear up what is required and
# if it is empty or fault, highlight, if it is conforming, its okay and the description can be just blakc
# shall be editable in the text or within the editor
# XSD model validation


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YamlTreeEditor()

    window.show()
    # automation - adding the automatic recipe opening - uncomment to speed up testing
    file_path="/home/pts/dev/pypts/src/pypts/recipes/simple_recipe.yml"
    window.load_yaml(file_path)
    sys.exit(app.exec())

