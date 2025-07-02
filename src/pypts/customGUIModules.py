import sys
import io
from PySide6.QtWidgets import (
    QApplication,
    QPlainTextEdit,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QTextEdit,
    QLabel,
    QWidgetAction,
    QFileDialog,
    QToolBar,
    QStyle,
    QSizePolicy,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QTextFormat,
    QFont,
    QTextCharFormat,
    QTextCursor,
    QPixmap,
    QPainter,
)
from PySide6.QtCore import QSize, Qt, QRect, QMargins, QEvent
from PyQt6.Qsci import QsciScintilla, QsciLexerYAML
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from datetime import datetime
import webbrowser
from pypts.styles import *
from pypts.verify_recipe import *

from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtGui import QKeySequence, QUndoStack, QUndoCommand, QShortcut

class YamlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []

        # Key: "key:"
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#d17b49"))  # orange-brown
        key_format.setFontWeight(QFont.Weight.Bold)
        self.highlighting_rules.append((QRegularExpression(r"^\s*[^:\n]+(?=:)"), key_format))

        # String: "value" or 'value'
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#6abf69"))  # green
        self.highlighting_rules.append((QRegularExpression(r'(?<=:\s)["\'].*["\']'), string_format))

        # Number
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#6897bb"))  # blue
        self.highlighting_rules.append((QRegularExpression(r'\b\d+(\.\d+)?\b'), number_format))

        # Boolean
        bool_format = QTextCharFormat()
        bool_format.setForeground(QColor("#ff7c9c"))  # pink
        bool_pattern = QRegularExpression(r'\b(true|false)\b')
        self.highlighting_rules.append((bool_pattern, bool_format))

        # Null values
        null_format = QTextCharFormat()
        null_format.setForeground(QColor("#b0b0b0"))  # gray
        self.highlighting_rules.append((QRegularExpression(r'\b(null|Null|NULL|~)\b'), null_format))

        # Comment
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#888888"))  # gray
        comment_format.setFontItalic(True)
        self.highlighting_rules.append((QRegularExpression(r'#.*'), comment_format))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                match = it.next()
                start = match.capturedStart()
                length = match.capturedLength()
                self.setFormat(start, length, fmt)

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.codeEditor = editor

    def sizeHint(self):
        return QSize(self.codeEditor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.codeEditor.line_number_area_paint_event(event)

class ScintillaYamlEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont("Courier New", 10)
        self.setFont(font)
        self.highlighter = YamlHighlighter(self.document())

        self.highlight_current_line = True
        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.update_current_line_highlight)

        self.update_line_number_area_width(0)

    def line_number_area_width(self):
        digits = len(str(self.blockCount()))
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#f0f0f0"))

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(blockNumber + 1)
                painter.setPen(Qt.GlobalColor.darkGray)
                painter.drawText(0, top, self.line_number_area.width() - 5, self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, number)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            blockNumber += 1

    def update_current_line_highlight(self):
        extraSelections = []

        if self.highlight_current_line:
            selection = QTextEdit.ExtraSelection()
            lineColor = QColor("#e6f7ff")
            selection.format.setBackground(lineColor)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)

        self.setExtraSelections(extraSelections)

    def setText(self, text):
        # Compatibility method for QsciScintilla
        self.setPlainText(text)

    def SendScintilla(self, *args):
        # Stub for QsciScintilla compatibility
        pass

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        pos = event.position().toPoint()  # Convert QPointF to QPoint (integer)
        cursor = self.cursorForPosition(pos)

        line = cursor.blockNumber()
        column = cursor.positionInBlock()

    def positionFromLineIndex(self, line_num, index):
        # Use QTextDocument to navigate to block (line)
        block = self.document().findBlockByNumber(line_num)
        if block.isValid():
            return block.position() + index
        return 0

    def line_text(self, line_num):
        # Return text of a specific line
        lines = self.toPlainText().split('\n')
        if 0 <= line_num < len(lines):
            return lines[line_num]
        return ""

    def setCursorPosition(self, line_num, col):
        # Set cursor to specific line and column
        lines = self.toPlainText().split('\n')
        if line_num < len(lines):
            pos = sum(len(line) + 1 for line in lines[:line_num]) + col
            cursor = self.textCursor()
            cursor.setPosition(pos)
            self.setTextCursor(cursor)

    def ensureLineVisible(self, line_num):
        # Make sure line is visible (stub implementation)
        pass

class WatermarkWidget(QWidget):
    """Widget showing a watermark image in the center."""
    def __init__(self, image_path: str):
        super().__init__()
        self.image_path = image_path
        self.pixmap = QPixmap(image_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(0.2)
        x = (self.width() - self.pixmap.width()) // 2
        y = (self.height() - self.pixmap.height()) // 2
        painter.drawPixmap(x, y, self.pixmap)

class HashableTreeItem:
    def __init__(self, item):
        self.item = item

    def __hash__(self):
        return id(self.item)

    def __eq__(self, other):
        return isinstance(other, HashableTreeItem) and self.item is other.item

