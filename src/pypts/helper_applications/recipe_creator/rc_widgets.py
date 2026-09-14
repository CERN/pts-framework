# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
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
        self._updating = True
        self.setPlainText(text)
        self._updating = False

    def set_error_lines(self, lines: set[int]) -> None:
        """Mark 1-based line numbers with a red dot in the gutter."""
        self._error_lines = lines
        self.line_number_area.update()

    def go_to_line(self, line_num: int) -> None:
        """Move cursor to 1-based line_num and ensure it is visible."""
        if line_num and line_num > 0:
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
