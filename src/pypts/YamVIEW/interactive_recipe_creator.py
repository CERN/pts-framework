from pypts.YamVIEW.styles import *
import sys
import yaml
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QDialog,
    QLineEdit, QFormLayout, QDialogButtonBox, QSpinBox, QMessageBox
)


class RecipeCreatorDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("New Recipe Creator")
        self.layout = QVBoxLayout(self)

        self.form_layout = QFormLayout()

        self.name_field = QLineEdit("Template Test Recipe")
        self.description_field = QLineEdit("Please describe meaning of the test")
        self.sequence_name_field = QLineEdit("My beautiful sequence")
        self.num_steps_field = QSpinBox()
        self.num_steps_field.setMinimum(1)
        self.num_steps_field.setValue(5)

        self.form_layout.addRow("Recipe Name:", self.name_field)
        self.form_layout.addRow("Description:", self.description_field)
        self.form_layout.addRow("Main Sequence:", self.sequence_name_field)
        self.form_layout.addRow("Number of Steps:", self.num_steps_field)

        self.layout.addLayout(self.form_layout)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def set_dark_mode(self, enabled: bool):
        self.dark_mode = enabled
        if enabled:
            self.setStyleSheet(dark_style)
            ###################################################
        else:
            self.setStyleSheet("")

    def get_data(self):
        return {
            'name': self.name_field.text(),
            'version': "0.0.1",  # hardcoded
            'recipe_version': "1.0.0",  # hardcoded
            'description': self.description_field.text(),
            'main_sequence': self.sequence_name_field.text(),
            'num_steps': self.num_steps_field.value(),
        }


class RecipeCreatorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.generated_recipe = None
        self.setWindowTitle("Recipe Creator")
        layout = QVBoxLayout(self)

        self.create_button = QPushButton("Create New Recipe")
        self.create_button.clicked.connect(self.open_creator_dialog)

        layout.addWidget(self.create_button)

    def get_generated_recipe(self):
        return self.generated_recipe

    def open_creator_dialog(self, dark_mode_enabled):
        dialog = RecipeCreatorDialog()
        dialog.set_dark_mode(dark_mode_enabled)
        dialog.resize(500, 300)
        if dialog.exec():
            data = dialog.get_data()
            yaml_data = self.generate_template_yaml(data)
            self.generated_recipe = yaml_data
            if self.generated_recipe == None:
                return
            else:
                return True

    def generate_template_yaml(self, data):
        header = {
            'name': data['name'],
            'version': data['version'],
            'recipe_version': data['recipe_version'],
            'description': data['description'],
            'main_sequence': data['main_sequence'],
            'globals': {}
        }

        sequence = {
            'sequence_name': data['main_sequence'],
            'description': f"{data['main_sequence']} Description",
            'parameters': {},
            'locals': {},
            'outputs': {},
            'setup_steps': [],
            'steps': [],
            'teardown_steps': []
        }

        for i in range(data['num_steps']):
            step = {
                'steptype': 'UserInteractionStep',
                'step_name': f'Step {i+1}',
                'description': f'Step {i+1} description',
                'skip': 'False',
                'input_mapping': {
                    'message': {'type': 'direct', 'value': 'Put your message here'},
                    'options': {'type': 'direct', 'value': [{'yes': ''}, {'no': ''}]}
                },
                'output_mapping': {
                    'output': {'type': 'equals', 'value': 'yes'}
                }
            }
            sequence['steps'].append(step)

        # Generate the YAML string with two documents
        yaml_string = yaml.dump_all([header, sequence], sort_keys=False)
        print(yaml_string)
        return yaml_string


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = RecipeCreatorApp()
    window.resize(300, 150)
    window.show()
    sys.exit(app.exec())
