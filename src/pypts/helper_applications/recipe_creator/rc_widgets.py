# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
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

from pypts.helper_applications.recipe_creator.customGUIModules import ScintillaYamlEditor
from pypts.hmi.gui.palette import get_palette


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
