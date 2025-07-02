from pypts.customGUIModules import *

class RecipeEditorMainMenu(QMainWindow):
# Initialization methods
    def __init__(self):
        super().__init__()
        self.yaml_documents = []
        self.temporary_recipe_contents = ""
        self.last_valid_recipe = ""
        self.current_file_path = ""
        self.item_to_line = {}
        self.yaml_parser = None
        self.data = None
        self.enable_recipe_verification = True

        self.setWindowTitle("Recipe Editor")
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

        self.open_recipe_action = QAction("Open Recipe", self)
        self.close_recipe = QAction("Close Recipe", self)
        self.exit_action = QAction("Exit", self)

        self.file_menu.addAction(self.open_recipe_action)
        self.file_menu.addAction(self.close_recipe)
        self.file_menu.addAction(self.exit_action)
        self.close_recipe.setEnabled(False)

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

    def setup_central_widget(self):
        self.setStyleSheet(light_style)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

    def setup_toolbar(self):
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(32, 32))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.action_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add", self)
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

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer_action = QWidgetAction(self)
        spacer_action.setDefaultWidget(spacer)
        self.toolbar.addAction(spacer_action)

        icon_label = QLabel()
        icon_label.setPixmap(QPixmap("YamVIEW.png"))
        icon_action = QWidgetAction(self)
        icon_action.setDefaultWidget(icon_label)
        self.toolbar.addAction(icon_action)

    def setup_tree_and_yaml(self):
        # YAML Tree widget
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Field", "Value"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self.on_treeview_item_changed)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        self.tree.setEditTriggers(
            QTreeWidget.EditTrigger.DoubleClicked |
            QTreeWidget.EditTrigger.SelectedClicked |
            QTreeWidget.EditTrigger.EditKeyPressed
        )

        # YAML Viewer (custom ScintillaYamlEditor)
        self.yaml_viewer = ScintillaYamlEditor(self)
        self.yaml_viewer.setReadOnly(False)
        self.yaml_viewer.textChanged.connect(self.on_yamlview_item_changed)
        font = QFont("Fira Code", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.yaml_viewer.setFont(font)

        # Horizontal container for tree + yaml viewer
        self.tree_and_yaml_widget = QWidget()
        self.tree_and_yaml_hlayout = QHBoxLayout(self.tree_and_yaml_widget)
        self.tree_and_yaml_hlayout.addWidget(self.tree)
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
        self.watermark_widget = WatermarkWidget("logo.png")  # Replace with your logo

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
    def mark_required_field(self, tree_item, is_required: bool):
        if is_required:
            # Append star
            original_text = tree_item.text(0)

            # tree_item.setForeground(0, QColor(210, 40, 0))  # orange star
            # mmark required field (only temporary, not to be saved to YAML)
            tree_item.setText(0, "* " + original_text)

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
        dict_fields = ["parameters", "outputs", "locals"]
        for dfield in dict_fields:
            if dfield in data and (data[dfield] == "" or data[dfield] is None):
                data[dfield] = {}

        return data

# Methods related to handling GUI actions
    def on_action_restore_recipe_clicked(self):
        if self.last_valid_recipe == "":
            self.log("️⚠️ ️Unable to restore, no working version in the history")
            return
        self.temporary_recipe_contents = self.last_valid_recipe
        self.update_yaml_viewer()

    def on_save_as_clicked(self):
        # Open the file dialog for the user to choose the save location
        new_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            self.current_file_path or "",  # Start from current path if available
            "YAML Files (*.yaml *.yml);;All Files (*)"
        )

        if not new_path:
            self.log("⚠️ Save As cancelled.")
            return

        try:
            data = self.extract_treeView_to_data()
            data = self.sanitize_empty_fields(data)
            with open(new_path, 'w') as f:
                yaml.dump_all(data, f, sort_keys=False)

            self.current_file_path = new_path  # Update the current path
            self.log(f"💾 Saved to {new_path}")
            self.setWindowTitle(f"Recipe Editor - {os.path.basename(new_path)}")
        except Exception as e:
            self.log(f"❌ Failed to save: {e}")

    def on_save_clicked(self):
        validation_result, description = self.validate_temporary_recipe_contents()
        if not validation_result:
            if not self.ask_save_invalid_file():
                self.log("⚠️ Save aborted.")
                return
        if not self.current_file_path:
            self.log("⚠️ No YAML file loaded.")
            return
        try:
            data = self.extract_treeView_to_data()
            # Construct new filename with suffix
            base, ext = os.path.splitext(self.current_file_path)
            new_path = f"{base}{ext}"
            print(new_path)
            with open(new_path, 'w') as f:
                yaml.dump_all(data, f, sort_keys=False)

            self.log(f"💾 Saved to {new_path}")
            self.setWindowTitle(f"Recipe Editor - {os.path.basename(new_path)}")

            self.load_yaml_recipe(new_path)
        except Exception as e:
            self.log(f"❌ Failed to save: {e}")

    def on_add_clicked(self):
        self.log("️️ℹ️ Add clicked (not implemented yet)")

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
        pass

    def on_open_gitlab_clicked(self):
        url = "https://gitlab.cern.ch/pts/framework/pypts"
        webbrowser.open(url)

    def on_close_recipe_clicked(self):
        self.tree.clear()
        self.stacked_layout.setCurrentIndex(0)  # Show logo
        self.close_recipe.setEnabled(False)  # 🔒 Disable it - gray out
        self.log("️ℹ️ Recipe view cleared.")

    def on_create_recipe_clicked(self):
        self.log("️ℹ️ Todo: 0.2")

    def on_tree_item_clicked(self, item, column):
        text = item.text(column)
        print("Registered click on " + text)

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
            result, description = self.validate_yaml_documents()
            if result == True:
                self.update_yaml_viewer()
                self.show_recipe_ok()
            else:
                self.show_recipe_error("Recipe in Tree Edit View is invalid!")
                self.log(description)
            self.setWindowTitle(f"Recipe Editor - {os.path.basename(self.current_file_path)} *unsaved changes*")
        pass

    def on_yamlview_item_changed(self):
        if self.enable_recipe_verification == True:
            try:
                self.temporary_recipe_contents = self.yaml_viewer.toPlainText()
                validation_result, description = self.validate_temporary_recipe_contents()
                if (validation_result == True):
                    self.update_yaml_treeview()
                    self.show_recipe_ok()
                else:
                    self.show_recipe_error("Recipe in Text Edit View is invalid!")
                    self.log(description)
                self.log("✏️️ Recipe in YAML editor updated")
                self.setWindowTitle(f"Recipe Editor - {os.path.basename(self.current_file_path)} *unsaved changes*")
            except Exception as e:
                self.log(f"❌ YAML edit failure!: {e}")
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_selected_items()
        else:
            super().keyPressEvent(event)

# Recipe parsing and processing
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
            self.tree.blockSignals(False)  # Safety catch
            self.log(f"❌ Unhandled expception while validating the recipe: {e}")
            return False

    def validate_yaml_documents(self):
        self.extract_treeView_to_data()
        validation_result = self.validate_temporary_recipe_contents()
        if validation_result == True:
            self.last_valid_recipe = self.temporary_recipe_contents
        return validation_result

    def validate_temporary_recipe_contents(self):
        result, description = validate_recipe_string_variable(self.temporary_recipe_contents)
        if result == True:
            self.last_valid_recipe = self.temporary_recipe_contents
        return result, description

    def open_recipe(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open recipe file", "", "YAML Files (*.yml *.yaml)")
        self.load_yaml_recipe(file_path)
        self.setWindowTitle(f"Recipe Editor - {os.path.basename(file_path)}")

    def load_yaml_recipe(self, file_path):
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    raw_text = f.read()
                    self.temporary_recipe_contents = raw_text
                    self.current_file_path = file_path

                self.yaml_parser = YAML()
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
                    self.log(f"❌ YAML verification failure!: {e}")


                self.stacked_layout.setCurrentIndex(1)
                self.close_recipe.setEnabled(True)  # 🔒 Enable it

            except YAMLError as e:
                self.tree.blockSignals(False)  # Safety catch
                self.log(f"❌ YAML parse error: {e}")
            QApplication.processEvents()

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

                child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsEditable)  # make the field editable
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
                child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsEditable)  # make editable
                parent_item.addChild(child_item)

                # Line number for sequence item
                line_number = None
                if hasattr(data, 'lc'):
                    try:
                        line_info = data.lc.item(idx)
                        if line_info is not None:
                            line_number = line_info[0]
                    except Exception as e:
                        pass
                if line_number is not None:
                    self.item_to_line[HashableTreeItem(child_item)] = line_number

                self.populate_tree(value, child_item, path + (idx,))

        else:
            # Scalar value directly under a sequence or map
            leaf_item = QTreeWidgetItem(parent_item, [str(data), ""])
            leaf_item.setFlags(leaf_item.flags() | Qt.ItemFlag.ItemIsEditable)  # make editable
            parent_item.addChild(leaf_item)

        # Expand all items after population
        self.tree.expandAll()

    def extract_treeView_to_data(self):
        documents = []
        for i in range(self.tree.topLevelItemCount()):
            doc_item = self.tree.topLevelItem(i)
            data = self.extract_item_data(doc_item)

            doc_item = self.strip_star_prefix(doc_item)
            data = self.strip_star_prefix(data)
            data = self.sanitize_empty_fields(data)
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

# Misc
    def log(self, message: str):
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.log_console.append(f"[{timestamp}] {message}")

    def ask_save_invalid_file(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Invalid File")
        msg.setText("The recipe content is invalid.\nDo you want to save it anyway?\n The content in Tree View would be saved.")
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

#TODO - BugFIX
#Globals are being written as a string, not as a list (if empty)
#

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

# todo 1.0 - Create new recipe, ask for its name
# done 1.0 - fix the small gui imperfections
# done 1.0 - Some gui and UX improvements
# todo 1.0 - create a new helper file yaml_description.py, where we can have yaml field type descriptions etc
# todo 1.0 - Recipe generator
# todo 1.0 - Populate generator with headers
# todo 1.0 - Ask how many sequences to make
# todo 1.0 - Step generator
# todo 1.0 - increase 1st column size
# todo 1.0 - easy way to set the YamView application
# done 1.0 - change the required field to be a star or warning emoji, instead of red colour
# todo 1.0 - 1.1 unit tests

# todo 1.1 - UX REFINEMENT
# todo 1.1 - Add possibility to open recent files
# todo 1.1 - Handle possibility that the recent file is not present anymore
# todo 1.1 - Add parsing of the recipe_version field and inform if the recipe is up to correct version
# todo 1.1 - Bugfix - sometimes after opening new recipe for editing, the GUI is not refreshing (it does after clicking on the window)
# todo 1.1 - 1.2 unit tests

# todo 1.2 - FULL SUPPORT
# todo 1.2 - creator - number of sequences, steps etc
# todo 1.2 - all fields programatically described in the yaml_description.py helper file
# todo 1.2 - clean up documentation
# todo 1.2 - add drop down lists on the treeview

# todo 2.0 - AI based yaml generation based on prompt (answers to fixed questions)

# todo 3.0 - check possibility to generate the recipe from test plan using AI

# todo Nice features to show in 0.2:
# shortcuts,
# parser - if i put some undefined globals, it will define it for me
# auto recovery
# auto cross-verification
# check on save
# save as
# undo on the YAML editview
# unsaved changes

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RecipeEditorMainMenu()

    window.show()
    # automation - adding the automatic recipe opening - uncomment to speed up testing
    file_path = "/home/pts/dev/pypts/src/pypts/recipes/simple_recipe.yml"
    window.load_yaml_recipe(file_path)
    sys.exit(app.exec())

