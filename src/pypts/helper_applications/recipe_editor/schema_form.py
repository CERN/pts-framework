"""
The Recipe Editor v2's form: one widget per field, generated from recipe_schema.

Nothing here knows a step type. The form walks the Pydantic model of what is
selected - `STEP_SCHEMAS[steptype]` for a step, `HeaderSchema` and
`SequenceSchema` with nothing selected - and picks a widget from what each field
declares (`field_kind()`). A field's `description` is its tooltip and the ⓘ
beside its label; its first example is the placeholder of an empty field. So a
new field or step type in recipe_schema.py appears here without an edit.

Every edit is written through `RecipeModel.set_path()` - one undo entry each,
comments in the YAML kept. The form is rebuilt only when the *shape* of what it
shows changes (another step, another type, an input or output added); otherwise
its fields are refilled in place, so the one being typed in keeps its focus.
Widgets it replaces are deleted later, never on the spot (see recipe_creator.md,
The window): a field commits from inside its own signal.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Callable
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pypts.helper_applications.recipe_creator.rc_model import DELETE, RecipeModel
from pypts.helper_applications.recipe_editor.row_map import StepRef
from pypts.recipe.recipe_parser import steptype_key
from pypts.recipe.recipe_schema import (
    INPUT_TYPES,
    OUTPUT_SCHEMAS,
    STEP_SCHEMAS,
    STEP_TYPE_NAMES,
    HeaderSchema,
    SequenceSchema,
)

# -- what widget a field gets ------------------------------------------------------

SKIP = "skip"
CHECK = "check"
TEXT = "text"
VALUE = "value"
INPUTS = "inputs"
OUTPUTS = "outputs"
TEMPLATE = "template"
PARAMETER_SETS = "parameter_sets"
MAPPING = "mapping"
NAME_LIST = "name_list"
SEQUENCE_CHOICE = "sequence_choice"
YAML_BOX = "yaml"

#: The optional fields every step shares, shown under "More".
MORE_FIELDS = ("description", "image_path", "id", "skip", "continue_on_error")

#: An input entry's two kinds, as the inputs editor names them.
_LITERAL_KIND = "value"
_GLOBAL_KIND = next(iter(INPUT_TYPES))  # "global"

_MISSING = object()


def field_kind(model: type[BaseModel], name: str, info: FieldInfo) -> str:
    """
    The widget a field gets, from what the schema declares for it.

    YAML_BOX is the fallback for a field nothing else fits; a test fails if a
    field of a recipe model ever lands there, so a new kind of field gets a
    widget of its own on purpose.
    """
    annotation = info.annotation
    if annotation is type(None):
        # Declared only to be refused, with its reason as the message.
        return SKIP
    if typing.get_origin(annotation) is typing.Literal:
        # steptype / type: the form's heading, or the output type dropdown.
        return SKIP
    if model is SequenceSchema and name in ("steps", "teardown_steps"):
        # The step table is these.
        return SKIP
    if annotation is bool:
        return CHECK
    if name == "inputs":
        return INPUTS
    if name == "outputs":
        return OUTPUTS
    if name == "template":
        return TEMPLATE
    if name == "parameter_sets":
        return PARAMETER_SETS
    if model is HeaderSchema and name == "main_sequence":
        return SEQUENCE_CHOICE
    origin = typing.get_origin(annotation)
    if origin is dict:
        return MAPPING
    if origin is list and _is_text(typing.get_args(annotation)[0]):
        return NAME_LIST
    if _is_text(annotation):
        return TEXT
    if annotation is Any:
        return VALUE
    return YAML_BOX


def _is_text(annotation: Any) -> bool:
    """str, an Annotated str, or str | None."""
    if annotation is str:
        return True
    if typing.get_origin(annotation) is typing.Annotated:
        return typing.get_args(annotation)[0] is str
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        others = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return len(others) == 1 and others[0] is str
    return False


def label_text(name: str, required: bool) -> str:
    """`wait_time` -> "Wait time *"."""
    text = name.replace("_", " ").capitalize()
    if required:
        text += " *"
    return text


# -- values in and out of text -----------------------------------------------------


def plain(value: Any) -> Any:
    """
    A recipe value as plain Python: ruamel's commented maps, lists and scalars
    are subclasses PyYAML's safe dumper refuses.
    """
    if isinstance(value, dict):
        return {plain(key): plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def value_text(value: Any) -> str:
    """A value as it would be written in YAML, on one line: 2, [A, B], text."""
    if value is _MISSING or value is None:
        return ""
    value = plain(value)
    if isinstance(value, str):
        return value
    text = yaml.safe_dump(value, default_flow_style=True, width=10000, sort_keys=False)
    text = text.strip()
    if text.endswith("..."):
        text = text[:-3].strip()
    return text


def read_value(text: str) -> Any:
    """Text as YAML reads it: "2" a number, "[A, B]" a list; unreadable text stays text."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


# -- the form ------------------------------------------------------------------------


class _Field:
    """One editor in the form: where it writes, how it shows a value, its problem."""

    def __init__(
        self,
        document: int,
        path: tuple[int | str, ...],
        editor: QWidget,
        refresh: Callable[[Any], None],
    ) -> None:
        self.document = document
        self.path = path
        self.editor = editor
        self.refresh = refresh
        self.problem_label = QLabel()
        self.problem_label.setObjectName("formProblem")
        self.problem_label.setWordWrap(True)
        self.problem_label.setVisible(False)

    def set_problem(self, message: str) -> None:
        self.problem_label.setText(message)
        self.problem_label.setVisible(bool(message))
        self.editor.setProperty("problem", bool(message))
        self.editor.style().unpolish(self.editor)
        self.editor.style().polish(self.editor)


class SchemaForm(QScrollArea):
    """The right-hand column: the selected step's fields, or the header's and sequence's."""

    def __init__(
        self, model: RecipeModel, parent: QWidget | None = None, fit_content: bool = False
    ) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        # Inside a card (Cards view) the form is as tall as its fields, with no
        # scroll bar of its own: the cards scroll as a whole.
        self._fit_content = fit_content
        if fit_content:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._model = model
        self._ref: StepRef | None = None
        self._sequence_index = 0
        self._fields: list[_Field] = []
        self._shape: Any = None
        self._issues: list = []
        self._more_open = False
        self._content: QWidget | None = None
        self.show_step(None, 0)

    # -- what is shown -----------------------------------------------------------

    def show_step(self, ref: StepRef | None, sequence_index: int) -> None:
        """Show an authored step, or (None) the header and sequence `sequence_index`."""
        self._ref = ref
        self._sequence_index = sequence_index
        self._rebuild()

    def current_ref(self) -> StepRef | None:
        return self._ref

    def refresh(self) -> None:
        """After a model change: refill in place, or rebuild if the shape changed."""
        if self._ref is not None and self._value(self._ref.document, self._ref.path()) is _MISSING:
            # The step is gone (deleted, undone): back to the header.
            self._ref = None
        if self._current_shape() != self._shape:
            self._rebuild()
            return
        for field in self._fields:
            field.refresh(self._value(field.document, field.path))
        self._apply_issues()

    def set_issues(self, issues: list) -> None:
        """The verificator's issues; those with a path outline their field."""
        self._issues = issues
        self._apply_issues()

    # -- reading the model ---------------------------------------------------------

    def _documents(self) -> list[Any]:
        if self._model.is_empty():
            return []
        return [self._model.header(), *self._model.sequences()]

    def _value(self, document: int, path: tuple[int | str, ...]) -> Any:
        documents = self._documents()
        if document >= len(documents):
            return _MISSING
        value: Any = documents[document]
        for key in path:
            if isinstance(value, dict):
                if key not in value:
                    return _MISSING
                value = value[key]
            elif isinstance(value, list) and isinstance(key, int):
                if key >= len(value):
                    return _MISSING
                value = value[key]
            else:
                return _MISSING
        return value

    def _mapping_now(self, document: int, path: tuple[int | str, ...]) -> dict:
        """The mapping at `path` as the model has it right now ({} if none)."""
        value = self._value(document, path)
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _write(self, document: int, path: tuple[int | str, ...], value: Any) -> None:
        current = self._value(document, path)
        if value is DELETE and current is _MISSING:
            return
        if value is not DELETE and current is not _MISSING and plain(current) == plain(value):
            return
        self._model.set_path(document, path, value)

    # -- shape: what decides a rebuild ---------------------------------------------

    def _current_shape(self) -> Any:
        if self._model.is_empty() or not self._model.is_valid():
            return ("none",)
        if self._ref is None:
            header = self._value(0, ())
            names = tuple(str(seq.get("sequence_name", "")) for seq in self._model.sequences())
            globals_value = header.get("globals") if isinstance(header, dict) else None
            return ("header", self._sequence_index, names, _keys_shape(globals_value))
        step = self._value(self._ref.document, self._ref.path())
        return ("step", self._ref.document, self._ref.list_name, self._ref.step_index,
                _step_shape(step))

    # -- building --------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._fields = []
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(8)

        if self._model.is_empty() or not self._model.is_valid():
            note = QLabel("Nothing to edit while there is no recipe the tree can show.")
            note.setObjectName("formHelp")
            note.setWordWrap(True)
            column.addWidget(note)
        elif self._ref is None:
            self._build_header(column)
        else:
            step = self._value(self._ref.document, self._ref.path())
            self._build_step(column, step)
        column.addStretch()

        old = self.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.setWidget(content)
        self._content = content
        self._shape = self._current_shape()
        for field in self._fields:
            field.refresh(self._value(field.document, field.path))
        self._apply_issues()
        if self._fit_content:
            self.setFixedHeight(content.sizeHint().height() + 4)

    def set_refs(self, refs: list, sequence_index: int) -> None:
        """The views' common call after the table is rebuilt; one step at a time needs none."""

    def _heading(self, column: QVBoxLayout, title: str, help_text: str) -> None:
        title_label = QLabel(title)
        title_label.setObjectName("formTitle")
        column.addWidget(title_label)
        if help_text:
            help_label = QLabel(help_text)
            help_label.setObjectName("formHelp")
            help_label.setWordWrap(True)
            column.addWidget(help_label)

    def _build_header(self, column: QVBoxLayout) -> None:
        self._heading(
            column,
            "Recipe",
            "Select a step in the table, or put the cursor in it in the YAML, to edit it.",
        )
        recipe_group = QGroupBox("Recipe")
        recipe_form = QFormLayout(recipe_group)
        self._add_model_fields(recipe_form, HeaderSchema, 0, (), set())
        column.addWidget(recipe_group)

        sequences = self._model.sequences()
        if self._sequence_index < len(sequences):
            name = sequences[self._sequence_index].get("sequence_name", "")
            sequence_group = QGroupBox(f"Sequence '{name}'")
            sequence_form = QFormLayout(sequence_group)
            self._add_model_fields(
                sequence_form, SequenceSchema, self._sequence_index + 1, (), set()
            )
            column.addWidget(sequence_group)

    def _build_step(self, column: QVBoxLayout, step: Any) -> None:
        assert self._ref is not None
        steptype = ""
        if isinstance(step, dict):
            steptype = steptype_key(step.get("steptype"))
        model = STEP_SCHEMAS.get(steptype)
        if model is None:
            self._heading(
                column,
                "Unknown step type",
                f"'{step.get('steptype') if isinstance(step, dict) else step}' is not a "
                "step type. Change it in the YAML; the problems list names the types.",
            )
            return
        self._build_step_fields(column, model, self._ref.document, self._ref.path())

    def _build_step_fields(
        self,
        column: QVBoxLayout,
        model: type[BaseModel],
        document: int,
        prefix: tuple[int | str, ...],
    ) -> None:
        steptype = typing.get_args(model.model_fields["steptype"].annotation)[0]
        title = STEP_TYPE_NAMES.get(steptype, steptype)
        self._heading(column, title, model.model_fields["steptype"].description or "")

        main_group = QGroupBox("Step")
        main_form = QFormLayout(main_group)
        self._add_model_fields(main_form, model, document, prefix, set(MORE_FIELDS))
        column.addWidget(main_group)

        # The optional fields every step shares, folded unless one is in use.
        more_names = [name for name in MORE_FIELDS if name in model.model_fields]
        if more_names:
            in_use = False
            for name in more_names:
                value = self._value(document, (*prefix, name))
                if value is not _MISSING and value != model.model_fields[name].default:
                    in_use = True
            more_button = QToolButton()
            more_button.setText("More")
            more_button.setCheckable(True)
            more_button.setAutoRaise(True)
            more_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            more_box = QWidget()
            more_form = QFormLayout(more_box)
            only_more = {name for name in model.model_fields if name not in more_names}
            self._add_model_fields(more_form, model, document, prefix, only_more)
            # Into the form first: a widget shown before it has a parent is a
            # window of its own, which flashed up on every row click.
            column.addWidget(more_button)
            column.addWidget(more_box)
            open_now = self._more_open or in_use
            more_box.setVisible(open_now)
            more_button.setChecked(open_now)
            if open_now:
                more_button.setArrowType(Qt.ArrowType.DownArrow)
            else:
                more_button.setArrowType(Qt.ArrowType.RightArrow)

            def toggle(checked: bool) -> None:
                self._more_open = checked
                more_box.setVisible(checked)
                if checked:
                    more_button.setArrowType(Qt.ArrowType.DownArrow)
                else:
                    more_button.setArrowType(Qt.ArrowType.RightArrow)

            more_button.toggled.connect(toggle)

        for name, info in model.model_fields.items():
            kind = field_kind(model, name, info)
            path = (*prefix, name)
            if kind == INPUTS:
                column.addWidget(self._inputs_group(document, path, info))
            elif kind == OUTPUTS:
                column.addWidget(self._outputs_group(document, path, info))
            elif kind == TEMPLATE:
                column.addWidget(self._template_group(document, path))
            elif kind == PARAMETER_SETS:
                column.addWidget(self._parameter_sets_group(document, prefix, info))

    def _add_model_fields(
        self,
        form: QFormLayout,
        model: type[BaseModel],
        document: int,
        prefix: tuple[int | str, ...],
        leave_out: set[str],
    ) -> None:
        """The simple fields of `model`: required first, then optional, in model order."""
        names = [name for name, info in model.model_fields.items() if info.is_required()]
        names += [name for name, info in model.model_fields.items() if not info.is_required()]
        for name in names:
            if name in leave_out:
                continue
            info = model.model_fields[name]
            kind = field_kind(model, name, info)
            if kind in (SKIP, INPUTS, OUTPUTS, TEMPLATE, PARAMETER_SETS):
                continue
            field = self._simple_field(kind, document, (*prefix, name), info)
            self._add_row(form, name, info, field)

    def _add_row(self, form: QFormLayout, name: str, info: FieldInfo, field: _Field) -> None:
        label = QLabel(label_text(name, info.is_required()) + "  ⓘ")
        description = info.description or ""
        label.setToolTip(description)
        field.editor.setToolTip(description)
        cell = QWidget()
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setSpacing(2)
        cell_layout.addWidget(field.editor)
        cell_layout.addWidget(field.problem_label)
        form.addRow(label, cell)
        self._fields.append(field)

    # -- simple fields ---------------------------------------------------------------

    def _simple_field(
        self, kind: str, document: int, path: tuple[int | str, ...], info: FieldInfo
    ) -> _Field:
        required = info.is_required()
        placeholder = ""
        if info.examples:
            placeholder = value_text(info.examples[0])

        if kind == CHECK:
            box = QCheckBox()
            default = bool(info.default) if not required else False

            def show_check(value: Any) -> None:
                box.blockSignals(True)
                if value is _MISSING:
                    box.setChecked(default)
                else:
                    box.setChecked(bool(value))
                box.blockSignals(False)

            box.toggled.connect(lambda checked: self._write(document, path, bool(checked)))
            return _Field(document, path, box, show_check)

        if kind == SEQUENCE_CHOICE:
            combo = QComboBox()

            def show_choice(value: Any) -> None:
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("")
                for sequence in self._model.sequences():
                    combo.addItem(str(sequence.get("sequence_name", "")))
                current = "" if value is _MISSING or value is None else str(value)
                index = combo.findText(current)
                if index < 0:
                    combo.addItem(current)
                    index = combo.count() - 1
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

            def choose(index: int) -> None:
                text = combo.itemText(index)
                if text:
                    self._write(document, path, text)
                else:
                    self._write(document, path, DELETE)

            combo.activated.connect(choose)
            combo.setToolTip("Empty: the first sequence.")
            return _Field(document, path, combo, show_choice)

        if kind == MAPPING:
            return self._mapping_field(document, path, info)

        if kind == YAML_BOX:
            return self._yaml_field(document, path, required)

        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)

        def show_text(value: Any) -> None:
            if kind == NAME_LIST:
                if isinstance(value, list):
                    text = ", ".join(str(item) for item in value)
                else:
                    text = value_text(value)
            else:
                text = value_text(value)
            if edit.text() != text:
                edit.setText(text)
                edit.setCursorPosition(0)

        def commit() -> None:
            text = edit.text().strip()
            if not text:
                if required:
                    self._write(document, path, "")
                else:
                    self._write(document, path, DELETE)
                return
            if kind == NAME_LIST:
                names = [part.strip() for part in text.split(",") if part.strip()]
                self._write(document, path, names)
            elif kind == VALUE:
                self._write(document, path, read_value(text))
            else:
                self._write(document, path, text)

        edit.editingFinished.connect(commit)
        return _Field(document, path, edit, show_text)

    def _yaml_field(self, document: int, path: tuple[int | str, ...], required: bool) -> _Field:
        """The fallback: one field as a small YAML box, written when it parses."""
        box = QPlainTextEdit()
        box.setFixedHeight(80)
        timer = QTimer(box)
        timer.setSingleShot(True)
        timer.setInterval(700)
        showing = [False]

        def show_yaml(value: Any) -> None:
            if box.hasFocus():
                return
            if value is _MISSING:
                text = ""
            else:
                text = yaml.safe_dump(plain(value), sort_keys=False).strip()
            if box.toPlainText() != text:
                showing[0] = True
                box.setPlainText(text)
                showing[0] = False

        def commit() -> None:
            text = box.toPlainText().strip()
            if not text:
                if not required:
                    self._write(document, path, DELETE)
                return
            try:
                self._write(document, path, yaml.safe_load(text))
            except yaml.YAMLError:
                return

        box.textChanged.connect(lambda: None if showing[0] else timer.start())
        timer.timeout.connect(commit)
        return _Field(document, path, box, show_yaml)

    def _mapping_field(self, document: int, path: tuple[int | str, ...], info: FieldInfo) -> _Field:
        """Name / value rows - the header's globals."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        rows: list[tuple[QLineEdit, QLineEdit]] = []

        def current() -> dict:
            value = self._value(document, path)
            if isinstance(value, dict):
                return dict(value)
            return {}

        def commit() -> None:
            result: dict = {}
            for name_edit, value_edit in rows:
                name = name_edit.text().strip()
                if name:
                    result[name] = read_value(value_edit.text()) if value_edit.text() else ""
            self._write(document, path, result)

        def show_mapping(value: Any) -> None:
            mapping = value if isinstance(value, dict) else {}
            for (name_edit, value_edit), (key, item) in zip(rows, mapping.items(), strict=False):
                text = value_text(item)
                if name_edit.text() != str(key):
                    name_edit.setText(str(key))
                if value_edit.text() != text:
                    value_edit.setText(text)

        mapping = current()
        for key, item in mapping.items():
            row = QHBoxLayout()
            name_edit = QLineEdit(str(key))
            value_edit = QLineEdit(value_text(item))
            value_edit.setPlaceholderText("initial value")
            remove = _small_button("✕", f"Remove {key}")
            name_edit.editingFinished.connect(commit)
            value_edit.editingFinished.connect(commit)
            remove.clicked.connect(
                lambda _checked=False, gone=key: self._write(
                    document, path, {k: v for k, v in current().items() if k != gone}
                )
            )
            row.addWidget(name_edit, 1)
            row.addWidget(value_edit, 1)
            row.addWidget(remove)
            layout.addLayout(row)
            rows.append((name_edit, value_edit))

        add = QPushButton("+ Add")
        add.clicked.connect(
            lambda _checked=False: self._write(
                document, path, {**current(), _new_name(current(), "name"): ""}
            )
        )
        layout.addWidget(add)
        return _Field(document, path, box, show_mapping)

    # -- inputs and outputs ------------------------------------------------------------

    def _inputs_group(
        self, document: int, path: tuple[int | str, ...], info: FieldInfo
    ) -> QGroupBox:
        value = self._value(document, path)
        mapping = dict(value) if isinstance(value, dict) else {}
        group = QGroupBox(f"Inputs ({len(mapping)})")
        group.setToolTip(info.description or "")
        layout = QVBoxLayout(group)
        rows: list[tuple[QLineEdit, QComboBox, QLineEdit]] = []

        def commit() -> None:
            result: dict = {}
            for name_edit, kind_combo, value_edit in rows:
                name = name_edit.text().strip()
                if not name:
                    continue
                if kind_combo.currentText() == _GLOBAL_KIND:
                    result[name] = {"type": _GLOBAL_KIND, "global_name": value_edit.text().strip()}
                else:
                    result[name] = read_value(value_edit.text()) if value_edit.text() else ""
            self._write(document, path, result)

        for key, entry in mapping.items():
            row = QHBoxLayout()
            name_edit = QLineEdit(str(key))
            name_edit.setPlaceholderText("argument")
            kind_combo = QComboBox()
            kind_combo.addItems([_LITERAL_KIND, _GLOBAL_KIND])
            value_edit = QLineEdit()
            if isinstance(entry, dict):
                kind_combo.setCurrentText(_GLOBAL_KIND)
                value_edit.setText(value_text(entry.get("global_name")))
                value_edit.setPlaceholderText("global_name")
            else:
                value_edit.setText(value_text(entry))
                value_edit.setPlaceholderText("value")
            remove = _small_button("✕", f"Remove {key}")
            name_edit.editingFinished.connect(commit)
            value_edit.editingFinished.connect(commit)
            kind_combo.activated.connect(lambda _index: commit())
            remove.clicked.connect(
                lambda _checked=False, gone=key: self._write(
                    document,
                    path,
                    {k: v for k, v in self._mapping_now(document, path).items() if k != gone},
                )
            )
            row.addWidget(name_edit, 2)
            row.addWidget(kind_combo, 1)
            row.addWidget(value_edit, 2)
            row.addWidget(remove)
            layout.addLayout(row)
            rows.append((name_edit, kind_combo, value_edit))

        add = QPushButton("+ Add input")
        add.clicked.connect(lambda _checked=False: self._add_entry(document, path, "input", ""))
        layout.addWidget(add)

        def show_inputs(value: Any) -> None:
            entries = value if isinstance(value, dict) else {}
            for (name_edit, _kind, value_edit), (key, entry) in zip(
                rows, entries.items(), strict=False
            ):
                _set_if_changed(name_edit, str(key))
                if isinstance(entry, dict):
                    _set_if_changed(value_edit, value_text(entry.get("global_name")))
                else:
                    _set_if_changed(value_edit, value_text(entry))

        field = _Field(document, path, group, show_inputs)
        layout.addWidget(field.problem_label)
        self._fields.append(field)
        return group

    def _outputs_group(
        self, document: int, path: tuple[int | str, ...], info: FieldInfo
    ) -> QGroupBox:
        value = self._value(document, path)
        mapping = dict(value) if isinstance(value, dict) else {}
        group = QGroupBox(f"Outputs ({len(mapping)})")
        group.setToolTip(info.description or "")
        layout = QVBoxLayout(group)
        type_names = sorted(OUTPUT_SCHEMAS)
        rows: list[tuple[QLineEdit, QComboBox, dict[str, QLineEdit]]] = []

        def commit() -> None:
            result: dict = {}
            for name_edit, type_combo, edits in rows:
                name = name_edit.text().strip()
                if not name:
                    continue
                entry: dict = {"type": type_combo.currentText()}
                for field_name, edit in edits.items():
                    if edit.text().strip():
                        entry[field_name] = read_value(edit.text())
                result[name] = entry
            self._write(document, path, result)

        def change_type(entry_name: Any, new_type: str) -> None:
            # Keep what still applies; the new type's other fields start empty.
            result: dict = {}
            for key, entry in self._mapping_now(document, path).items():
                if key != entry_name:
                    result[key] = entry
                    continue
                kept: dict = {"type": new_type}
                if isinstance(entry, dict):
                    for field_name in OUTPUT_SCHEMAS[new_type].model_fields:
                        if field_name != "type" and field_name in entry:
                            kept[field_name] = entry[field_name]
                result[key] = kept
            self._write(document, path, result)

        for key, entry in mapping.items():
            row = QHBoxLayout()
            name_edit = QLineEdit(str(key))
            name_edit.setPlaceholderText("output")
            type_combo = QComboBox()
            type_combo.addItems(type_names)
            declared = ""
            if isinstance(entry, dict):
                declared = str(entry.get("type", "")).lower()
            if declared in OUTPUT_SCHEMAS:
                type_combo.setCurrentText(declared)
            else:
                type_combo.insertItem(0, declared or "?")
                type_combo.setCurrentIndex(0)
            type_model = OUTPUT_SCHEMAS.get(declared)
            if type_model is not None:
                type_combo.setToolTip(type_model.model_fields["type"].description or "")
            edits: dict[str, QLineEdit] = {}
            row.addWidget(name_edit, 2)
            row.addWidget(type_combo, 1)
            if type_model is not None:
                for field_name, field_info in type_model.model_fields.items():
                    if field_name == "type":
                        continue
                    edit = QLineEdit()
                    current = entry.get(field_name) if isinstance(entry, dict) else None
                    edit.setText(value_text(current))
                    edit.setPlaceholderText(field_name)
                    edit.setToolTip(field_info.description or "")
                    edit.editingFinished.connect(commit)
                    edits[field_name] = edit
                    row.addWidget(edit, 1)
            remove = _small_button("✕", f"Remove {key}")
            remove.clicked.connect(
                lambda _checked=False, gone=key: self._write(
                    document,
                    path,
                    {k: v for k, v in self._mapping_now(document, path).items() if k != gone},
                )
            )
            name_edit.editingFinished.connect(commit)
            type_combo.activated.connect(
                lambda _index, combo=type_combo, entry_name=key: change_type(
                    entry_name, combo.currentText()
                )
            )
            row.addWidget(remove)
            layout.addLayout(row)
            rows.append((name_edit, type_combo, edits))

        add = QPushButton("+ Add output")
        add.clicked.connect(
            lambda _checked=False: self._add_entry(document, path, "result", {"type": "pass"})
        )
        layout.addWidget(add)

        def show_outputs(value: Any) -> None:
            entries = value if isinstance(value, dict) else {}
            for (name_edit, _type, edits), (key, entry) in zip(
                rows, entries.items(), strict=False
            ):
                _set_if_changed(name_edit, str(key))
                for field_name, edit in edits.items():
                    current = entry.get(field_name) if isinstance(entry, dict) else None
                    _set_if_changed(edit, value_text(current))

        field = _Field(document, path, group, show_outputs)
        layout.addWidget(field.problem_label)
        self._fields.append(field)
        return group

    # -- Indexed -----------------------------------------------------------------------

    def _template_group(self, document: int, path: tuple[int | str, ...]) -> QGroupBox:
        template = self._value(document, path)
        steptype = ""
        if isinstance(template, dict):
            steptype = steptype_key(template.get("steptype"))
        model = STEP_SCHEMAS.get(steptype)
        group = QGroupBox("Template")
        layout = QVBoxLayout(group)
        if model is None or model is STEP_SCHEMAS.get("indexed"):
            field = self._yaml_field(document, path, True)
            layout.addWidget(field.editor)
            layout.addWidget(field.problem_label)
            self._fields.append(field)
            return group
        self._build_step_fields(layout, model, document, path)
        return group

    def _parameter_sets_group(
        self, document: int, step_path: tuple[int | str, ...], info: FieldInfo
    ) -> QGroupBox:
        path = (*step_path, "parameter_sets")
        value = self._value(document, path)
        sets = list(value) if isinstance(value, list) else []
        template = self._value(document, (*step_path, "template"))

        # Columns: the template's inputs, then its outputs, then any extra key a set uses.
        input_names: list[str] = []
        expect_names: list[str] = []
        if isinstance(template, dict):
            for name in template.get("inputs") or {}:
                input_names.append(str(name))
            for name in template.get("outputs") or {}:
                expect_names.append(str(name))
        for one_set in sets:
            if not isinstance(one_set, dict):
                continue
            for name in one_set.get("inputs") or {}:
                if str(name) not in input_names:
                    input_names.append(str(name))
            for name in one_set.get("expect") or {}:
                if str(name) not in expect_names:
                    expect_names.append(str(name))

        group = QGroupBox(f"Parameter sets ({len(sets)})")
        group.setToolTip(info.description or "")
        layout = QVBoxLayout(group)
        table = QTableWidget(len(sets), len(input_names) + len(expect_names))
        headers = [f"in: {name}" for name in input_names]
        headers += [f"expect: {name}" for name in expect_names]
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, one_set in enumerate(sets):
            inputs = one_set.get("inputs") or {} if isinstance(one_set, dict) else {}
            expect = one_set.get("expect") or {} if isinstance(one_set, dict) else {}
            for column, name in enumerate(input_names):
                table.setItem(row, column, QTableWidgetItem(value_text(inputs.get(name, _MISSING))))
            for offset, name in enumerate(expect_names):
                column = len(input_names) + offset
                table.setItem(row, column, QTableWidgetItem(value_text(expect.get(name, _MISSING))))
        table.setMinimumHeight(min(60 + 30 * len(sets), 260))

        def commit(_item: QTableWidgetItem) -> None:
            result = []
            for row in range(table.rowCount()):
                one: dict = {}
                inputs: dict = {}
                expect: dict = {}
                for column, name in enumerate(input_names):
                    item = table.item(row, column)
                    if item is not None and item.text().strip():
                        inputs[name] = read_value(item.text())
                for offset, name in enumerate(expect_names):
                    item = table.item(row, len(input_names) + offset)
                    if item is not None and item.text().strip():
                        expect[name] = read_value(item.text())
                if inputs:
                    one["inputs"] = inputs
                if expect:
                    one["expect"] = expect
                result.append(one)
            self._write(document, path, result)

        table.itemChanged.connect(commit)

        buttons = QHBoxLayout()
        def sets_now() -> list:
            value = self._value(document, path)
            if isinstance(value, list):
                return list(value)
            return []

        def remove_selected() -> None:
            chosen = table.currentRow()
            if chosen < 0:
                return
            self._write(
                document, path, [one for index, one in enumerate(sets_now()) if index != chosen]
            )

        add = QPushButton("+ Add set")
        add.clicked.connect(
            lambda _checked=False: self._write(document, path, [*sets_now(), {"inputs": {}}])
        )
        remove = QPushButton("Remove selected set")
        remove.clicked.connect(lambda _checked=False: remove_selected())
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addWidget(table)
        layout.addLayout(buttons)
        def show_sets(value: Any) -> None:
            shown = value if isinstance(value, list) else []
            table.blockSignals(True)
            for row, one_set in enumerate(shown[: table.rowCount()]):
                inputs = one_set.get("inputs") or {} if isinstance(one_set, dict) else {}
                expect = one_set.get("expect") or {} if isinstance(one_set, dict) else {}
                cells = [inputs.get(name, _MISSING) for name in input_names]
                cells += [expect.get(name, _MISSING) for name in expect_names]
                for column, cell in enumerate(cells):
                    item = table.item(row, column)
                    text = value_text(cell)
                    if item is None:
                        table.setItem(row, column, QTableWidgetItem(text))
                    elif item.text() != text:
                        item.setText(text)
            table.blockSignals(False)

        field = _Field(document, path, table, show_sets)
        layout.addWidget(field.problem_label)
        self._fields.append(field)
        return group

    def _add_entry(self, document: int, path: tuple[int | str, ...], stem: str, entry: Any) -> None:
        """A new inputs/outputs entry, named stem_1, stem_2, ... - the mapping made if absent."""
        mapping = self._mapping_now(document, path)
        mapping[_new_name(mapping, stem)] = entry
        self._write(document, path, mapping)

    # -- problems on fields --------------------------------------------------------------

    def _apply_issues(self) -> None:
        for field in self._fields:
            field.set_problem("")
        for issue in self._issues:
            path = tuple(getattr(issue, "path", ()) or ())
            document = getattr(issue, "document", None)
            if document is None or not path:
                continue
            best: _Field | None = None
            for field in self._fields:
                if field.document != document:
                    continue
                if path[: len(field.path)] != field.path:
                    continue
                if best is None or len(field.path) > len(best.path):
                    best = field
            if best is not None:
                message = issue.message
                if best.problem_label.isVisible():
                    message = best.problem_label.text() + "\n" + message
                best.set_problem(message)


# -- helpers --------------------------------------------------------------------------


def _small_button(text: str, tooltip: str) -> QPushButton:
    from pypts.helper_applications.recipe_creator.rc_widgets import SMALL_BUTTON_NAME

    button = QPushButton(text)
    button.setObjectName(SMALL_BUTTON_NAME)
    button.setFixedSize(28, 28)
    button.setToolTip(tooltip)
    return button


def _set_if_changed(edit: QLineEdit, text: str) -> None:
    """Rewrite a field only when the model's text differs and it is not being typed in."""
    if edit.text() != text and not edit.hasFocus():
        edit.setText(text)
        edit.setCursorPosition(0)


def _new_name(mapping: Any, stem: str) -> str:
    """`stem_1`, `stem_2`, ... - the first not already a key."""
    number = 1
    while f"{stem}_{number}" in mapping:
        number += 1
    return f"{stem}_{number}"


def _keys_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(str(key) for key in value)
    return None


def _step_shape(step: Any) -> Any:
    """What the form's layout depends on: the type, the entries, the template, the sets."""
    if not isinstance(step, dict):
        return ("not a mapping",)
    inputs = step.get("inputs")
    input_shape = None
    if isinstance(inputs, dict):
        input_shape = tuple((str(key), isinstance(entry, dict)) for key, entry in inputs.items())
    outputs = step.get("outputs")
    output_shape = None
    if isinstance(outputs, dict):
        output_shape = tuple(
            (str(key), str(entry.get("type", "")).lower() if isinstance(entry, dict) else "?")
            for key, entry in outputs.items()
        )
    sets = step.get("parameter_sets")
    set_shape = None
    if isinstance(sets, list):
        keys = []
        for one_set in sets:
            if isinstance(one_set, dict):
                keys.append(
                    (_keys_shape(one_set.get("inputs")), _keys_shape(one_set.get("expect")))
                )
            else:
                keys.append(None)
        set_shape = tuple(keys)
    template = step.get("template")
    template_shape = _step_shape(template) if isinstance(template, dict) else None
    return (
        steptype_key(step.get("steptype")),
        input_shape,
        output_shape,
        set_shape,
        template_shape,
    )
