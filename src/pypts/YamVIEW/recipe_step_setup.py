# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Schema-driven dialogs used by the YamVIEW recipe editor."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import TypeAdapter, ValidationError
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pypts.recipe_language import Recipe as RecipeDefinition
from pypts.recipe_language import Sequence, StepDefinition


def recipe_form_schema() -> dict[str, Any]:
    """Return the production aggregate schema used to build YamVIEW forms."""
    return RecipeDefinition.model_json_schema(by_alias=True, mode="validation")


def resolve_schema(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local JSON Schema reference without a parallel registry."""
    while "$ref" in node:
        prefix = "#/$defs/"
        reference = node["$ref"]
        if not reference.startswith(prefix):
            raise ValueError(f"Unsupported schema reference: {reference}")
        node = schema["$defs"][reference.removeprefix(prefix)]
    return node


def discriminator_schemas(
    name: str, schema: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Map discriminator values to their resolved model schemas."""
    schema = schema or recipe_form_schema()
    definition = schema["$defs"][name]
    mapping = definition["discriminator"]["mapping"]
    return {
        key: resolve_schema(schema, {"$ref": reference})
        for key, reference in mapping.items()
    }


def schema_widget_kind(field: dict[str, Any]) -> str:
    """Select a control solely from JSON Schema metadata and JSON value type."""
    if "enum" in field or "const" in field:
        return "choice"
    variants = field.get("anyOf", [])
    kinds = {item.get("type") for item in variants}
    if "$ref" in field or any("$ref" in item for item in variants):
        return "structured"
    kind = field.get("type")
    if kind == "boolean":
        return "boolean"
    if kind in {"integer", "number"}:
        return "number"
    if kind == "string":
        return "text"
    if kind in {"array", "object"} or kinds & {"array", "object"} or not (kind or kinds):
        return "structured"
    return "text"


def recipe_form_description(
    schema: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Describe selectors and fields directly from the production JSON Schema."""
    schema = schema or recipe_form_schema()

    def variants(name: str) -> dict[str, Any]:
        result = {}
        for discriminator, definition in discriminator_schemas(name, schema).items():
            required = set(definition.get("required", []))
            result[discriminator] = {
                "title": definition.get("title", discriminator),
                "description": definition.get("description", ""),
                "fields": {
                    field_name: {
                        **field_schema,
                        "required": field_name in required,
                        "widget": schema_widget_kind(field_schema),
                    }
                    for field_name, field_schema in definition.get("properties", {}).items()
                },
            }
        return result

    return {
        "steps": variants("StepDefinition"),
        "inputs": variants("InputMapping"),
        "outputs": variants("OutputMapping"),
    }


def build_schema_widget(field: dict[str, Any], parent=None):
    """Build a primitive or structured editor from one resolved field schema."""
    mapping_reference = field.get("additionalProperties", {}).get("$ref", "")
    if mapping_reference.endswith("/InputMapping"):
        return DiscriminatedMappingWidget("inputs", parent)
    if mapping_reference.endswith("/OutputMapping"):
        return DiscriminatedMappingWidget("outputs", parent)

    kind = schema_widget_kind(field)
    if kind == "choice":
        widget = QComboBox(parent)
        values = field.get("enum", [field.get("const")])
        for value in values:
            widget.addItem(str(value), value)
    elif kind == "boolean":
        widget = QCheckBox(parent)
        widget.setChecked(bool(field.get("default", False)))
    elif kind == "structured":
        widget = QTextEdit(parent)
        if "default" in field:
            widget.setPlainText(json.dumps(field["default"], ensure_ascii=False))
        widget.setMaximumHeight(90)
    else:
        widget = QLineEdit(parent)
        if "default" in field and field["default"] is not None:
            widget.setText(str(field["default"]))

    details = field.get("description", "")
    if field.get("examples"):
        details += f" Example: {field['examples'][0]!r}."
    widget.setToolTip(details)
    return widget


class SchemaFormWidget(QWidget):
    """Generic form whose fields and defaults come entirely from JSON Schema."""

    def __init__(self, variant: dict[str, Any], parent=None):
        super().__init__(parent)
        self.variant = variant
        self.field_widgets: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        description = variant.get("description")
        if description:
            layout.addWidget(QLabel(description))
        for name, field in variant.get("fields", {}).items():
            suffix = " *" if field.get("required") else ""
            label = QLabel(f"{name}{suffix}")
            label.setToolTip(field.get("description", ""))
            widget = build_schema_widget(field, self)
            self.field_widgets[name] = widget
            layout.addWidget(label)
            layout.addWidget(widget)

    def values(self) -> dict[str, Any]:
        """Read Python values from the schema controls."""
        values: dict[str, Any] = {}
        fields = self.variant["fields"]
        for name, widget in self.field_widgets.items():
            field = fields[name]
            if isinstance(widget, DiscriminatedMappingWidget):
                value = widget.values()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QTextEdit):
                text = widget.toPlainText().strip()
                if not text:
                    if "default" not in field and not field.get("required"):
                        continue
                    value = field.get("default")
                else:
                    try:
                        value = json.loads(text)
                    except json.JSONDecodeError as error:
                        widget.setFocus()
                        raise ValueError(
                            f"Field '{name}' must contain valid JSON: {error.msg}."
                        ) from error
            else:
                text = widget.text().strip()
                if not text and not field.get("required"):
                    continue
                value = text
                if field.get("type") in {"integer", "number"}:
                    try:
                        value = json.loads(text)
                    except json.JSONDecodeError as error:
                        widget.setFocus()
                        raise ValueError(f"Field '{name}' must be a number.") from error
            values[name] = value
        return values

    def load_values(self, values: dict[str, Any]) -> None:
        """Populate controls from canonical recipe values."""
        for name, value in values.items():
            widget = self.field_widgets.get(name)
            if widget is None:
                continue
            if isinstance(widget, DiscriminatedMappingWidget):
                widget.load_values(value)
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QTextEdit):
                widget.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            else:
                widget.setText("" if value is None else str(value))


class DiscriminatedMappingWidget(QWidget):
    """Editable input/output rows driven by discriminator schema mappings."""

    def __init__(self, mapping_kind: str, parent=None):
        super().__init__(parent)
        self.variants = recipe_form_description()[mapping_kind]
        self.rows: list[dict[str, Any]] = []
        self.layout = QVBoxLayout(self)
        add_button = QPushButton("Add mapping")
        add_button.clicked.connect(lambda: self.add_row())
        self.layout.addWidget(add_button)

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                DiscriminatedMappingWidget._clear(item.layout())

    def add_row(self, name: str = "", value: dict[str, Any] | None = None) -> None:
        original_value = value or {}
        row_widget = QWidget(self)
        row_layout = QVBoxLayout(row_widget)
        heading = QHBoxLayout()
        name_edit = QLineEdit(row_widget)
        name_edit.setPlaceholderText("mapping name")
        name_edit.setText(name)
        type_combo = QComboBox(row_widget)
        type_combo.addItems(self.variants)
        if original_value.get("type") in self.variants:
            type_combo.setCurrentText(original_value["type"])
        remove_button = QPushButton("Remove", row_widget)
        heading.addWidget(name_edit)
        heading.addWidget(type_combo)
        heading.addWidget(remove_button)
        row_layout.addLayout(heading)
        form_layout = QVBoxLayout()
        row_layout.addLayout(form_layout)
        row = {
            "widget": row_widget,
            "name": name_edit,
            "type": type_combo,
            "form_layout": form_layout,
            "form": None,
            "value": original_value,
        }
        self.rows.append(row)
        self.layout.insertWidget(self.layout.count() - 1, row_widget)

        def render(discriminator: str) -> None:
            self._clear(form_layout)
            form = SchemaFormWidget(self.variants[discriminator], row_widget)
            row["form"] = form
            form_layout.addWidget(form)
            if row["value"].get("type") == discriminator:
                form.load_values(row["value"])
            row["value"] = {}

        def remove() -> None:
            self.rows.remove(row)
            row_widget.setParent(None)
            row_widget.deleteLater()

        type_combo.currentTextChanged.connect(render)
        remove_button.clicked.connect(remove)
        render(type_combo.currentText())

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in self.rows:
            name = row["name"].text().strip()
            if not name:
                row["name"].setFocus()
                raise ValueError("Mapping rows require a name.")
            if name in result:
                row["name"].setFocus()
                raise ValueError(f"Mapping name '{name}' is duplicated.")
            value = row["form"].values()
            value["type"] = row["type"].currentText()
            result[name] = value
        return result

    def load_values(self, values: dict[str, Any]) -> None:
        for row in tuple(self.rows):
            self.rows.remove(row)
            row["widget"].setParent(None)
            row["widget"].deleteLater()
        for name, value in values.items():
            self.add_row(name, value)


class Sequence_setup(QDialog):
    """Small product-oriented dialog for creating a validated empty sequence."""

    def __init__(self, steps=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Sequence Setup")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        self.sequence_name_input = QLineEdit()
        self.sequence_name_input.setPlaceholderText("New sequence name")
        layout.addWidget(QLabel("Sequence name *"))
        layout.addWidget(self.sequence_name_input)
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(70)
        self.description_input.setPlaceholderText("Describe the sequence")
        layout.addWidget(QLabel("Description *"))
        layout.addWidget(self.description_input)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        data = {
            "sequence_name": self.sequence_name_input.text().strip(),
            "description": self.description_input.toPlainText().strip(),
            "parameters": {},
            "outputs": {},
            "locals": {},
            "setup_steps": [],
            "steps": [],
            "teardown_steps": [],
        }
        try:
            definition = Sequence.model_validate(data)
        except ValidationError as error:
            QMessageBox.warning(self, "Invalid sequence", str(error))
            return
        self.result_sequence = definition.model_dump(
            mode="python", by_alias=True, exclude_none=True
        )
        super().accept()


class Skip_setup(QDialog):
    """Bulk editor for schema-defined skip and continue-on-error fields."""

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Step Manager")
        self.resize(600, 400)
        self.steps = steps
        self.rows: list[dict[str, Any]] = []
        layout = QVBoxLayout(self)
        self.sequence_selector = QComboBox()
        self.sequences = [item for item in steps if item.get("steptype") == "sequence_folder"]
        for sequence in self.sequences:
            self.sequence_selector.addItem(sequence["step_name"], sequence["_sequence_id"])
        layout.addWidget(QLabel("Select sequence:"))
        layout.addWidget(self.sequence_selector)
        self.skip = QCheckBox("Skip all")
        self.err = QCheckBox("Continue on error for all")
        toggles = QHBoxLayout()
        toggles.addWidget(self.skip)
        toggles.addWidget(self.err)
        layout.addLayout(toggles)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.sequence_selector.currentIndexChanged.connect(self._load_sequence)
        self.skip.stateChanged.connect(
            lambda checked: [row["skip"].setChecked(bool(checked)) for row in self.rows]
        )
        self.err.stateChanged.connect(
            lambda checked: [row["err"].setChecked(bool(checked)) for row in self.rows]
        )
        self._load_sequence(0)

    def _clear_rows(self) -> None:
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        self.rows.clear()

    def _load_sequence(self, index: int) -> None:
        self._clear_rows()
        sequence_id = self.sequence_selector.itemData(index)
        sequence = next(
            (item for item in self.sequences if item.get("_sequence_id") == sequence_id),
            None,
        )
        if sequence is None:
            return
        for folder in sequence.get("children", []):
            for step in folder.get("children", []):
                node = step["_node"]
                row_layout = QHBoxLayout()
                row_layout.addWidget(QLabel(node.get("step_name", "Unnamed step")))
                skip = QCheckBox("Skip")
                skip.setChecked(node.get("skip", False))
                error = QCheckBox("Continue on error")
                error.setChecked(node.get("continue_on_error", False))
                row_layout.addWidget(skip)
                row_layout.addWidget(error)
                self.container_layout.addLayout(row_layout)
                self.rows.append({"step": step, "skip": skip, "err": error})
        self.container_layout.addStretch()

    def accept(self) -> None:
        for row in self.rows:
            row["step"]["_node"]["skip"] = row["skip"].isChecked()
            row["step"]["_node"]["continue_on_error"] = row["err"].isChecked()
        self.result_steps = self.steps
        super().accept()


class Step_setup(QDialog):
    """Create or edit any StepDefinition through the production JSON Schema."""

    def __init__(self, use_input_mapping=True, use_output_mapping=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New step creation")
        self.resize(500, 500)
        self.AlreadyID = None
        self.form_description = recipe_form_description()
        self._skip_warning = False
        self._previous_step_type = ""
        self.schema_form: SchemaFormWidget | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Step type"))
        self.list_steptype = QComboBox()
        self.list_steptype.addItems(self.form_description["steps"])
        layout.addWidget(self.list_steptype)
        self.step_specific_container = QVBoxLayout()
        container = QWidget()
        container.setLayout(self.step_specific_container)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        buttons.addButton(self.ok_button, QDialogButtonBox.AcceptRole)
        buttons.addButton(self.cancel_button, QDialogButtonBox.RejectRole)
        layout.addWidget(buttons)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        initial_type = self.list_steptype.currentText()
        self._render_schema_step(initial_type)
        self._previous_step_type = initial_type
        self.list_steptype.currentTextChanged.connect(self.on_step_type_changed)

    def _current_values_for_switch(self) -> dict[str, Any]:
        if self.schema_form is None:
            return {}
        try:
            return self.schema_form.values()
        except (TypeError, ValueError):
            return {}

    def on_step_type_changed(self, step_type: str) -> None:
        previous_values = self._current_values_for_switch()
        if self._previous_step_type and not self._skip_warning:
            answer = QMessageBox.question(
                self,
                "Change step type",
                "Compatible common fields will be retained; fields specific to the old "
                "type will be removed. Continue?",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer == QMessageBox.Cancel:
                self.list_steptype.blockSignals(True)
                self.list_steptype.setCurrentText(self._previous_step_type)
                self.list_steptype.blockSignals(False)
                return
        self._previous_step_type = step_type
        self._render_schema_step(step_type, previous_values)

    def _render_schema_step(
        self, step_type: str, retained_values: dict[str, Any] | None = None
    ) -> None:
        self._clear_layout(self.step_specific_container)
        self.schema_form = SchemaFormWidget(self.form_description["steps"][step_type])
        self.step_specific_container.addWidget(self.schema_form)
        self.step_specific_container.addStretch()
        if retained_values:
            allowed = self.form_description["steps"][step_type]["fields"]
            self.schema_form.load_values(
                {name: value for name, value in retained_values.items() if name in allowed}
            )

    def load_definition(self, node: dict[str, Any]) -> None:
        """Load an existing canonical step into the same form used for new steps."""
        step_type = node["steptype"]
        if step_type not in self.form_description["steps"]:
            raise ValueError(f"Unsupported canonical step type: {step_type}")
        self._skip_warning = True
        self.list_steptype.setCurrentText(step_type)
        self._skip_warning = False
        self._previous_step_type = step_type
        assert self.schema_form is not None
        self.schema_form.load_values(node)
        self.setWindowTitle(f"Edit Step: {node.get('step_name', step_type)}")

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                Step_setup._clear_layout(item.layout())

    def accept(self) -> None:
        assert self.schema_form is not None
        step_type = self.list_steptype.currentText()
        try:
            data = self.schema_form.values()
            data["steptype"] = step_type
            definition = TypeAdapter(StepDefinition).validate_python(data)
        except (TypeError, ValueError, ValidationError) as error:
            QMessageBox.warning(self, "Invalid step", str(error))
            return

        node = definition.model_dump(mode="python", by_alias=True, exclude_none=True)
        self.result_step = {
            "steptype": step_type,
            "step_name": definition.step_name,
            "_node": node,
            "_id": self.AlreadyID or str(uuid.uuid4()),
        }
        super().accept()
