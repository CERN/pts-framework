from PySide6.QtWidgets import (QDialog,QFileDialog, QComboBox,
                                QVBoxLayout,
                                QLabel,
                                QDialogButtonBox,
                                QPushButton,QLineEdit,QTextEdit,QCheckBox, QHBoxLayout, QMessageBox,QWidget,QTableWidgetItem,QTableWidget,
                                QAbstractItemView, QScrollArea)
import os, uuid

class Sequence_setup(QDialog):
    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Sequence Setup")
        self.resize(600, 400)

        main_layout = QVBoxLayout(self)

        self.sequence_name_input = QLineEdit()
        self.sequence_name_input.setPlaceholderText("New Sequence name")
        main_layout.addWidget(QLabel("<b>Sequence name<b>"))
        main_layout.addWidget(self.sequence_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholdertext("describe the test here")
        main_layout.addWidget(QLabel("<b>Description<b>"))
        main_layout.addWidget(self.description_input)


        main_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
    

    def accept(self):


        validate_method = f"validate_sequence"
        if hasattr(self, validate_method):
            ok, error_msg = getattr(self, validate_method)()
            if not ok:
                self.setStyleSheet("""QMessageBox QPushButton { color: black;}""")
                msg = QMessageBox.warning(self,"Missing data", error_msg)
                return 
            
        self.result_sequence = {
            "sequence_name": self.sequence_name_input.text(),
            "description": self.description_input.toPlainText(),
            "parameters": {},
            "locals": {},
            "outputs": {},
            "setup_steps": {},
            "steps": {},
            "teardown_steps": {},
        }

        super().accept()

    def validate_sequence(self):
        if not self.sequence_name_input.text().strip():
            return False, "Step must have a name"

        return True, ""


class Skip_setup(QDialog):
    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Step Manager")
        self.resize(600, 400)

        main_layout = QVBoxLayout(self)

        self.steps = steps
        self.all_sequences = [
            s for s in self.steps if s.get("steptype") == "sequence_folder"
        ]

        self.sequence_selector = QComboBox()
        for seq in self.all_sequences:
            name = seq["step_name"]
            seq_id = seq["_sequence_id"]
            self.sequence_selector.addItem(name, seq_id)

        self.sequence_selector.currentIndexChanged.connect(self.on_sequence_changed)
        main_layout.addWidget(QLabel("Select Sequence:"))
        main_layout.addWidget(self.sequence_selector)

        self.skip = QCheckBox("Skip All")
        self.skip.setChecked(False)

        self.err = QCheckBox("Continue on All")
        self.err.setChecked(False)
        layout = QHBoxLayout()
        layout.addWidget(self.skip)
        layout.addWidget(self.err)
        main_layout.addLayout(layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)

        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        scroll.setWidget(container)

        self.rows = []  # list of dicts holding widgets for each step
        self.on_sequence_changed(index=0)
        self.container_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        main_layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.skip.stateChanged.connect(self.toggle_skip_all)
        self.err.stateChanged.connect(self.toggle_continue_all)

    def build_row(self, step):

        node = step.get("_node", {})
        layout = QHBoxLayout()
        #seq_name = self.get_sequence_name(step.get("_sequence_id"))

        name = QLineEdit(node.get("step_name", ""))
        name.setDisabled(True)

        skip = QCheckBox("Skip")
        skip.setChecked(node.get("skip", False))

        err = QCheckBox("Continue on Error")
        err.setChecked(node.get("continue_on_error", False))

        #layout.addWidget(QLabel(f"Sequence: {seq_name}"))
        layout.addWidget(QLabel("Name:"))
        layout.addWidget(name)
        layout.addWidget(skip)
        layout.addWidget(err)

        return {
            "layout": layout,
            "step_data": step,
            "name": name,
            "skip": skip,
            "err": err,
        }

    def accept(self):
        
        for row in self.rows:
            self.result_step = row["step_data"]
            node = self.result_step.get("_node", {})

            # Update only the skip/continue flags
            node["skip"] = row["skip"].isChecked()
            node["continue_on_error"] = row["err"].isChecked()

        super().accept()

    def get_steps(self):
        return self.steps
    
    def toggle_skip_all(self, checked):
        for row in self.rows:
            row["skip"].setChecked(checked)

    def toggle_continue_all(self, checked):
        for row in self.rows:
            row["err"].setChecked(checked)

    def get_sequence_name(self, seq_id):
        if not self.all_sequences:
            return "Unknown"

        for seq in self.all_sequences:
            if seq.get("_sequence_id") == seq_id:
                return seq.get("step_name", "Unknown")
        return "Unknown"
    
    def on_sequence_changed(self, index):
        self.skip.setChecked(False)
        self.err.setChecked(False)
        seq_id = self.sequence_selector.itemData(index)
        if seq_id is None:
            return
        self.load_sequence(seq_id)

    def load_steps(self, steps):
        self.clear_container_layout()
        self.rows.clear()
        for step in steps:
            row = self.build_row(step)
            self.rows.append(row)
            self.container_layout.addLayout(row["layout"])

    def load_sequence(self, sequence_id):
        seq = next((s for s in self.all_sequences 
                    if s["_sequence_id"] == sequence_id), None)
        if not seq:
            return
        
        setup_folder = next((f for f in seq["children"] if f["steptype"] == "setup_folder"), None) 
        setup_steps = setup_folder["children"] if setup_folder else []
        main_folder = next((f for f in seq["children"] if f["steptype"] == "main_folder"), None)
        main_steps = main_folder["children"] if main_folder else []
        teardown_folder = next((f for f in seq["children"] if f["steptype"] == "teardown_folder"), None) 
        teardown_steps = teardown_folder["children"] if teardown_folder else []
        steps = setup_steps + main_steps + teardown_steps
        self.load_steps(steps)
        
    def clear_container_layout(self):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout_recursive(item.layout())
    def clear_layout_recursive(self, layout): 
        while layout.count():
            item = layout.takeAt(0) 
            if item.widget():
                item.widget().deleteLater() 
            elif item.layout():
                self.clear_layout_recursive(item.layout())
        





class Step_setup(QDialog):
    def __init__(self,use_input_mapping=True, use_output_mapping=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New step creation")
        self.resize(500,500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Steptype"))
        self.list_steptype = QComboBox()
        self.steptypes = [
            "PythonModuleStep",
            "UserInteractionStep",
            "WaitStep",
            "UserLoadingStep",
            "UserRunMethodStep",
            "UserWriteStep",
            "SSHConnectStep",
            "SSHCloseStep"
        ]
        self.list_steptype.addItems(self.steptypes)
        layout.addWidget(self.list_steptype)

        self.list_steptype.currentTextChanged.connect(self.on_step_type_changed)
        self._previous_step_type = self.list_steptype.currentText()
        self._skip_warning = False

        # Container for step-specific widgets
        self.step_specific_container = QVBoxLayout()
        container_widget = QWidget()
        container_widget.setLayout(self.step_specific_container)
        self.setup_pythonmodulestep()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container_widget)
        self.step_specific_container.addStretch()
        layout.addWidget(scroll)

        # OK/Cancel buttons
        buttons = QDialogButtonBox()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.ok_button.setStyleSheet("color: black;")
        self.cancel_button.setStyleSheet("color: black;")
        buttons.addButton(self.ok_button, QDialogButtonBox.AcceptRole)
        buttons.addButton(self.cancel_button, QDialogButtonBox.RejectRole)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.AlreadyID = None

    def on_step_type_changed(self, step_type: str):
        if not getattr(self, "_skip_warning", False):
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Warning")
            msg.setText(
                "Changing this step type will delete all current information.\n\n"
                "Do you want to continue?"
            )
            msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            msg.setDefaultButton(QMessageBox.Cancel)

            checkbox = QCheckBox("Don't ask again")
            msg.setCheckBox(checkbox)

            result = msg.exec()

            if checkbox.isChecked():
                self._skip_warning = True

            if result == QMessageBox.Cancel:
                # User canceled → revert selection and stop everything
                self.list_steptype.blockSignals(True)
                self.list_steptype.setCurrentText(self._previous_step_type)
                self.list_steptype.blockSignals(False)
                return
        self._previous_step_type = step_type
        # Clear previous widgets
        self.clear_layout(self.step_specific_container)
        # Call the corresponding setup function
        func_name = f"setup_{step_type.lower()}"
        if hasattr(self, func_name):
            getattr(self, func_name)()
        
    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            # Remove widgets
            if item.widget():
                item.widget().deleteLater()
            # Remove nested layouts
            elif item.layout():
                self.clear_layout(item.layout())
    
    # --------- Setup functions for each steptype ---------
    def setup_pythonmodulestep(self):
        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New step")
        self.step_specific_container.addWidget(QLabel("<b>Step name<b>"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)

        self.list_actiontypes = QComboBox()
        self.action_types = ["method", "read_attribute", "write_attribute"]
        self.list_actiontypes.addItems(self.action_types)
        self.step_specific_container.addWidget(QLabel("<b>Action Type<b>"))
        self.step_specific_container.addWidget(self.list_actiontypes)

        self.module_input = QLineEdit()
        self.module_input.setText("example_tests")
        self.step_specific_container.addWidget(QLabel("<b>Specify filename for the script<b>"))
        self.step_specific_container.addWidget(self.module_input)

        self.method_input = QLineEdit()
        self.method_input.setText("main")
        self.step_specific_container.addWidget(QLabel("<b>Name of method to run<b>"))
        self.step_specific_container.addWidget(self.method_input)

        self.step_specific_container.addWidget(QLabel("<b>Input Mapping<b>"))
        self.input_mapping_widget = self.InOutputMappingWidget()
        self.step_specific_container.addWidget(self.input_mapping_widget)

        self.step_specific_container.addWidget(QLabel("<b>Output Mapping<b>"))
        self.output_mapping_widget = self.InOutputMappingWidget( output = True)
        self.step_specific_container.addWidget(self.output_mapping_widget)

        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)


        self.step_specific_container.addLayout(checkbox_horizontal)       
        self.step_specific_container.addStretch()

    def setup_userinteractionstep(self):
        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New UserInteractionStep")
        self.step_specific_container.addWidget(QLabel("<b>Step name<b>"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)
        
        self.step_specific_container.addWidget(QLabel("<b>Input Mapping<b>"))
        self.input_mapping_widget = self.InOutputMappingWidget(allow_message=True, allow_image=True, allow_options=True, no_extraSteps=True)
        self.step_specific_container.addWidget(self.input_mapping_widget)

        self.step_specific_container.addWidget(QLabel("<b>Output Mapping<b>"))
        self.output_mapping_widget = self.InOutputMappingWidget( output = True, no_extraSteps=True, specific_method="output")
        self.step_specific_container.addWidget(self.output_mapping_widget)

        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)


        self.step_specific_container.addLayout(checkbox_horizontal)  
        self.step_specific_container.addStretch() 


    def setup_waitstep(self):

        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New waitstep")
        self.step_specific_container.addWidget(QLabel("Stepname"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.wait_time_input = QLineEdit()
        self.wait_time_input.setText("3")
        self.step_specific_container.addWidget(QLabel("Wait time (seconds)"))
        self.step_specific_container.addWidget(self.wait_time_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(100)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("Description"))
        self.step_specific_container.addWidget(self.description_input)

        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)



        self.step_specific_container.addLayout(checkbox_horizontal)       
        self.step_specific_container.addStretch()


    def setup_userloadingstep(self):

        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New UserLoadingStep")
        self.step_specific_container.addWidget(QLabel("<b>Step name<b>"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)

        self.step_specific_container.addWidget(QLabel("<b>Input Mapping<b>"))
        self.input_mapping_widget = self.InOutputMappingWidget(allow_message=True, allow_image=True,allow_options=True, no_extraSteps=True)
        self.input_mapping_widget.add_option_row(key="cancel", value="cancel")
        self.input_mapping_widget.add_option_row(key="file", value="ButtonKey for fileloading")
        self.input_mapping_widget.add_option_row()
        self.step_specific_container.addWidget(self.input_mapping_widget)


        self.step_specific_container.addWidget(QLabel("<b>Output Mapping<b>"))
        self.output_mapping_widget = self.InOutputMappingWidget(loader=True, no_extraSteps=False, specific_method="passfail")
        self.step_specific_container.addWidget(self.output_mapping_widget)


        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)

        self.step_specific_container.addLayout(checkbox_horizontal)  
        self.step_specific_container.addStretch() 

    def setup_userrunmethodstep(self):
        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New Userstep")
        self.step_specific_container.addWidget(QLabel("<b>Step name<b>"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)

        self.list_actiontypes = QComboBox()
        self.action_types = ["method", "read_attribute", "write_attribute"]
        self.list_actiontypes.addItems(self.action_types)
        self.step_specific_container.addWidget(QLabel("<b>Action Type<b>"))
        self.step_specific_container.addWidget(self.list_actiontypes)

        self.module_input = QLineEdit()
        self.module_input.setText("example_tests")
        self.step_specific_container.addWidget(QLabel("<b>Specify filename for the script<b>"))
        self.step_specific_container.addWidget(self.module_input)

        self.step_specific_container.addWidget(QLabel("<b>Input Mapping<b>"))
        layout = QHBoxLayout()
        layout.addWidget(QLabel("<b> Trigger response<b>:"))
        self.trigger_response = QLineEdit()
        self.trigger_response.setPlaceholderText("Name the value of the key for the options button desired to trigger method")
        layout.addWidget(self.trigger_response)
        self.step_specific_container.addLayout(layout)
        self.input_mapping_widget = self.InOutputMappingWidget(allow_message=True, allow_image=True, allow_method=True, allow_options=True)
        self.step_specific_container.addWidget(self.input_mapping_widget)

        self.step_specific_container.addWidget(QLabel("<b>Output Mapping<b>"))
        self.output_mapping_widget = self.InOutputMappingWidget( output = True)
        self.step_specific_container.addWidget(self.output_mapping_widget)

        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)


        self.step_specific_container.addLayout(checkbox_horizontal)       
        self.step_specific_container.addStretch()

    def setup_userwritestep(self):
        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New UserWriteStep")
        self.step_specific_container.addWidget(QLabel("<b>Step name<b>"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)

        self.step_specific_container.addWidget(QLabel("<b>Input Mapping<b>"))
        self.input_mapping_widget = self.InOutputMappingWidget(allow_message=True, allow_image=True, no_extraSteps=True)
        self.step_specific_container.addWidget(self.input_mapping_widget)

        self.step_specific_container.addWidget(QLabel("<b>Determine type of function<b>"))
        self.UART_setup = QCheckBox("UART")
        self.Write_variable = QCheckBox("Write to variable")
        mode_choice = QHBoxLayout()
        mode_choice.addWidget(self.UART_setup)
        mode_choice.addWidget(self.Write_variable)
        self.chosen_input = QLineEdit()
        self.chosen_input.setPlaceholderText("Explaination of what will happen once either of the above are chosen. ")
        self.chosen_input.setDisabled(True)
        self.step_specific_container.addLayout(mode_choice)
        self.step_specific_container.addWidget(self.chosen_input)
        self.UART_setup.stateChanged.connect(self.Uart_Toggle)
        self.Write_variable.stateChanged.connect(self.Write_toggle)

        self.step_specific_container.addWidget(QLabel("<b>Output Mapping<b>"))
        self.output_mapping_widget = self.InOutputMappingWidget(loader=True, no_extraSteps=False)
        self.step_specific_container.addWidget(self.output_mapping_widget)

        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)

        self.step_specific_container.addLayout(checkbox_horizontal)  
        self.step_specific_container.addStretch() 

    def setup_sshconnectstep(self):

        if hasattr(self, "input_mapping_widget"):
            self.input_mapping_widget.setParent(None)
            self.input_mapping_widget.deleteLater()
            del self.input_mapping_widget

        if hasattr(self, "output_mapping_widget"):
            self.output_mapping_widget.setParent(None)
            self.output_mapping_widget.deleteLater()
            del self.output_mapping_widget


        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New SSH Close step")
        self.step_specific_container.addWidget(QLabel("<b>Stepname<b>"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)

        self.step_specific_container.addWidget(QLabel("<b>Global variables used for SSH<b>"))
        self.SSHInfo_exists = QCheckBox("Already exists?")
        self.SSHInfo_exists.setChecked(False)
        self.step_specific_container.addWidget(self.SSHInfo_exists)

        self.GLB_host = QLineEdit()
        self.GLB_host.setPlaceholderText("Hostname, either name or IP")
        self.GLB_user = QLineEdit()
        self.GLB_user.setPlaceholderText("root")
        self.GLB_passwd = QLineEdit()
        self.GLB_passwd.setPlaceholderText("1234")
        self.GLB_pkey = QLineEdit()
        self.GLB_pkey.setPlaceholderText("Path to key")
        self.GLB_port = QLineEdit()
        self.GLB_port.setPlaceholderText("Only change if non default port is used")

        def add_row(label_text, widget):
            layout = QHBoxLayout()
            layout.addWidget(QLabel(label_text))
            layout.addWidget(widget)
            self.step_specific_container.addLayout(layout)

        add_row("<b>Host", self.GLB_host)
        add_row("<b>Username", self.GLB_user)
        add_row("<b>Password", self.GLB_passwd)
        add_row("<b>Private Key location", self.GLB_pkey)
        add_row("<b>Port", self.GLB_port)

        def toggle_ssh_fields(state):
            enabled = not bool(state)  # if checkbox is checked, disable fields
            for widget in [self.GLB_host, self.GLB_user, self.GLB_passwd, self.GLB_pkey, self.GLB_port]:
                widget.setEnabled(enabled)

        self.SSHInfo_exists.stateChanged.connect(toggle_ssh_fields)

        self.skip_checkbox = QCheckBox("Skip")
        self.skip_checkbox.setChecked(True)
        self.continue_on_error_checkbox = QCheckBox("Continue on Error")
        self.continue_on_error_checkbox.setChecked(True)

        checkbox_horizontal = QHBoxLayout()
        checkbox_horizontal.addWidget(self.skip_checkbox)
        checkbox_horizontal.addWidget(self.continue_on_error_checkbox)

        self.step_specific_container.addLayout(checkbox_horizontal)

        self.step_specific_container.addStretch()

    def setup_sshclosestep(self):
        self.step_name_input = QLineEdit()
        self.step_name_input.setPlaceholderText("New SSH Close step")
        self.step_specific_container.addWidget(QLabel("Stepname"))
        self.step_specific_container.addWidget(self.step_name_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("describe the test in this box")
        self.step_specific_container.addWidget(QLabel("<b>Description<b>"))
        self.step_specific_container.addWidget(self.description_input)
   
        self.step_specific_container.addStretch()



    def accept(self):
        step_type = self.list_steptype.currentText()
        if self.AlreadyID:
            StepID = self.AlreadyID
        else:
            StepID = str(uuid.uuid4())

        validate_method = f"validate_{step_type.lower()}"
        if hasattr(self, validate_method):
            ok, error_msg = getattr(self, validate_method)()
            if not ok:
                self.setStyleSheet("""QMessageBox QPushButton { color: black;}""")
                msg = QMessageBox.warning(self,"Missing data", error_msg)
                return 
             
        self.result_step = {
            "steptype": step_type,
            "step_name": "Default",
            "_parent": None,
            "_node": {},
             "_id": StepID
        }
        self.global_variables = {}
        self.local_variables = {}
        g_in, l_in = None, None
        g_out, l_out = None,None
        match step_type:
            case "PythonModuleStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "PythonModuleStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "action_type": self.list_actiontypes.currentText(),
                    "module": self.module_input.text(),
                    "method_name": self.method_input.text(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                    "input_mapping": self.input_mapping_widget.get_data(),
                    "output_mapping": self.output_mapping_widget.get_data()
                }
                g_in, l_in = self.extract_locals_globals(self.input_mapping_widget.get_data())
                g_out, l_out = self.extract_locals_globals(self.output_mapping_widget.get_data())

            case "UserInteractionStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "UserInteractionStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                    "input_mapping": self.input_mapping_widget.get_data(),
                    "output_mapping": self.output_mapping_widget.get_data()
                }
                g_in, l_in = self.extract_locals_globals(self.input_mapping_widget.get_data())
                g_out, l_out = self.extract_locals_globals(self.output_mapping_widget.get_data())

            case "WaitStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "WaitStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                    "input_mapping": {"wait_time": {"value": self.wait_time_input.text()}},
                    "output_mapping": {}
                }

            case "UserLoadingStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "UserInteractionStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                    "input_mapping": self.input_mapping_widget.get_data(),
                    "output_mapping": self.output_mapping_widget.get_data()
                }
                self.global_variables = {
                    "loadFile": 'file'
                }
                g_in, l_in = self.extract_locals_globals(self.input_mapping_widget.get_data())
                g_out, l_out = self.extract_locals_globals(self.output_mapping_widget.get_data())

            case "UserRunMethodStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "UserRunMethodStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "action_type": self.list_actiontypes.currentText(),
                    "module": self.module_input.text(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                    "trigger_response": self.trigger_response.text(),
                    "input_mapping": self.input_mapping_widget.get_data(),
                    "output_mapping": self.output_mapping_widget.get_data()
                }
                g_in, l_in = self.extract_locals_globals(self.input_mapping_widget.get_data())
                g_out, l_out = self.extract_locals_globals(self.output_mapping_widget.get_data())
            case "UserWriteStep":
                self.input_mapping_widget.add_special_row("options")
                self.input_mapping_widget.add_option_row(key="cancel", value="cancel")
                if self.Write_variable.isChecked():
                    self.input_mapping_widget.add_option_row(key="wrt", value="Write to variable")
                elif self.UART_setup.isChecked():
                    self.input_mapping_widget.add_option_row(key="ID", value="Setup UART")
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "UserWriteStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                    "input_mapping": self.input_mapping_widget.get_data(),
                    "output_mapping": self.output_mapping_widget.get_data()
                }
                if self.UART_setup.isChecked():
                    self.result_step["_node"]["output_mapping"] = {"output":{"type":"passfail"}}
                self.global_variables = {
                    "cancel_key": 'cancel',
                    "ID_key": 'ID',
                    "wrt_key": 'wrt',
                }
                g_in, l_in = self.extract_locals_globals(self.input_mapping_widget.get_data())
                g_out, l_out = self.extract_locals_globals(self.output_mapping_widget.get_data())

            case "SSHConnectStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "setup_folder"
                self.result_step["_node"] = {
                    "steptype": "SSHConnectStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText(),
                    "skip": self.skip_checkbox.isChecked(),
                    "continue_on_error": self.continue_on_error_checkbox.isChecked(),
                }
                self.global_variables = {
                    "host": self.GLB_host.text(),
                    "user": self.GLB_user.text(),
                    "password": self.GLB_passwd.text(),
                    "private_key": self.GLB_pkey.text(),
                    "port": self.GLB_port.text() if self.GLB_port.text() != "" else "none"
                }

            case "SSHCloseStep":
                self.result_step["step_name"] = self.step_name_input.text()
                self.result_step["_parent"] = "main_folder"
                self.result_step["_node"] = {
                    "steptype": "SSHCloseStep",
                    "step_name": self.result_step["step_name"],
                    "description": self.description_input.toPlainText()
                }
            case _:
                print("Unknown step type")
        if g_in and g_out and l_in and l_out is not None:
            self.global_variables.update(g_in)
            self.global_variables.update(g_out)
            self.local_variables.update(l_in)
            self.local_variables.update(l_out)

        super().accept()

    def load_existing_globals(self, data):
        """Load saved SSH global variables into the existing input fields."""

        # Map data keys to the actual widgets created in setup_sshconnectstep()
        widget_map = {
            "host": self.GLB_host,
            "user": self.GLB_user,
            "password": self.GLB_passwd,
            "private_key": self.GLB_pkey,
            "port": self.GLB_port
        }

        for key, widget in widget_map.items():
            if key in data:
                value = data[key]
                widget.setText("" if value is None else str(value))
        self.SSHInfo_exists.setChecked(True)
        self.SSHInfo_exists.stateChanged.emit(True)
    
    ################ Validation steps for the settings #################################
    def validate_pythonmodulestep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"

        # Validate input mapping
        ok, msg = self.input_mapping_widget.validate()
        if not ok:
            return False, msg

        # Validate output mapping
        ok, msg = self.output_mapping_widget.validate()
        if not ok:
            return False, msg

        return True, ""

    def validate_userinteractionstep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"

        # Validate input mapping
        ok, msg = self.input_mapping_widget.validate()
        if not ok:
            if not "Image" in msg:
                return False, msg


        # Validate output mapping
        ok, msg = self.output_mapping_widget.validate()
        if not ok:
            return False, msg

        return True, ""

    def validate_waitstep(self):
        if not self.wait_time_input.text().strip():
            return False, "Please enter a wait time."
        if not self.wait_time_input.text().isdigit():
            return False, "Wait time must be a number."
        if not self.step_name_input.text():
            return False, "Step must have a name"
        return True, ""
    
    def validate_userloadingstep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"

        # Validate input mapping
        ok, msg = self.input_mapping_widget.validate()
        if not ok:
            if not "Image" in msg:
                return False, msg
            
        
        table = self.input_mapping_widget.get_options_table()
        has_valid = False
        for r in range(table.rowCount()):
            key_item = table.item(r, 0)
            if key_item and key_item.text().strip()=="file":
                has_valid = True
        if not has_valid:
            return False, f"'file' must exist as a key"
        

        # Validate output mapping
        ok, msg = self.output_mapping_widget.validate()
        if not ok:
            return False, msg

        return True, ""

    def validate_userrunmethodstep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"

        # Validate input mapping
        ok, msg = self.input_mapping_widget.validate()
        if not ok:
            return False, msg

        # Validate output mapping
        ok, msg = self.output_mapping_widget.validate()
        if not ok:
            return False, msg

        return True, ""

    def validate_userwritestep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"
        
        if not self.UART_setup.isChecked() and not self.Write_variable.isChecked():
            return False, "You must choose which functionType to use"

        # Validate input mapping
        ok, msg = self.input_mapping_widget.validate()
        if not ok:
            if not "Image" in msg:
                return False, msg

        # Validate output mapping
        ok, msg = self.output_mapping_widget.validate()
        if not ok:
            return False, msg

        return True, ""


    def validate_sshconnectstep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"

        return True, ""

    def validate_sshclosestep(self):
        if not self.step_name_input.text().strip():
            return False, "Step must have a name"
        
        return True, ""
        
    def Write_toggle(self):
        if self.Write_variable.isChecked():
            self.UART_setup.setChecked(False)
            self.chosen_input.setText("Chosing this will allow the function to write to a specific output")

    def Uart_Toggle(self):
        if self.UART_setup.isChecked():
            self.Write_variable.setChecked(False)
            self.chosen_input.setText("Chosing this will make the step setup a UART that can be used for other tests. Choosing this will bypass the output mapping")

    def extract_locals_globals(self, mapping):
        IGNORED = {"message", "options", "image_path", "method"}
        
        globals_found = {}
        locals_found = {}

        for key, entry in mapping.items():
            if key in IGNORED:
                continue

            if not isinstance(entry, dict):
                continue

            var_type = entry.get("type")
            value = entry.get("value")
            if var_type == "global":
                value = entry.get("global_name")
                globals_found[value] = ""
            elif var_type == "local":
                value = entry.get("local_name")
                locals_found[value] = ""

        return globals_found, locals_found


    class InOutputMappingWidget(QWidget):
        def __init__(self, parent=None, output= False, allow_image = False, allow_options=False,allow_message=False, allow_method = False, no_extraSteps=False, specific_method = None, loader = None):
            super().__init__(parent)
            self.Output = output
            self.allow_image  = allow_image
            self.allow_options = allow_options
            self.allow_message = allow_message
            self.allow_method = allow_method
            self.no_extraSteps = no_extraSteps
            self.specific_method = specific_method
            self.loader = loader

            self.layout = QVBoxLayout(self)
            self.layout.setContentsMargins(0, 0, 0, 0)
            self.layout.setSpacing(2)
            self.rows = []

            self.populate_required_rows()
            if not self.no_extraSteps:
                self.add_row()

        # ---------------- Pre-populate required rows ----------------
        def populate_required_rows(self):
            if self.allow_message:
                self.add_special_row("message")
            if self.allow_options:
                self.add_special_row("options")
            if self.allow_image:
                self.add_special_row("image_path")
            if self.allow_method:
                self.add_special_row("method")
            if self.specific_method:
                self.add_special_row(self.specific_method)

        def add_special_row(self, type_name):
            row = {}


            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(2)

            # Parameter name
            row["name_edit"] = QLineEdit()
            row["name_edit"].setPlaceholderText(type_name)
            row["name_edit"].setReadOnly(True)
            h.addWidget(row["name_edit"])

            # Type combobox
            row["type_combo"] = QComboBox()
            row["type_combo"].addItem(type_name)
            row["type_combo"].setCurrentText(type_name)
            row["type_combo"].setEnabled(False)
            h.addWidget(row["type_combo"])

            # Value edit
            row["value_edit"] = QLineEdit()
            row["value_edit"].setPlaceholderText("fill in value")
            h.addWidget(row["value_edit"])

            # Second value for ranges (hidden)
            row["value_edit2"] = QLineEdit()
            row["value_edit2"].setVisible(False)
            h.addWidget(row["value_edit2"])

            row["special"] = QLineEdit()
            row["special"].setText(type_name)
            row["special"].setVisible(False)
            h.addWidget(row["special"])

            # File button or options table
            row["file_button"] = QPushButton("📁")
            row["file_button"].setVisible(False)
            row["options_widget"] = None
            if type_name == "image_path":
                row["file_button"].setVisible(True)
                row["file_button"].clicked.connect(lambda _, r=row: self.pick_file(r))
                h.addWidget(row["file_button"])

            self.layout.addWidget(container)
            self.rows.append(row)
            self.on_type_changed(row)

            row["name_edit"].editingFinished.connect(lambda r=row: self.on_edit_finished(r))
            row["value_edit"].editingFinished.connect(lambda r=row: self.on_edit_finished(r))
            row["value_edit2"].editingFinished.connect(lambda r=row: self.on_edit_finished(r))


        # ---------------- Dynamic row changes ----------------
        def add_row(self):
            row = {}

            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(2)

            # Parameter name
            row["name_edit"] = QLineEdit()
            if self.Output:
                row["name_edit"].setPlaceholderText("parameter (Set the name to be the input of your method)")
            elif self.loader:
                row["name_edit"].setPlaceholderText("Specify variable to save the loaded file/element")
                row["name_edit"].setVisible
            else:
                row["name_edit"].setPlaceholderText("parameter (e.g. value)")
            row["name_edit"].textChanged.connect(self.on_edit_changed)
            h.addWidget(row["name_edit"])

            # direct/global/local
            row["type_combo"] = QComboBox()
            if self.Output:
                types = ["equals", "passthrough", "passfail", "range", "global", "local"]
            elif self.loader:
                types = ["global", "local"]
            else:
                types = ["direct", "global", "local"]
            if self.allow_message:
                types.append("message")
            if self.allow_image:
                types.append("image_path")
            if self.allow_options:
                types.append("options")
            if self.allow_method:
                types.append("method")

            row["type_combo"].addItems(types)
            
            h.addWidget(row["type_combo"])
            row["type_combo"].currentTextChanged.connect(lambda _, r=row: self.on_type_changed(r))

            # First value input
            row["value_edit"] = QLineEdit()
            row["value_edit"].setPlaceholderText("value or variable name")
            row["value_edit"].textChanged.connect(self.on_edit_changed)
            h.addWidget(row["value_edit"])

            # Second value (only visible in "range")
            row["value_edit2"] = QLineEdit()
            row["value_edit2"].setPlaceholderText("max")
            row["value_edit2"].setVisible(False)
            h.addWidget(row["value_edit2"])


            row["file_button"] = QPushButton("📁")
            row["file_button"].setVisible(False)
            row["file_button"].clicked.connect(lambda checked, r=row: self.pick_file(r))
            h.addWidget(row["file_button"])

            # options editor (sub-table)
            row["options_widget"] = None

            self.layout.addWidget(container)
            self.rows.append(row)

            #self.on_type_changed(row)

            row["name_edit"].editingFinished.connect(lambda r=row: self.on_edit_finished(r))
            row["value_edit"].editingFinished.connect(lambda r=row: self.on_edit_finished(r))
            row["value_edit2"].editingFinished.connect(lambda r=row: self.on_edit_finished(r))

        def del_rows(self):
            def is_blank(row):
                """Return True if the row has no meaningful data."""
                
                name = row["name_edit"].text().strip()
                value = row["value_edit"].text().strip()
                value2 = row["value_edit2"].text().strip() if row.get("value_edit2") else ""
                if row.get("options_widget"):
                    table = row["options_widget"]
                    for r in range(table.rowCount()):
                        key_item = table.item(r, 0)
                        val_item = table.item(r, 1)
                        if (key_item and key_item.text().strip()) or (val_item and val_item.text().strip()):
                            return False
                return not (name or value or value2)

            new_rows = []
            last_non_blank_index = -1

            # Find the last row that has content
            for i, row in enumerate(self.rows):
                if not is_blank(row):
                    last_non_blank_index = i

            # Rebuild rows, keeping only meaningful blanks
            for i, row in enumerate(self.rows):
                blank = is_blank(row)
                if blank and i < last_non_blank_index:
                    # Remove middle blank rows
                    if not row["special"]:
                        widget = row["name_edit"].parentWidget()
                        self.layout.removeWidget(widget)
                        widget.setParent(None)
                        widget.deleteLater()
                else:
                    new_rows.append(row)

            # Ensure at least one blank row at the end
            if not new_rows or not is_blank(new_rows[-1]) and not self.no_extraSteps:
                self.add_row()
            self.rows = new_rows

        def on_edit_finished(self, row):
            """Called when a row loses focus."""
            self.del_rows()

        def pick_file(self, row):
            """Choose a file for image_path"""
            import shutil
            file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg)")

            if file_path:
                target_folder = "./src/pypts/images/"
                os.makedirs(target_folder, exist_ok=True)
                
                filename = os.path.basename(file_path)
                destination = os.path.join(target_folder, filename)
                if not os.path.exists(destination):
                    shutil.copy(file_path, destination)
                
                row["value_edit"].setText(filename)

        def make_options_editor(self, row):
            table = QTableWidget(1, 2)  # 1 row, 2 columns
            table.setHorizontalHeaderLabels(["Key", "Value"])
            table.horizontalHeader().setStretchLastSection(True)
            table.verticalHeader().setVisible(False)

            table.setStyleSheet("""
                QTableWidget::item {
                    padding: 0px;
                }
                QHeaderView::section {
                    padding: 0px;
                    font-size: 12px;
                }
            """)

            table.verticalHeader().setDefaultSectionSize(18)

            table.setFixedWidth(260)
            table.setFixedHeight(180)

            table.setItem(0, 0, QTableWidgetItem(""))
            table.setItem(0, 1, QTableWidgetItem(""))

            table.setEditTriggers(QAbstractItemView.AllEditTriggers)

            # Store reference
            row["options_widget"] = table

            self.layout.addWidget(table)

            # Add a new blank row when last row has text
            def on_cell_changed(_row, _col):
                last_row = table.rowCount() - 1
                key = table.item(last_row, 0)
                val = table.item(last_row, 1)
                if key and key.text().strip() or val and val.text().strip():
                    table.insertRow(table.rowCount())
                    table.setItem(table.rowCount() - 1, 0, QTableWidgetItem(""))
                    table.setItem(table.rowCount() - 1, 1, QTableWidgetItem(""))
                
                self.on_edit_changed()

            table.cellChanged.connect(on_cell_changed)
        
        def get_options_table(self):
            for r in self.rows:
                if r.get("options_widget"):
                    return r["options_widget"]
            return None
        
        def add_option_row(self, key="", value=""):
            """Append a row to the options table and set key/value (safe vs cellChanged)."""
            table = self.get_options_table()
            if table is None:
                return
            table.blockSignals(True)
            try:
                row_index = table.rowCount()
                table.insertRow(row_index)
                table.setItem(row_index, 0, QTableWidgetItem(key))
                table.setItem(row_index, 1, QTableWidgetItem(value))
            finally:
                table.blockSignals(False)
            try:
                if hasattr(self, "on_edit_changed"):
                    self.on_edit_changed()
            except Exception:
                pass

        def on_type_changed(self, row):
            t = row["type_combo"].currentText()

            # Reset everything
            row["value_edit"].setVisible(True)
            row["value_edit2"].setVisible(False)
            row["file_button"].setVisible(False)
            if row.get("options_widget"):
                row["name_edit"].setVisible(False)
            if t == "range":
                row["value_edit"].setPlaceholderText("min")
                row["value_edit2"].setVisible(True)
            elif t == "passthrough" or t == "passfail":
                row["value_edit"].setVisible(False)
            elif t == "image_path":
                row["name_edit"].setVisible(False)
                row["file_button"].setVisible(True)
                row["value_edit"].setPlaceholderText("image file path")
            elif t == "message":
                row["name_edit"].setText("Deletionsaving")
                row["name_edit"].setVisible(False)
            elif t == "method":
                #row["value_edit"].setText("Deletionsaving")
                row["name_edit"].setVisible(False)
            elif t == "options":
                row["name_edit"].setVisible(False)
                row["value_edit"].setVisible(False)
                self.make_options_editor(row)
            if self.specific_method:
                row["name_edit"].setText("output")
                row["name_edit"].setVisible(False)

        def on_edit_changed(self):
            last = self.rows[-1]
            has_text = (
                last["name_edit"].text().strip()
                or last["value_edit"].text().strip()
                or last["value_edit2"].text().strip()
            )
            if last.get("options_widget"):
                table = last["options_widget"]
                for r in range(table.rowCount()):
                    key_item = table.item(r, 0)
                    val_item = table.item(r, 1)
                    if key_item and key_item.text().strip():
                        has_text = True
                    if val_item and val_item.text().strip():
                        has_text = True
            if has_text:
                    self.add_row()
            


        def get_data(self):
            """
            Build YAML-style input mapping, skipping empty rows.
            """
            result = {}
            for row in self.rows:
                name = row["name_edit"].text().strip()
                value1 = row["value_edit"].text().strip()
                value2 = row["value_edit2"].text().strip()
                type_ = row["type_combo"].currentText()
                

                if not name and type_ not in {"message", "options", "image_path", "method", "output"}:
                    continue
                
                if type_ == "image_path":
                    result[type_] = {"type": "direct", "value": value1}
                elif type_ == "options":
                    opts = []
                    table = row.get("options_widget")
                    if table:
                        for r in range(table.rowCount()):
                            key_item = table.item(r, 0)
                            val_item = table.item(r, 1)
                            if key_item and val_item:
                                key = key_item.text().strip()
                                val = val_item.text().strip()
                                if key and val:
                                    if key.lower() in {"yes", "no", "true", "false"}:
                                        key = f"'{key}'"
                                    if val.lower() in {"yes", "no", "true", "false"}:
                                        val = f"'{val}'"
                                    opts.append({key: val})
                    result[type_] = {"type": "direct", "value": opts}
                elif type_ == "message":
                    result[type_] = {"type": "direct", "value": value1}

                elif type_ == "method":
                    result[type_] = {"type": "method", "value": value1}

                elif type_ == "range":
                    if not (value1 and value2):
                        continue  # skip incomplete
                    result[name] = {"type": "range", "min": value1, "max": value2}

                elif type_ == "local":
                    result[name] = {"type": "local", "local_name": value1}

                elif type_ == "global":
                    result[name] = {"type": "global", "global_name": value1}

                elif type_ == "passthrough":
                    result[name] = {"type": "passthrough"}
                elif type_ == "equals":
                    result[name] = {"type": "equals", "value": value1}
                elif type_ == "output":
                    result[type_] = {"type": "equals", "value": value1}
                elif type_ == "passfail":
                    result[name] = {"type": "passfail"}
                else:  # direct
                    result[name] = {"type": "direct", "value": value1}

            return result

        
        def validate(self):
            found_message = False
            found_options = False
            found_image = False
            found_method = False

            for row in self.rows:

                name = row["name_edit"].text().strip()

                type_ = row["type_combo"].currentText()
                value1 = row["value_edit"].text().strip()
                value2 = row["value_edit2"].text().strip()

                if not name and type_ not in {"message", "options", "image_path", "method"}:
                    continue  # ignore blank row
                
                if type_ in ["direct", "global", "local", "equals", "method"] and not value1:
                    return False, f"Parameter '{name}' needs a value."

                if type_ == "range" and (not value1 or not value2):
                    return False, f"Parameter '{name}' needs min and max."


                if type_ == "options":
                    table = row["options_widget"]
                    has_valid = False
                    for r in range(table.rowCount()):
                        key_item = table.item(r, 0)
                        val_item = table.item(r, 1)
                        if key_item and val_item and key_item.text().strip() and val_item.text().strip():
                            has_valid = True
                    if not has_valid:
                        return False, f"Options for '{name}' must contain at least one key/value pair."
                if type_ == "message":
                    found_message = True
                if type_ == "options":
                    found_options = True
                if type_ == "image_path":
                    found_image = True
                if type_ == "method":
                    found_method = True

            # ---- REQUIRED TYPES CHECK ----
            if self.allow_message and not found_message:
                return False, "A 'message' mapping is required."
            if self.allow_options and not found_options:
                return False, "At least one 'options' mapping is required."
            if self.allow_image and not found_image:
                return False, "An 'image_path' mapping is required."
            if self.allow_method and not found_method:
                return False, "A 'method' mapping is required."
            return True, ""


        def load_existing_data(self, data):

            self.clear_gui()

            def safe_set_text(widget, value):
                widget.setText("" if value is None else str(value))
            added_row = False

            for name, info in data.items():

                # Add a row for each mapping
                special_types = {"output", "message", "options", "image_path", "method"}
                is_special = name in special_types

                # Create a row
                if is_special:
                    self.add_special_row(type_name=name)
                    row = self.rows[-1]

                    if name == "options":
                        for opt in info.get("value", []):
                            for k, v in opt.items():
                                table = row["options_widget"]
                                r = table.rowCount() - 1
                                table.setItem(r, 0, QTableWidgetItem(k))
                                table.setItem(r, 1, QTableWidgetItem(v))
                                table.setItem(table.rowCount() - 1, 0, QTableWidgetItem(""))
                                table.setItem(table.rowCount() - 1, 1, QTableWidgetItem(""))

                    elif name in ("image_path", "message", "output", "method","equals"):
                        safe_set_text(row["value_edit"], info.get("value"))
                    else:  # direct / custom name
                        safe_set_text(row["value_edit"], info.get("value"))
                        if not is_special:
                            row["name_edit"].setVisible(True)
                        else:
                            row["name_edit"].setVisible(False)

                else:
                    type_ = info.get("type", "direct")
                    self.add_row()
                    row = self.rows[-1]
                    row["name_edit"].setText(name)
                    row["type_combo"].setCurrentText(type_)
                    # handle specific types
                    if type_ == "range":
                        safe_set_text(row["value_edit"], info.get("min", ""))
                        safe_set_text(row["value_edit2"], info.get("max", ""))
                        row["value_edit2"].setVisible(True)

                    elif type_ == "local":
                        safe_set_text(row["value_edit"], info.get("local_name"))
                    elif type_ == "global":
                        safe_set_text(row["value_edit"], info.get("global_name"))
                    elif type_ in {"equals", "direct", "method"}:
                        safe_set_text(row["value_edit"], info.get("value"))
                    elif type_ == "passfail":
                        pass
                    
                added_row = True

            if not added_row or (self.no_extraSteps is False):
                self.add_row()
            self.del_rows()



        def clear_gui(self):
            for row in getattr(self, "rows", []):
                # remove row widgets from layout
                for key in ["name_edit", "type_combo", "value_edit", "value_edit2", "file_button"]:
                    widget = row.get(key)
                    if widget:
                        widget.setParent(None)
                        widget.deleteLater()
                # remove options table if exists
                table = row.get("options_widget")
                if table:
                    table.setParent(None)
                    table.deleteLater()
            self.rows = []
