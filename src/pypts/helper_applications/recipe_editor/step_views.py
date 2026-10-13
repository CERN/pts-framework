"""
The right-hand panel's other ways of editing: Cards, Grid and Outline.

The Form view is `schema_form.SchemaForm` itself. These three show more than one
step at a time - like the Recipe Creator's Card and List views - and all go
through the same `RecipeModel`, so their edits share the one undo history.

Each view has the panel's calls: `show_step(ref, sequence_index)` (what the
window selected), `set_refs(refs, sequence_index)` (every authored step, after the
table is rebuilt), `refresh()` (after any model change), `set_issues(issues)`. A
view that lets the user pick a step emits `step_chosen` with its StepRef (None
for the header); the window then selects it everywhere.
"""

from __future__ import annotations

from typing import Any

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_editor.row_map import StepRef
from pypts.helper_applications.recipe_editor.schema_form import (
    TEXT,
    VALUE,
    SchemaForm,
    field_kind,
    plain,
    value_text,
)
from pypts.hmi.gui.palette import get_palette
from pypts.recipe.recipe_parser import steptype_key
from pypts.recipe.recipe_schema import STEP_SCHEMAS, STEP_TYPE_NAMES


def _key(ref: StepRef) -> tuple[int, str, int]:
    """A step's identity, whatever its lines are now."""
    return (ref.sequence_index, ref.list_name, ref.step_index)


def _step(model: RecipeModel, ref: StepRef) -> dict:
    """The authored step a ref points at, {} if it is gone."""
    sequences = model.sequences()
    if ref.sequence_index >= len(sequences):
        return {}
    steps = sequences[ref.sequence_index].get(ref.list_name) or []
    if ref.step_index >= len(steps) or not isinstance(steps[ref.step_index], dict):
        return {}
    return steps[ref.step_index]


def step_title(step: dict) -> str:
    """`[Wait] Settle` - a Sequence step, which has no name, by what it calls."""
    steptype = STEP_TYPE_NAMES.get(steptype_key(step.get("steptype")), str(step.get("steptype")))
    if steptype_key(step.get("steptype")) == "sequence":
        return f"[{steptype}] → {step.get('sequence_name', '')}"
    return f"[{steptype}] {step.get('step_name', '')}"


def _sequence_refs(refs: list[StepRef], sequence_index: int) -> list[StepRef]:
    return [ref for ref in refs if ref.sequence_index == sequence_index]


def _has_problem(issues: list, ref: StepRef) -> bool:
    for issue in issues:
        path = tuple(getattr(issue, "path", ()) or ())
        if getattr(issue, "document", None) == ref.document and path[:2] == ref.path():
            return True
    return False


# -- Cards --------------------------------------------------------------------------------


class CardsView(QScrollArea):
    """Every step of the sequence as a card; the selected one is open, with its form."""

    step_chosen = Signal(object)

    def __init__(self, model: RecipeModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._model = model
        self._refs: list[StepRef] = []
        self._sequence_index = 0
        self._selected: StepRef | None = None
        self._issues: list = []
        self._form: SchemaForm | None = None
        self._headers: list[tuple[StepRef, QToolButton]] = []
        self._shown_keys: list[tuple[int, str, int]] = []
        self._shown_open: tuple[int, str, int] | None = None

    def show_step(self, ref: StepRef | None, sequence_index: int) -> None:
        self._selected = ref
        self._sequence_index = sequence_index
        self._rebuild_if_needed()

    def set_refs(self, refs: list[StepRef], sequence_index: int) -> None:
        self._refs = _sequence_refs(refs, sequence_index)
        self._sequence_index = sequence_index
        self._rebuild_if_needed()

    def current_ref(self) -> StepRef | None:
        return self._selected

    def refresh(self) -> None:
        for ref, header in self._headers:
            step = _step(self._model, ref)
            if step:
                header.setText(step_title(step))
        if self._form is not None:
            self._form.refresh()

    def set_issues(self, issues: list) -> None:
        self._issues = issues
        if self._form is not None:
            self._form.set_issues(issues)
        self._paint_headers()

    def set_dark(self, _dark: bool) -> None:
        self._paint_headers()

    def _rebuild_if_needed(self) -> None:
        keys = [_key(ref) for ref in self._refs]
        open_key = _key(self._selected) if self._selected is not None else None
        if keys == self._shown_keys and open_key == self._shown_open:
            return
        self._shown_keys = keys
        self._shown_open = open_key

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(6)
        self._headers = []
        self._form = None
        if not self._refs:
            note = QLabel("No steps in this sequence yet - add one with + Add step.")
            note.setObjectName("formHelp")
            column.addWidget(note)
        for ref in self._refs:
            card = QFrame()
            card.setObjectName("stepCard")
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(6, 4, 6, 6)
            card_layout.setSpacing(4)
            is_open = open_key == _key(ref)
            header = QToolButton()
            header.setAutoRaise(True)
            header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            if is_open:
                header.setArrowType(Qt.ArrowType.DownArrow)
            else:
                header.setArrowType(Qt.ArrowType.RightArrow)
            header.setText(step_title(_step(self._model, ref)))
            header.clicked.connect(lambda _checked=False, r=ref: self._toggle(r))
            card_layout.addWidget(header)
            if ref.list_name == "teardown_steps":
                header.setToolTip("A teardown step: runs after the sequence, whatever happened.")
            if is_open:
                # Only the open card has a form: every form listens to the model.
                form = SchemaForm(self._model, fit_content=True)
                card_layout.addWidget(form)
                form.show_step(ref, self._sequence_index)
                form.set_issues(self._issues)
                self._form = form
            column.addWidget(card)
            self._headers.append((ref, header))
        column.addStretch()

        old = self.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.setWidget(content)
        self._paint_headers()

    def _toggle(self, ref: StepRef) -> None:
        if self._selected is not None and _key(self._selected) == _key(ref):
            self.step_chosen.emit(None)
        else:
            self.step_chosen.emit(ref)

    def _paint_headers(self) -> None:
        danger = get_palette(False).danger
        for ref, header in self._headers:
            if _has_problem(self._issues, ref):
                header.setStyleSheet(f"color: {danger}; font-weight: 600;")
            else:
                header.setStyleSheet("font-weight: 600;")


# -- Grid --------------------------------------------------------------------------------

_TYPE, _NAME, _DESCRIPTION, _DETAILS = range(4)


def detail_fields(steptype: str) -> list[str]:
    """The type's own required fields a one-line cell can carry (no inputs, template, ...)."""
    model = STEP_SCHEMAS.get(steptype)
    if model is None:
        return []
    names = []
    for name, info in model.model_fields.items():
        if name in ("steptype", "step_name", "description"):
            continue
        if not info.is_required():
            continue
        if field_kind(model, name, info) in (TEXT, VALUE):
            names.append(name)
    return names


def details_text(step: dict) -> str:
    """`wait_time: 2` / `module: x.py, method_name: f` - or a summary of what is not one line."""
    steptype = steptype_key(step.get("steptype"))
    names = detail_fields(steptype)
    if steptype == "indexed":
        template = step.get("template")
        template_type = ""
        if isinstance(template, dict):
            template_type = STEP_TYPE_NAMES.get(steptype_key(template.get("steptype")), "?")
        sets = step.get("parameter_sets")
        count = len(sets) if isinstance(sets, list) else 0
        return f"template {template_type}, {count} parameter sets"
    parts = []
    for name in names:
        parts.append(f"{name}: {value_text(step.get(name))}")
    return ", ".join(parts)


class GridView(QWidget):
    """One row per authored step of the sequence: type, name, description, its own fields."""

    step_chosen = Signal(object)

    def __init__(self, model: RecipeModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._refs: list[StepRef] = []
        self._sequence_index = 0
        self._selected: StepRef | None = None
        self._issues: list = []
        self._filling = False

        help_label = QLabel(
            "Double-click a cell to edit it. Details are written as YAML: "
            "wait_time: 2, module: my_tests.py"
        )
        help_label.setObjectName("formHelp")
        help_label.setWordWrap(True)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Type", "Name", "Description", "Details"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_DETAILS, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(_NAME, 140)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellClicked.connect(self._clicked)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(help_label)
        column.addWidget(self.table, 1)

    def show_step(self, ref: StepRef | None, sequence_index: int) -> None:
        self._selected = ref
        self._sequence_index = sequence_index
        self._select_row()

    def set_refs(self, refs: list[StepRef], sequence_index: int) -> None:
        self._refs = _sequence_refs(refs, sequence_index)
        self._sequence_index = sequence_index
        self._fill()

    def current_ref(self) -> StepRef | None:
        return self._selected

    def refresh(self) -> None:
        if self.table.state() == QAbstractItemView.State.EditingState:
            return
        self._fill()

    def set_issues(self, issues: list) -> None:
        self._issues = issues
        self._fill()

    def set_dark(self, _dark: bool) -> None:
        self._fill()

    def _fill(self) -> None:
        self._filling = True
        self.table.setRowCount(len(self._refs))
        danger = QColor(get_palette(False).danger)
        for row, ref in enumerate(self._refs):
            step = _step(self._model, ref)
            steptype = steptype_key(step.get("steptype"))
            type_item = QTableWidgetItem(STEP_TYPE_NAMES.get(steptype, str(step.get("steptype"))))
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if ref.list_name == "teardown_steps":
                type_item.setText(type_item.text() + " (teardown)")
            if _has_problem(self._issues, ref):
                type_item.setForeground(danger)
                type_item.setToolTip("This step has a problem - see PROBLEMS.")
            if steptype == "sequence":
                name_item = QTableWidgetItem(f"→ {step.get('sequence_name', '')}")
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            else:
                name_item = QTableWidgetItem(str(step.get("step_name") or ""))
            description_item = QTableWidgetItem(str(step.get("description") or ""))
            details_item = QTableWidgetItem(details_text(step))
            if steptype == "indexed" or not detail_fields(steptype):
                details_item.setFlags(details_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            for column, item in (
                (_TYPE, type_item),
                (_NAME, name_item),
                (_DESCRIPTION, description_item),
                (_DETAILS, details_item),
            ):
                current = self.table.item(row, column)
                if current is None or current.text() != item.text() or column == _TYPE:
                    self.table.setItem(row, column, item)
        self._filling = False
        self._select_row()

    def _select_row(self) -> None:
        self.table.blockSignals(True)
        self.table.clearSelection()
        if self._selected is not None:
            for row, ref in enumerate(self._refs):
                if _key(ref) == _key(self._selected):
                    self.table.selectRow(row)
        self.table.blockSignals(False)

    def _clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._refs):
            self.step_chosen.emit(self._refs[row])

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        row = item.row()
        if not 0 <= row < len(self._refs):
            return
        ref = self._refs[row]
        text = item.text().strip()
        if item.column() == _NAME:
            self._model.set_path(ref.document, ref.path("step_name"), text)
        elif item.column() == _DESCRIPTION:
            self._model.set_path(ref.document, ref.path("description"), text)
        elif item.column() == _DETAILS:
            self._write_details(ref, text)

    def _write_details(self, ref: StepRef, text: str) -> None:
        """`a: 1, b: x` read as one YAML mapping; each of the type's fields in it written."""
        try:
            values = yaml.safe_load("{" + text + "}")
        except yaml.YAMLError:
            self._fill()
            return
        if not isinstance(values, dict):
            self._fill()
            return
        step = _step(self._model, ref)
        allowed = detail_fields(steptype_key(step.get("steptype")))
        changes = [
            (name, value)
            for name, value in values.items()
            if name in allowed and plain(step.get(name)) != value
        ]
        if not changes:
            self._fill()
            return
        # One undo entry for the whole cell.
        self._model.undo_stack.beginMacro("Edit step details")
        for name, value in changes:
            self._model.set_path(ref.document, ref.path(name), value)
        self._model.undo_stack.endMacro()


# -- Outline -------------------------------------------------------------------------------

_HEADER_NODE = ("header",)


class OutlineView(QSplitter):
    """The whole recipe as a tree - header, sequences, steps, their inputs and outputs -
    over a form for what is selected in it."""

    step_chosen = Signal(object)
    sequence_chosen = Signal(int)

    def __init__(self, model: RecipeModel, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._model = model
        self._refs: list[StepRef] = []
        self._sequence_index = 0
        self._selected: StepRef | None = None
        self._shape: Any = None
        self._filling = False

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._clicked)
        self.form = SchemaForm(model)
        self.addWidget(self.tree)
        self.addWidget(self.form)
        self.setStretchFactor(0, 2)
        self.setStretchFactor(1, 3)
        self.setChildrenCollapsible(False)

    def show_step(self, ref: StepRef | None, sequence_index: int) -> None:
        self._selected = ref
        self._sequence_index = sequence_index
        if self.form.current_ref() != ref or ref is None:
            self.form.show_step(ref, sequence_index)
        self._select_item()

    def set_refs(self, refs: list[StepRef], sequence_index: int) -> None:
        self._refs = list(refs)
        self._sequence_index = sequence_index
        self._fill()

    def current_ref(self) -> StepRef | None:
        return self._selected

    def refresh(self) -> None:
        self.form.refresh()
        self._fill()

    def set_issues(self, issues: list) -> None:
        self.form.set_issues(issues)

    def set_dark(self, _dark: bool) -> None:
        return

    def _fill(self) -> None:
        sequences = self._model.sequences()
        shape = (
            tuple(_key(ref) for ref in self._refs),
            tuple(str(seq.get("sequence_name", "")) for seq in sequences),
            tuple(step_title(_step(self._model, ref)) for ref in self._refs),
            tuple(_entry_shape(_step(self._model, ref)) for ref in self._refs),
        )
        if shape == self._shape:
            return
        self._shape = shape
        expanded = self._expanded_paths()
        self._filling = True
        self.tree.clear()
        header = self._model.header() if not self._model.is_empty() else {}
        root = QTreeWidgetItem([f"Recipe: {header.get('name', '')}"])
        root.setData(0, Qt.ItemDataRole.UserRole, _HEADER_NODE)
        self.tree.addTopLevelItem(root)
        for index, sequence in enumerate(sequences):
            node = QTreeWidgetItem([f"Sequence: {sequence.get('sequence_name', '')}"])
            node.setData(0, Qt.ItemDataRole.UserRole, ("sequence", index))
            root.addChild(node)
            for ref in self._refs:
                if ref.sequence_index != index:
                    continue
                step = _step(self._model, ref)
                title = step_title(step)
                if ref.list_name == "teardown_steps":
                    title += "  (teardown)"
                step_node = QTreeWidgetItem([title])
                step_node.setData(0, Qt.ItemDataRole.UserRole, ("step", _key(ref)))
                node.addChild(step_node)
                for child_title in _entry_lines(step):
                    child = QTreeWidgetItem([child_title])
                    child.setData(0, Qt.ItemDataRole.UserRole, ("step", _key(ref)))
                    step_node.addChild(child)
        root.setExpanded(True)
        for index in range(root.childCount()):
            root.child(index).setExpanded(True)
        self._restore_expanded(expanded)
        self._filling = False
        self._select_item()

    def _expanded_paths(self) -> set[str]:
        paths = set()
        iterator = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while iterator:
            item = iterator.pop()
            if item.isExpanded():
                paths.add(_item_path(item))
            iterator.extend(item.child(i) for i in range(item.childCount()))
        return paths

    def _restore_expanded(self, paths: set[str]) -> None:
        iterator = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while iterator:
            item = iterator.pop()
            if _item_path(item) in paths:
                item.setExpanded(True)
            iterator.extend(item.child(i) for i in range(item.childCount()))

    def _select_item(self) -> None:
        wanted: Any = None
        if self._selected is not None:
            wanted = ("step", _key(self._selected))
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        iterator = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while iterator:
            item = iterator.pop(0)
            if wanted is not None and item.data(0, Qt.ItemDataRole.UserRole) == wanted:
                item.setSelected(True)
                self.tree.scrollToItem(item)
                break
            iterator.extend(item.child(i) for i in range(item.childCount()))
        self.tree.blockSignals(False)

    def _clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._filling:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data == _HEADER_NODE:
            self.step_chosen.emit(None)
            return
        if isinstance(data, tuple) and data and data[0] == "sequence":
            self.sequence_chosen.emit(int(data[1]))
            return
        if isinstance(data, tuple) and data and data[0] == "step":
            for ref in self._refs:
                if _key(ref) == data[1]:
                    self.step_chosen.emit(ref)
                    return


def _item_path(item: QTreeWidgetItem) -> str:
    parts = []
    while item is not None:
        parts.append(item.text(0))
        item = item.parent()
    return "/".join(reversed(parts))


def _entry_shape(step: dict) -> Any:
    return tuple(_entry_lines(step))


def _entry_lines(step: dict) -> list[str]:
    """A step's inputs, outputs, template and parameter sets, one tree line each."""
    lines: list[str] = []
    inputs = step.get("inputs")
    if isinstance(inputs, dict):
        for name, value in inputs.items():
            if isinstance(value, dict):
                lines.append(f"in  {name} ← global {value.get('global_name', '')}")
            else:
                lines.append(f"in  {name} = {value_text(value)}")
    outputs = step.get("outputs")
    if isinstance(outputs, dict):
        for name, value in outputs.items():
            if isinstance(value, dict):
                rest = {k: v for k, v in value.items() if k != "type"}
                detail = value_text(plain(rest)) if rest else ""
                lines.append(f"out {name}: {value.get('type', '?')} {detail}".rstrip())
            else:
                lines.append(f"out {name}: ?")
    template = step.get("template")
    if isinstance(template, dict):
        lines.append(f"template: {step_title(template)}")
    sets = step.get("parameter_sets")
    if isinstance(sets, list):
        lines.append(f"{len(sets)} parameter sets")
    return lines

