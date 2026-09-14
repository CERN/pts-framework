# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtCore import Qt, QRegularExpression, QTimer, Signal

import yaml

from pypts.helper_applications.recipe_creator.customGUIModules import ScintillaYamlEditor
from pypts.hmi.gui.palette import get_palette
from pypts.recipe.rules import INPUT_TYPES, OUTPUT_TYPES, STEP_TYPE_REQUIRED


# ── PaletteYamlHighlighter ────────────────────────────────────────────────────


class PaletteYamlHighlighter(QSyntaxHighlighter):
    """YAML syntax highlighter that reads colours from the palette (no hex literals)."""

    def __init__(self, document, dark: bool = False) -> None:
        super().__init__(document)
        self._rules: list[tuple] = []
        self._build_rules(dark)

    def set_dark(self, dark: bool) -> None:
        self._build_rules(dark)
        self.rehighlight()

    def _build_rules(self, dark: bool) -> None:
        p = get_palette(dark)
        self._rules = []

        def _rule(pattern: str, color: str, bold: bool = False, italic: bool = False) -> None:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            self._rules.append((QRegularExpression(pattern), fmt))

        _rule(r"^\s*[^:\n]+(?=:)", p.yaml_key, bold=True)
        _rule(r'(?<=:\s)["\'].*["\']', p.yaml_string)
        _rule(r"\b\d+(\.\d+)?\b", p.yaml_number)
        _rule(r"\b(true|false)\b", p.yaml_boolean)
        _rule(r"\b(null|Null|NULL|~)\b", p.yaml_null)
        _rule(r"#.*", p.yaml_comment, italic=True)

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ── YamlEditor ────────────────────────────────────────────────────────────────


class YamlEditor(ScintillaYamlEditor):
    """ScintillaYamlEditor extended with debounced commit signal and error gutter dots."""

    text_committed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self._error_lines: set[int] = set()

        # Detach the parent's plain YamlHighlighter and replace it with the
        # palette-aware version so only one highlighter is active on the document.
        self.highlighter.setDocument(None)
        self._highlighter = PaletteYamlHighlighter(self.document(), dark=False)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._on_debounce)

        self.textChanged.connect(self._on_text_changed)

    def set_dark(self, dark: bool) -> None:
        """Apply theme to both the gutter rendering and the syntax highlighter."""
        self.set_dark_mode(dark)
        self._highlighter.set_dark(dark)

    def set_content(self, text: str) -> None:
        """Set editor text without triggering the debounce/commit cycle."""
        self._debounce.stop()
        self._updating = True
        self.setPlainText(text)
        self._updating = False

    def set_error_lines(self, lines: set[int]) -> None:
        """Mark 1-based line numbers with a red dot in the gutter."""
        self._error_lines = lines
        self.line_number_area.update()

    def go_to_line(self, line_num: int) -> None:
        """Move cursor to 1-based line_num and ensure it is visible."""
        if line_num > 0:
            self.setCursorPosition(line_num - 1, 0)
            self.ensureLineVisible(line_num - 1)

    def _on_text_changed(self) -> None:
        if not self._updating:
            self._debounce.start()

    def _on_debounce(self) -> None:
        self.text_committed.emit(self.toPlainText())

    def line_number_area_width(self) -> int:
        """Return gutter width wide enough for digits plus a red-dot column."""
        return super().line_number_area_width() + 14

    def line_number_area_paint_event(self, event) -> None:  # noqa: ANN001
        """Paint line numbers and red error dots.

        Does NOT call super() — doing so would open a second QPainter on the
        same widget, which crashes Qt.  Line number drawing is reproduced here
        in full.
        """
        painter = QPainter(self.line_number_area)
        p = get_palette(self.dark_mode)
        painter.fillRect(event.rect(), QColor(p.panel_background))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        line_h = self.fontMetrics().height()
        dot_size = min(8, line_h - 2)
        num_width = self.line_number_area_width() - dot_size - 6

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_num = block_number + 1
                painter.setPen(QColor(p.text_muted))
                painter.drawText(
                    0,
                    top,
                    num_width,
                    line_h,
                    Qt.AlignmentFlag.AlignRight,
                    str(line_num),
                )
                if line_num in self._error_lines:
                    painter.setBrush(QColor(p.danger))
                    painter.setPen(Qt.PenStyle.NoPen)
                    x = self.line_number_area_width() - dot_size - 2
                    y = top + (line_h - dot_size) // 2
                    painter.drawEllipse(x, y, dot_size, dot_size)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1


# ── VerificationPanel ─────────────────────────────────────────────────────────


class VerificationPanel(QFrame):
    """Collapsible panel showing ValidationIssue list. Emits line_requested on double-click."""

    line_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._expanded = False
        self._issues: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # Summary row
        summary_row = QWidget()
        row_layout = QHBoxLayout(summary_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_label = QLabel("No recipe loaded")
        self._toggle_btn = QLabel("[▶]")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.mousePressEvent = lambda _: self._toggle()
        row_layout.addWidget(self._summary_label)
        row_layout.addStretch()
        row_layout.addWidget(self._toggle_btn)
        outer.addWidget(summary_row)

        # Issue list
        self._list = QListWidget()
        self._list.setFixedHeight(140)
        self._list.setVisible(False)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        outer.addWidget(self._list)

        # Hint label
        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        outer.addWidget(self._hint_label)
        self._list.currentItemChanged.connect(self._on_item_selected)

    def update_issues(self, issues: list) -> None:
        """Refresh the panel with a new list of ValidationIssue objects."""
        self._issues = issues
        self._list.clear()
        errors = [i for i in issues if i.is_error]
        warnings = [i for i in issues if i.is_warning]

        if not issues:
            self._summary_label.setText("\u2705 Recipe valid")
        else:
            parts = []
            if errors:
                parts.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}")
            if warnings:
                parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
            separator = " \u00b7 "
            self._summary_label.setText(f"\u274c {separator.join(parts)}")

        for issue in issues:
            line_info = f" (line {issue.line})" if issue.line else ""
            prefix = "\U0001f534" if issue.is_error else "\U0001f7e1"
            item = QListWidgetItem(f"{prefix} {issue.field}: {issue.message}{line_info}")
            item.setData(Qt.ItemDataRole.UserRole, issue)
            self._list.addItem(item)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._list.setVisible(self._expanded)
        self._hint_label.setVisible(self._expanded)
        self._toggle_btn.setText("[▼]" if self._expanded else "[▶]")

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue and issue.line:
            self.line_requested.emit(issue.line)

    def _on_item_selected(self, current: QListWidgetItem | None, _) -> None:
        if current:
            issue = current.data(Qt.ItemDataRole.UserRole)
            if issue:
                self._hint_label.setText(issue.hint)


# ── GlobalsEditorDialog ───────────────────────────────────────────────────────


class GlobalsEditorDialog(QDialog):
    """Modal dialog for editing the `globals` header dict."""

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Edit Globals")
        self.resize(420, 300)
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Name", "Initial value"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("- Remove")
        remove_btn.clicked.connect(self._remove_row)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate(model.header().get("globals") or {})

    def _populate(self, globals_dict: dict) -> None:
        self._table.setRowCount(0)
        for name, value in globals_dict.items():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(name)))
            self._table.setItem(row, 1, QTableWidgetItem(str(value) if value is not None else ""))

    def _add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(""))
        self._table.setItem(row, 1, QTableWidgetItem(""))

    def _remove_row(self) -> None:
        rows = sorted({item.row() for item in self._table.selectedItems()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)

    def _on_ok(self) -> None:
        result = {}
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 0)
            val_item = self._table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            value = val_item.text().strip() if val_item else ""
            if name:
                result[name] = value
        self._model.set_header_field("globals", result)
        self.accept()


# ── HeaderStrip ───────────────────────────────────────────────────────────────


class HeaderStrip(QFrame):
    """Collapsible strip showing recipe header fields and sequence selector."""

    sequence_changed = Signal(int)

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._expanded = True
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        # Collapse bar
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel("Recipe header")
        self._collapse_btn = QLabel("[▼]")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.mousePressEvent = lambda _: self._toggle()
        bar_layout.addWidget(self._title_label)
        bar_layout.addStretch()
        bar_layout.addWidget(self._collapse_btn)
        outer.addWidget(bar)

        # Form
        self._form_widget = QWidget()
        form = QFormLayout(self._form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self._name_edit = QLineEdit()
        self._version_edit = QLineEdit()
        self._desc_edit = QLineEdit()
        self._globals_btn = QPushButton("Edit globals…")
        self._globals_btn.clicked.connect(self._open_globals)
        self._metadata_edit = QLineEdit()

        form.addRow("Name *", self._name_edit)
        form.addRow("Version *", self._version_edit)
        form.addRow("Description", self._desc_edit)
        form.addRow("Globals", self._globals_btn)
        form.addRow("Report metadata", self._metadata_edit)

        # Sequence row
        seq_row = QWidget()
        seq_layout = QHBoxLayout(seq_row)
        seq_layout.setContentsMargins(0, 0, 0, 0)
        self._seq_combo = QComboBox()
        self._seq_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_seq_btn = QPushButton("+")
        add_seq_btn.setFixedWidth(28)
        add_seq_btn.clicked.connect(self._add_sequence)
        remove_seq_btn = QPushButton("−")
        remove_seq_btn.setFixedWidth(28)
        remove_seq_btn.clicked.connect(self._remove_sequence)
        seq_layout.addWidget(self._seq_combo)
        seq_layout.addWidget(add_seq_btn)
        seq_layout.addWidget(remove_seq_btn)
        form.addRow("Sequence", seq_row)

        outer.addWidget(self._form_widget)

        # Wire field changes to model
        self._name_edit.editingFinished.connect(
            lambda: model.set_header_field("name", self._name_edit.text())
        )
        self._version_edit.editingFinished.connect(
            lambda: model.set_header_field("version", self._version_edit.text())
        )
        self._desc_edit.editingFinished.connect(
            lambda: model.set_header_field("description", self._desc_edit.text())
        )
        self._metadata_edit.editingFinished.connect(
            lambda: model.set_header_field(
                "report_metadata",
                [s.strip() for s in self._metadata_edit.text().split(",") if s.strip()],
            )
        )
        self._seq_combo.currentIndexChanged.connect(self._on_seq_changed)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        h = self._model.header()
        self._title_label.setText(h.get("name") or "Recipe header")
        self._name_edit.blockSignals(True)
        self._version_edit.blockSignals(True)
        self._desc_edit.blockSignals(True)
        self._metadata_edit.blockSignals(True)
        self._seq_combo.blockSignals(True)

        self._name_edit.setText(str(h.get("name") or ""))
        self._version_edit.setText(str(h.get("version") or ""))
        self._desc_edit.setText(str(h.get("description") or ""))
        meta = h.get("report_metadata") or []
        self._metadata_edit.setText(", ".join(meta) if isinstance(meta, list) else str(meta))

        prev_idx = self._seq_combo.currentIndex()
        self._seq_combo.clear()
        for seq in self._model.sequences():
            self._seq_combo.addItem(seq.get("sequence_name", ""))
        if prev_idx >= 0 and prev_idx < self._seq_combo.count():
            self._seq_combo.setCurrentIndex(prev_idx)

        self._name_edit.blockSignals(False)
        self._version_edit.blockSignals(False)
        self._desc_edit.blockSignals(False)
        self._metadata_edit.blockSignals(False)
        self._seq_combo.blockSignals(False)

    def current_seq_idx(self) -> int:
        return max(0, self._seq_combo.currentIndex())

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._form_widget.setVisible(self._expanded)
        self._collapse_btn.setText("[▼]" if self._expanded else "[▶]")

    def _open_globals(self) -> None:
        dlg = GlobalsEditorDialog(self._model, self)
        dlg.exec()

    def _on_seq_changed(self, idx: int) -> None:
        self.sequence_changed.emit(idx)

    def _add_sequence(self) -> None:
        name, ok = QInputDialog.getText(self, "Add sequence", "Sequence name:")
        if ok and name.strip():
            self._model.add_sequence(name.strip())

    def _remove_sequence(self) -> None:
        idx = self._seq_combo.currentIndex()
        if idx >= 0:
            self._model.remove_sequence(idx)


# ── MappingRowsWidget ─────────────────────────────────────────────────────────


class MappingRowsWidget(QWidget):
    """Editable rows for a step's `inputs` or `outputs` dict."""

    def __init__(self, model, seq_idx: int, step_idx: int, mapping_key: str, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._key = mapping_key  # "inputs" or "outputs"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._rows_widget = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addWidget(self._rows_widget)

        add_btn = QPushButton(f"+ Add {mapping_key[:-1]}")  # "Add input" / "Add output"
        add_btn.clicked.connect(self._add_row)
        outer.addWidget(add_btn)
        outer.addStretch()

        self.rebuild()

    def rebuild(self) -> None:
        # Clear rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        steps = self._model.steps(self._seq_idx)
        if self._step_idx >= len(steps):
            return
        step = steps[self._step_idx]
        mapping = step.get(self._key) or {}
        for name, spec in mapping.items():
            self._rows_layout.addWidget(self._build_row(name, spec))

    def _build_row(self, name: str, spec) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        name_edit = QLineEdit(name)
        name_edit.setFixedWidth(110)
        rl.addWidget(name_edit)

        if self._key == "inputs":
            types = ["literal"] + list(INPUT_TYPES.keys())
        else:
            types = list(OUTPUT_TYPES.keys())

        type_combo = QComboBox()
        type_combo.addItems(types)
        if isinstance(spec, dict):
            current_type = spec.get("type", types[0])
        else:
            current_type = "literal"
        if current_type in types:
            type_combo.setCurrentText(current_type)
        type_combo.setFixedWidth(90)
        rl.addWidget(type_combo)

        # Value widget placeholder — replaced when type changes
        value_holder = QWidget()
        value_holder_layout = QHBoxLayout(value_holder)
        value_holder_layout.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(value_holder)

        def refresh_value(t: str) -> None:
            while value_holder_layout.count():
                item = value_holder_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._add_value_widgets(value_holder_layout, t, spec)

        type_combo.currentTextChanged.connect(refresh_value)
        refresh_value(current_type)

        remove_btn = QPushButton("\u2715")
        remove_btn.setFixedWidth(28)
        remove_btn.clicked.connect(lambda: self._remove_row(name))
        rl.addWidget(remove_btn)

        return row

    def _add_value_widgets(self, layout, type_name: str, spec) -> None:
        if type_name == "literal":
            val = spec if not isinstance(spec, dict) else spec.get("value", "")
            edit = QLineEdit(str(val) if val is not None else "")
            layout.addWidget(edit)
        elif type_name == "global":
            val = spec.get("global_name", "") if isinstance(spec, dict) else ""
            edit = QLineEdit(str(val))
            edit.setPlaceholderText("global_name")
            layout.addWidget(edit)
        elif type_name == "equals":
            val = spec.get("value", "") if isinstance(spec, dict) else ""
            edit = QLineEdit(str(val))
            edit.setPlaceholderText("value")
            layout.addWidget(edit)
        elif type_name == "range":
            mn = spec.get("min", "") if isinstance(spec, dict) else ""
            mx = spec.get("max", "") if isinstance(spec, dict) else ""
            min_edit = QLineEdit(str(mn))
            min_edit.setPlaceholderText("min")
            max_edit = QLineEdit(str(mx))
            max_edit.setPlaceholderText("max")
            layout.addWidget(min_edit)
            layout.addWidget(QLabel("\u2026"))
            layout.addWidget(max_edit)
        # passfail / pass: no extra fields

    def _add_row(self) -> None:
        step = self._model.steps(self._seq_idx)[self._step_idx]
        mapping = dict(step.get(self._key) or {})
        new_name = f"new_{self._key[:-1]}_{len(mapping) + 1}"
        if self._key == "inputs":
            mapping[new_name] = ""
        else:
            mapping[new_name] = {"type": "pass"}
        self._model.set_step_field(self._seq_idx, self._step_idx, self._key, mapping)

    def _remove_row(self, name: str) -> None:
        step = self._model.steps(self._seq_idx)[self._step_idx]
        mapping = dict(step.get(self._key) or {})
        mapping.pop(name, None)
        self._model.set_step_field(self._seq_idx, self._step_idx, self._key, mapping)


# ── MappingYamlWidget ─────────────────────────────────────────────────────────


class MappingYamlWidget(QWidget):
    """Small YAML editor for a step's `inputs` or `outputs` block."""

    def __init__(
        self,
        model,
        seq_idx: int,
        step_idx: int,
        mapping_key: str,
        dark: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._key = mapping_key
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._editor = QTextEdit()
        self._editor.setFixedHeight(130)
        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(font)
        layout.addWidget(self._editor)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        p = get_palette(dark)
        self._error_label.setStyleSheet(f"color: {p.danger};")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        self._highlighter = PaletteYamlHighlighter(self._editor.document(), dark)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._on_debounce)
        self._editor.textChanged.connect(lambda: self._debounce.start())

        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._highlighter.set_dark(dark)
        p = get_palette(dark)
        self._error_label.setStyleSheet(f"color: {p.danger};")

    def rebuild(self) -> None:
        steps = self._model.steps(self._seq_idx)
        if self._step_idx >= len(steps):
            return
        step = steps[self._step_idx]
        mapping = step.get(self._key)
        text = yaml.dump(mapping, default_flow_style=False) if mapping else ""
        self._updating = True
        self._editor.setPlainText(text.rstrip())
        self._debounce.stop()
        self._updating = False

    def _on_debounce(self) -> None:
        if self._updating:
            return
        text = self._editor.toPlainText().strip()
        if not text:
            self._model.set_step_field(self._seq_idx, self._step_idx, self._key, {})
            self._error_label.setVisible(False)
            return
        try:
            parsed = yaml.safe_load(text)
            if not isinstance(parsed, dict):
                raise ValueError("Expected a YAML mapping")
            self._model.set_step_field(self._seq_idx, self._step_idx, self._key, parsed)
            self._error_label.setVisible(False)
        except Exception as exc:
            self._error_label.setText(str(exc))
            self._error_label.setVisible(True)


# ── StepFormWidget ────────────────────────────────────────────────────────────


class StepFormWidget(QWidget):
    """Form for editing all fields of a single step."""

    def __init__(
        self,
        model,
        seq_idx: int,
        step_idx: int,
        dark: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._dark = dark

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)

        # Step type label
        self._type_label = QLabel()
        outer.addWidget(self._type_label)

        # Common fields
        common_group = QGroupBox("Common")
        common_form = QFormLayout(common_group)
        self._name_edit = QLineEdit()
        self._desc_edit = QLineEdit()
        self._skip_check = QCheckBox()
        self._coe_check = QCheckBox()
        common_form.addRow("Name", self._name_edit)
        common_form.addRow("Description", self._desc_edit)
        common_form.addRow("Skip", self._skip_check)
        common_form.addRow("Continue on error", self._coe_check)
        outer.addWidget(common_group)

        self._name_edit.editingFinished.connect(
            lambda: model.set_step_field(seq_idx, step_idx, "step_name", self._name_edit.text())
        )
        self._desc_edit.editingFinished.connect(
            lambda: model.set_step_field(seq_idx, step_idx, "description", self._desc_edit.text())
        )
        self._skip_check.toggled.connect(
            lambda v: model.set_step_field(seq_idx, step_idx, "skip", v)
        )
        self._coe_check.toggled.connect(
            lambda v: model.set_step_field(seq_idx, step_idx, "continue_on_error", v)
        )

        # Type-specific fields area
        self._specific_widget = QWidget()
        self._specific_layout = QFormLayout(self._specific_widget)
        self._specific_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._specific_widget)

        # Inputs section
        inputs_group = QGroupBox("Inputs")
        inputs_vlayout = QVBoxLayout(inputs_group)
        self._inputs_stack = QStackedWidget()
        self._inputs_rows = MappingRowsWidget(model, seq_idx, step_idx, "inputs")
        self._inputs_yaml = MappingYamlWidget(model, seq_idx, step_idx, "inputs", dark)
        self._inputs_stack.addWidget(self._inputs_rows)
        self._inputs_stack.addWidget(self._inputs_yaml)
        toggle_inputs = QPushButton("Rows | YAML")
        toggle_inputs.setCheckable(False)
        toggle_inputs.clicked.connect(
            lambda: self._inputs_stack.setCurrentIndex(1 - self._inputs_stack.currentIndex())
        )
        inputs_vlayout.addWidget(toggle_inputs)
        inputs_vlayout.addWidget(self._inputs_stack)
        outer.addWidget(inputs_group)

        # Outputs section
        outputs_group = QGroupBox("Outputs")
        outputs_vlayout = QVBoxLayout(outputs_group)
        self._outputs_stack = QStackedWidget()
        self._outputs_rows = MappingRowsWidget(model, seq_idx, step_idx, "outputs")
        self._outputs_yaml = MappingYamlWidget(model, seq_idx, step_idx, "outputs", dark)
        self._outputs_stack.addWidget(self._outputs_rows)
        self._outputs_stack.addWidget(self._outputs_yaml)
        toggle_outputs = QPushButton("Rows | YAML")
        toggle_outputs.setCheckable(False)
        toggle_outputs.clicked.connect(
            lambda: self._outputs_stack.setCurrentIndex(1 - self._outputs_stack.currentIndex())
        )
        outputs_vlayout.addWidget(toggle_outputs)
        outputs_vlayout.addWidget(self._outputs_stack)
        outer.addWidget(outputs_group)

        outer.addStretch()
        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._inputs_yaml.set_dark(dark)
        self._outputs_yaml.set_dark(dark)

    def rebuild(self) -> None:
        steps = self._model.steps(self._seq_idx)
        if self._step_idx >= len(steps):
            return
        step = steps[self._step_idx]

        _em = "\u2014"
        self._type_label.setText(f"Type: {step.get('steptype', _em)}")

        for widget in [self._name_edit, self._desc_edit, self._skip_check, self._coe_check]:
            widget.blockSignals(True)
        self._name_edit.setText(str(step.get("step_name") or ""))
        self._desc_edit.setText(str(step.get("description") or ""))
        self._skip_check.setChecked(bool(step.get("skip", False)))
        self._coe_check.setChecked(bool(step.get("continue_on_error", True)))
        for widget in [self._name_edit, self._desc_edit, self._skip_check, self._coe_check]:
            widget.blockSignals(False)

        # Rebuild type-specific fields
        while self._specific_layout.rowCount():
            self._specific_layout.removeRow(0)
        steptype = step.get("steptype", "")
        for field in STEP_TYPE_REQUIRED.get(steptype, ()):
            if field in ("inputs", "outputs"):
                continue
            if field == "wait_time":
                spin = QDoubleSpinBox()
                spin.setRange(0, 99999)
                spin.setValue(float(step.get(field) or 0))
                spin.valueChanged.connect(
                    lambda v, f=field: self._model.set_step_field(
                        self._seq_idx, self._step_idx, f, v
                    )
                )
                self._specific_layout.addRow(field, spin)
            else:
                edit = QLineEdit(str(step.get(field) or ""))
                edit.editingFinished.connect(
                    lambda f=field, e=edit: self._model.set_step_field(
                        self._seq_idx, self._step_idx, f, e.text()
                    )
                )
                self._specific_layout.addRow(field, edit)

        self._inputs_rows.rebuild()
        self._outputs_rows.rebuild()
        self._inputs_yaml.rebuild()
        self._outputs_yaml.rebuild()


# ── ListStepView ──────────────────────────────────────────────────────────────


class ListStepView(QSplitter):
    """Vertical splitter: step list on top, StepFormWidget below."""

    step_selected = Signal(int, int)

    def __init__(self, model, parent=None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._model = model
        self._seq_idx = 0
        self._dark = False
        self._form: StepFormWidget | None = None

        # Top: list
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.currentRowChanged.connect(self._on_row_changed)
        top_layout.addWidget(self._list)
        self.addWidget(top)

        # Bottom: form placeholder
        self._form_container = QScrollArea()
        self._form_container.setWidgetResizable(True)
        self.addWidget(self._form_container)

        model.changed.connect(self.rebuild)
        self.rebuild()
        self._list.model().rowsMoved.connect(self._on_rows_moved)

    def set_seq_idx(self, idx: int) -> None:
        self._seq_idx = idx
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        if self._form:
            self._form.set_dark(dark)

    def rebuild(self) -> None:
        self._list.blockSignals(True)
        prev = self._list.currentRow()
        self._list.clear()
        for step in self._model.steps(self._seq_idx):
            steptype = step.get("steptype", "?")
            name = step.get("step_name", "")
            skip = " [skip]" if step.get("skip") else ""
            self._list.addItem(f"[{steptype}] {name}{skip}")
        self._list.blockSignals(False)
        if prev >= 0 and prev < self._list.count():
            self._list.setCurrentRow(prev)
        self._show_form(self._list.currentRow())

    def _on_row_changed(self, row: int) -> None:
        self._show_form(row)
        if row >= 0:
            self.step_selected.emit(self._seq_idx, row)

    def _on_rows_moved(self, _parent, src, _srcEnd, _dst, dst) -> None:
        to = dst if dst > src else dst
        self._model.move_step(self._seq_idx, src, to)

    def _show_form(self, row: int) -> None:
        if row < 0 or row >= len(self._model.steps(self._seq_idx)):
            self._form_container.setWidget(QWidget())
            self._form = None
            return
        self._form = StepFormWidget(self._model, self._seq_idx, row, self._dark)
        self._form_container.setWidget(self._form)


# ── CardStepView ──────────────────────────────────────────────────────────────


class CardStepView(QScrollArea):
    """Accordion of StepCard widgets, one card per step."""

    step_selected = Signal(int, int)

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._seq_idx = 0
        self._dark = False
        self._expanded_idx: int = -1

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        self.setWidget(self._content)
        self.setWidgetResizable(True)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_seq_idx(self, idx: int) -> None:
        self._seq_idx = idx
        self._expanded_idx = -1
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.rebuild()

    def rebuild(self) -> None:
        # Remove all except the trailing stretch
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, step in enumerate(self._model.steps(self._seq_idx)):
            card = self._make_card(idx, step)
            self._layout.insertWidget(idx, card)

    def _make_card(self, step_idx: int, step: dict) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(2)

        # Header row
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        steptype = step.get("steptype", "?")
        name = step.get("step_name", "")
        title = QLabel(f"[{steptype}] {name}")
        expand_btn = QPushButton("▼" if step_idx == self._expanded_idx else "▶")
        expand_btn.setFixedWidth(28)
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(expand_btn)
        card_layout.addWidget(header)

        # Body (form)
        form = StepFormWidget(self._model, self._seq_idx, step_idx, self._dark)
        form.setVisible(step_idx == self._expanded_idx)
        card_layout.addWidget(form)

        def toggle():  # noqa: ANN202
            if self._expanded_idx == step_idx:
                self._expanded_idx = -1
            else:
                self._expanded_idx = step_idx
            self.rebuild()
            self.step_selected.emit(self._seq_idx, step_idx)

        expand_btn.clicked.connect(toggle)
        title.mousePressEvent = lambda _: toggle()
        return card


# ── PanelsStepView ────────────────────────────────────────────────────────────


class PanelsStepView(QSplitter):
    """Horizontal splitter: slim type+name list on left, StepFormWidget on right."""

    step_selected = Signal(int, int)

    def __init__(self, model, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._model = model
        self._seq_idx = 0
        self._dark = False
        self._form: StepFormWidget | None = None

        # Left: slim list
        self._list = QListWidget()
        self._list.setFixedWidth(180)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self.addWidget(self._list)

        # Right: form in scroll area
        self._form_container = QScrollArea()
        self._form_container.setWidgetResizable(True)
        self.addWidget(self._form_container)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_seq_idx(self, idx: int) -> None:
        self._seq_idx = idx
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        if self._form:
            self._form.set_dark(dark)

    def rebuild(self) -> None:
        self._list.blockSignals(True)
        prev = self._list.currentRow()
        self._list.clear()
        for step in self._model.steps(self._seq_idx):
            steptype = step.get("steptype", "?")
            name = step.get("step_name", "")
            self._list.addItem(f"[{steptype}]\n{name}")
        self._list.blockSignals(False)
        if prev >= 0 and prev < self._list.count():
            self._list.setCurrentRow(prev)
        self._show_form(self._list.currentRow())

    def _on_row_changed(self, row: int) -> None:
        self._show_form(row)
        if row >= 0:
            self.step_selected.emit(self._seq_idx, row)

    def _show_form(self, row: int) -> None:
        if row < 0 or row >= len(self._model.steps(self._seq_idx)):
            self._form_container.setWidget(QWidget())
            self._form = None
            return
        self._form = StepFormWidget(self._model, self._seq_idx, row, self._dark)
        self._form_container.setWidget(self._form)
