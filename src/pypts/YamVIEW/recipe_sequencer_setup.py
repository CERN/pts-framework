from PySide6.QtWidgets import (QDialog,
                                QVBoxLayout,
                                QLabel, QHBoxLayout, QMessageBox,QWidget,
                                QAbstractItemView, QFrame, QToolBar, QApplication, QStyle, QListWidgetItem, QListWidget)
from PySide6.QtCore import QSize, Qt, QPoint, Signal
from PySide6.QtGui import QAction,QDrag
from pypts.YamVIEW.recipe_step_setup import Step_setup
import re

class StepBlock(QFrame):
    def __init__(self, step_name, step_data, parent=None):
        super().__init__(parent)
        self.step_name = step_name
        self.step_data = step_data
        self.setMaximumWidth(200)
        self.setFrameShape(QFrame.StyledPanel)

        layout = QHBoxLayout(self)
        label = QLabel(step_name)
        layout.addWidget(label)
        layout.addStretch()


class SequencerWidget(QWidget):
    def __init__(self, yaml_viewer=None, parent=None):
        super().__init__(parent)
        self.yaml_viewer = yaml_viewer
        self.steps = []
        self.yaml_update_callback = None
        self.expanded = False

        self.preamble_globals = {}
        self.updated_preamble_globals = {}

        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        # ---- Toolbar ----
        self.Yamlbar = QToolBar()
        self.Yamlbar.setIconSize(QSize(22, 22))
        self.Yamlbar.setStyleSheet("""
            QToolBar {
                border: 1px;
                padding: 0px;
                spacing: 0px;
                background: #E6E6E6;
            }
            QToolButton {
                width: 30px;
                height: 28px;
                border: none;
            }
            QToolButton:hover {
                background: #D8D8D8;
            }
        """)

        style = QApplication.style()

        # "Add Sequence"
        act_new_seq = QAction(style.standardIcon(QStyle.SP_FileDialogNewFolder), 
                            "Add Sequence Folder", self)
        act_new_seq.triggered.connect(self.on_add_sequence)
        self.Yamlbar.addAction(act_new_seq)

        # "Add Step" as a + icon
        act_new_step = QAction("➕", self)
        act_new_step.setToolTip("Make new step")
        act_new_step.triggered.connect(self.on_add_step)
        self.Yamlbar.addAction(act_new_step)

        # ---- List ----
        self.list_widget = StepListWidget()
        self.list_widget.setContentsMargins(0, 0, 0, 0)
        self.list_widget.model().rowsMoved.connect(self.on_steps_reordered)
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.step_clicked.connect(self.navigate_to_step)
        self.list_widget.step_double_clicked.connect(self.edit_step)

        # Add widgets
        self.layout.addWidget(self.Yamlbar)
        self.layout.addWidget(self.list_widget)

        self.skip_warning = False


    def set_yaml_data(self, steps_list):
        self.steps = steps_list
        self.refresh()

    def refresh(self):
        """Render a fully nested collapsible tree of steps."""
        self.list_widget.clear()

        def add_step_item(step, indent=0):
            step_type = step.get("steptype", "")
            step_name = step.get("step_name", "Unnamed Step")
            children = step.get("children", [])
            

            # If the step has children → treat as collapsible folder
            if children:

                # Folder header
                prefix = "➖" if self.expanded else "➕"
                header_item = QListWidgetItem(f"{prefix} {step_name}")
                header_item.setFlags(Qt.ItemIsEnabled)
                header_item.setData(Qt.UserRole, step)
                self.list_widget.addItem(header_item)

                # Indent header
                header_item.setData(Qt.UserRole + 2, indent)
                header_widget = QLabel(f"{prefix} {step_name}")
                header_widget.setStyleSheet(f"margin-left: {indent}px; font-weight: bold;")
                self.list_widget.setItemWidget(header_item, header_widget)

                # Add all children recursively
                child_items = []
                for child in children:
                    child_index_start = self.list_widget.count()
                    add_step_item(child, indent + 20)
                    for i in range(child_index_start, self.list_widget.count()):
                        child_items.append(self.list_widget.item(i))

                # Save child references for collapse/expand
                header_item.setData(Qt.UserRole + 1, child_items)

                # Hide children initially if folder not expanded
                if not self.expanded:
                    for c in child_items:
                        c.setHidden(True)
                        widget = self.list_widget.itemWidget(c)
                        if widget:
                            widget.setVisible(False)

            else:
                # Leaf step → StepBlock
                block = StepBlock(step_name, step)
                container = QFrame()
                container_layout = QHBoxLayout(container)
                container_layout.setContentsMargins(indent, 0, 0, 0)
                container_layout.setAlignment(Qt.AlignLeft)
                container_layout.addWidget(block)
                item = QListWidgetItem()
                item.setSizeHint(container.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, container)
                item.setData(Qt.UserRole, step)

        # Build the full tree
        for step in self.steps:
            add_step_item(step, indent=0)


    def on_steps_reordered(self, parent, start, end, destination, row):
        """Update folder order internally; don't touch YAML yet."""
        # Iterate visible items and reorder them inside their folder
        folder_map = {f.get("steptype"): f for seq in self.steps if seq.get("steptype") == "sequence_folder" for f in seq.get("children", [])}

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            step_data = item.data(Qt.UserRole)
            if not step_data:
                continue

            parent_type = step_data.get("_parent")
            if parent_type:
                folder = folder_map.get(parent_type)
                if folder:
                    children = folder.get("children", [])
                    # Remove & append to maintain new order
                    if step_data in children:
                        children.remove(step_data)
                    children.append(step_data)

        if callable(self.yaml_update_callback):
            self.yaml_update_callback(self.steps)

    def move_step_to_folder(self, step, old_parent, new_parent):
        print(f"Moving: {step['step_name']}  {old_parent} → {new_parent}")

        # Find actual folder dicts
        source_folder = None
        dest_folder = None

        for seq in self.steps:
            if seq.get("steptype") != "sequence_folder":
                continue
            for folder in seq["children"]:
                if folder["steptype"] == old_parent:
                    source_folder = folder
                if folder["steptype"] == new_parent:
                    dest_folder = folder

        if not source_folder or not dest_folder:
            print("❌ Folder lookup failed")
            return

        source_folder["children"].remove(step)
        step["_parent"] = new_parent
        dest_folder["children"].append(step)
        print(step)
        self.refresh()

        if callable(self.yaml_update_callback):
            self.yaml_update_callback(self.steps)

    def on_item_clicked(self, item):
        """Toggle collapsible folder visibility."""
        children = item.data(Qt.UserRole + 1)
        if not children:
            return  # Not a folder
            

        hidden = children[0].isHidden()  # toggle state
        for child_item in children:
            child_item.setHidden(not hidden)

        # Update header icon
        if hidden:
            item.setText(f"➖ {item.data(Qt.UserRole).get('step_name', 'Unnamed Step')}")
            self.expanded = True
        else:
            item.setText(f"➕ {item.data(Qt.UserRole).get('step_name', 'Unnamed Step')}")
            self.expanded = False
    
    def navigate_to_step(self, step_data):
        if not self.yaml_viewer:
            return
        step_name = step_data.get("step_name", "")

        yaml_text = self.yaml_viewer.toPlainText()
        cursor = self.yaml_viewer.textCursor()

        # Try line number if stored
        id_number = step_data.get("_id")
        if id_number is not None:
            step_type = step_data.get("steptype", "")
            step_name = step_data.get("step_name", "")
            step_description = step_data.get("description", "")

            block_pattern = (
            r"steptype:\s*" + re.escape(step_type) + r"\s*"
             r"step_name:\s*" + re.escape(step_name) + r"\s*"
            r"description:\s*" + re.escape(step_description)
        )
            match = re.search(block_pattern, yaml_text)
            if match:
                position = match.start()
                cursor.setPosition(position)
        else:
            # fallback: search by step_name
            step_name = step_data.get("step_name", "")
            position = yaml_text.find(step_name)
            if position == -1:
                return
            cursor.setPosition(position)

        self.yaml_viewer.setTextCursor(cursor)
        self.yaml_viewer.setFocus()
    
    def edit_step(self, step_data):

        if hasattr(self, "current_setup_window") and self.current_setup_window:
            self.current_setup_window.close()
            self.current_setup_window.deleteLater()
            self.current_setup_window = None
         # Identify type and extract node data
        node = step_data.get("_node", {})
        step_type = node.get("steptype").lower()
        step_name = node.get("step_name", "Unnamed Step")
        step_id = step_data.get("_id", None)

        self.current_setup_window = Step_setup()
        self.current_setup_window.AlreadyID = step_id
        match step_type:
            case "pythonmodulestep":
                self.loaded_step_parameters(step_name, node=node, method =node.get("action_type", "method"), gui_name="PythonModuleStep")
                self.current_setup_window.input_mapping_widget.no_extraSteps = True
                self.current_setup_window.input_mapping_widget.load_existing_data(node.get("input_mapping", {}))
                self.current_setup_window.output_mapping_widget.__dict__.update(Output = True)
                self.current_setup_window.output_mapping_widget.load_existing_data(node.get("output_mapping", {}))
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            case "userinteractionstep":
                self.loaded_step_parameters(step_name, node=node, gui_name="UserInteractionStep")
                self.current_setup_window.input_mapping_widget.__dict__.update(allow_message=True, allow_image=True, allow_options=True, no_extraSteps=True)
                self.current_setup_window.input_mapping_widget.load_existing_data(node.get("input_mapping", {}))
                self.current_setup_window.output_mapping_widget.__dict__.update(Output = True, no_extraSteps=False)
                self.current_setup_window.output_mapping_widget.load_existing_data(node.get("output_mapping", {}))
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            case "waitstep":
                self.loaded_step_parameters(step_name, node=node, gui_name="WaitStep")
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            case "userloadingstep":
                self.loaded_step_parameters(step_name, node=node, gui_name="UserLoadingStep")
                self.current_setup_window.input_mapping_widget.__dict__.update(allow_message=True, allow_image=True, allow_options=True, no_extraSteps=True)
                self.current_setup_window.input_mapping_widget.load_existing_data(node.get("input_mapping", {}))
                self.current_setup_window.output_mapping_widget.__dict__.update(loader=True, no_extraSteps=False, specific_method="passfail")
                self.current_setup_window.output_mapping_widget.load_existing_data(node.get("output_mapping", {}))
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            case "userrunmethodstep":
                self.loaded_step_parameters(step_name, node=node, gui_name="UserRunMethodStep")
                self.current_setup_window.input_mapping_widget.__dict__.update(allow_message=True, allow_image=True, allow_options=True, allow_method = True)
                self.current_setup_window.input_mapping_widget.load_existing_data(node.get("input_mapping", {}))
                self.current_setup_window.output_mapping_widget.__dict__.update(Output = True)
                self.current_setup_window.output_mapping_widget.load_existing_data(node.get("output_mapping", {}))
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            case "userwritestep":
                self.loaded_step_parameters(step_name, node=node, gui_name="UserWriteStep")
                #self.current_setup_window.input_mapping_widget.__dict__.update(allow_message=True, allow_image=True, allow_options=True, allow_method = True)
                #self.current_setup_window.input_mapping_widget.load_existing_data(node.get("input_mapping", {}))
                #self.output_mapping_widget = self.InOutputMappingWidget( output = True)
                #self.current_setup_window.output_mapping_widget.load_existing_data(node.get("output_mapping", {}))
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            case "sshconnectstep":
                self.current_setup_window.clear_layout(self.current_setup_window.step_specific_container)
                self.loaded_step_parameters(step_name, node=node,gui_name="SSHConnectStep")
                self.current_setup_window.load_existing_globals(data=self.preamble_globals)
                self.current_setup_window.finished.connect(lambda result: self.on_edit_window_closed(result))
                self.current_setup_window.show()
            
            case _:
                QMessageBox.warning(self, "Unsupported Step", f"Editing not yet supported for '{step_type}'.")

    def on_edit_window_closed(self, result):
        if result == QDialog.Accepted:
            #self.skip_warning = self.current_setup_window.skip_checkbox
            self.updatingYAMLFormat(self.current_setup_window, edit_child=True)
            print("Ran after closing (OK pressed)")
        self.refresh()

    def loaded_step_parameters(self, step_name, node, method = None, gui_name= None):

        if gui_name:
            self.current_setup_window._skip_warning = True
            self.current_setup_window.list_steptype.setCurrentText(gui_name)
            self.current_setup_window._skip_warning = False
        self.current_setup_window.list_steptype.setCurrentText(step_name)
        self.current_setup_window.step_name_input.setText(step_name)
        self.current_setup_window.description_input.setText(node.get("description", ""))
        self.current_setup_window.skip_checkbox.setChecked(node.get("skip", False))
        self.current_setup_window.continue_on_error_checkbox.setChecked(node.get("continue_on_error", False))
        self.current_setup_window.setWindowTitle(f"Edit Step: {step_name}")
        if method:
            self.current_setup_window.list_actiontypes.setCurrentText(node.get("action_type", "method"))
            self.current_setup_window.module_input.setText(node.get("module", ""))
            self.current_setup_window.method_input.setText(node.get("method_name", ""))

    def receive_globals(self, globals_dict: dict):
        """Update the internal globals reference."""
        self.preamble_globals = globals_dict
        print(self.preamble_globals)

    def update_global_value(self, key, value):
        """Update or add a global value."""
        self.updated_preamble_globals[key] = value

    def on_add_sequence(self):
        print("Placeholder")

    def on_add_step(self):
        _step = Step_setup(self)
        _step._skip_warning = True
        if _step.exec():  # blocks until OK or Cancel
            self.updatingYAMLFormat(_step)

    def updatingYAMLFormat(self, _step, edit_child = False):
        new_step = _step.result_step
        
        if hasattr(_step, "global_variables") and _step.global_variables:
            for key, value in _step.global_variables.items():
                self.update_global_value(key, value)
            
        if new_step and not edit_child:
            # Assign parent folder type before inserting
            new_step["_parent"] = "main_folder"  

            self.steps[1]["children"][1]["children"].append(new_step)

            self.refresh()

            if callable(self.yaml_update_callback):
                self.yaml_update_callback(self.steps)

        elif new_step and edit_child:

            new_step["_parent"] = "main_folder"
            new_ID = new_step.get("_id") 

            for idx, child in enumerate(self.steps[1]["children"][1]["children"]):
                if child.get("_id").strip() == str(new_ID).strip():
                    self.steps[1]["children"][1]["children"][idx] = new_step
                    break
            else:
                self.steps[1]["children"][1]["children"].append(new_step)

            self.refresh()

            if callable(self.yaml_update_callback):
                self.yaml_update_callback(self.steps)


class StepListWidget(QListWidget):
    step_clicked = Signal(dict)
    step_double_clicked = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)  
        self.setDragEnabled(True)
        self._mouse_press_pos = None

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        widget = self.itemWidget(item)
        if not widget:
            return

        # Create a pixmap of the widget (the “ghost” that follows the mouse)
        pixmap = widget.grab()
        # Optionally make it semi-transparent
        pixmap.setDevicePixelRatio(widget.devicePixelRatioF())

        # Create the drag object
        drag = QDrag(self)
        selected_items = self.selectedItems()
        mime_data = self.mimeData(selected_items)  # <-- important!
        drag.setMimeData(mime_data)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        # Start the drag
        drag.exec(Qt.MoveAction)
    
    def mousePressEvent(self, event):
        self._mouse_press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        delta = (event.position().toPoint() - self._mouse_press_pos).manhattanLength()
        if delta < QApplication.startDragDistance():
            item = self.itemAt(event.position().toPoint())
            if item:
                step_data = item.data(Qt.UserRole)
                if step_data:
                    self.step_clicked.emit(step_data)  # notify parent
        super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item:
            step_data = item.data(Qt.UserRole)
            if step_data:
                self.step_double_clicked.emit(step_data)
        super().mouseDoubleClickEvent(event)

    def dropEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target_item = self.itemAt(pos)

        if not target_item:
            return super().dropEvent(event)

        dragged_item = self.currentItem()
        if not dragged_item:
            return super().dropEvent(event)

        dragged_step = dragged_item.data(Qt.UserRole)
        target_step = target_item.data(Qt.UserRole)

        # Only handle drop ON a folder header
        if target_step and "children" in target_step:
            new_parent = target_step["steptype"]
            old_parent = dragged_step["_parent"]

            if new_parent != old_parent:
                sequencer = self.parent()
                if hasattr(sequencer, "move_step_to_folder"):
                    sequencer.move_step_to_folder(dragged_step, old_parent, new_parent)

            event.accept()
            return

        #  Otherwise fallback to normal same-folder reorder
        return super().dropEvent(event)

