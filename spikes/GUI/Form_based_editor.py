# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QScrollArea, QGroupBox, QApplication
)
import sys
import yaml


class StepEditorWidget(QWidget):
    def __init__(self, step_data: dict):
        super().__init__()
        self.step_data = step_data
        self.fields = {}

        layout = QFormLayout()
        for key, value in step_data.items():
            if isinstance(value, dict):
                # Recursively add nested parameters (simplified)
                for sub_key, sub_val in value.items():
                    field = QLineEdit(str(sub_val))
                    layout.addRow(QLabel(f"{key}.{sub_key}:"), field)
                    self.fields[f"{key}.{sub_key}"] = field
            else:
                field = QLineEdit(str(value))
                layout.addRow(QLabel(f"{key}:"), field)
                self.fields[key] = field

        self.setLayout(layout)

    def get_updated_data(self):
        # Reconstruct data from the form
        updated = {}
        for key, field in self.fields.items():
            if '.' in key:
                parent, child = key.split('.')
                updated.setdefault(parent, {})[child] = field.text()
            else:
                updated[key] = field.text()
        return updated


class StepListEditor(QWidget):
    def __init__(self, steps):
        super().__init__()
        layout = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout()

        self.editors = []
        for step in steps:
            group = QGroupBox(step.get("name", "Step"))
            editor = StepEditorWidget(step)
            group.setLayout(editor.layout())
            content_layout.addWidget(group)
            self.editors.append(editor)

        content.setLayout(content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.setLayout(layout)

    def get_all_steps(self):
        return [editor.get_updated_data() for editor in self.editors]


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Simulate loading from YAML
    yaml_str = """
    sequences:
      default:
        description: "Main sequence"
        steps:
          - name: step1
            type: delay
            duration: 5
          - name: step2
            type: measure
            parameters:
              channel: A
    """
    data = yaml.safe_load(yaml_str)
    steps = data["sequences"]["default"]["steps"]

    window = StepListEditor(steps)
    window.resize(400, 400)
    window.show()

    sys.exit(app.exec())
