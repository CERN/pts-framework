# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QTextEdit,
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QDialog,
    QLineEdit,
    QFormLayout,
    QDialogButtonBox,
    QSpinBox
)
from PySide6.QtGui import (
    QTextFormat,
    QPixmap,
    QPainter,
)
from PySide6.QtCore import QSize, QRect
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import Qt, QRegularExpression
from pypts.YamVIEW.styles import *
import sys
import yaml


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
        self.dark_mode = False
        font = QFont("Courier New", 10)
        self.setFont(font)
        self.highlighter = YamlHighlighter(self.document())

        self.highlight_current_line = True
        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.update_current_line_highlight)

        self.update_line_number_area_width(0)

        self.setUndoRedoEnabled(True)


    def set_dark_mode(self, enabled: bool):
        self.dark_mode = enabled
        self.line_number_area.update()
        self.update_current_line_highlight()

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
        background_color = QColor("#2b2b2b") if self.dark_mode else QColor("#f0f0f0")
        painter.fillRect(event.rect(), background_color)

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
            lineColor = QColor("#000000") if self.dark_mode else QColor("#e6f7ff")
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

class RecipeCreatorDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("New Recipe Creator")
        self.layout = QVBoxLayout(self)

        self.form_layout = QFormLayout()

        self.name_field = QLineEdit("Black Forest Cake Testing")
        self.description_field = QLineEdit("Preparing the cake and checking the flavours")
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
                'step_name': f'Step {i + 1}',
                'description': f'Step {i + 1} description',
                'skip': 'False',
                'input_mapping': {
                    'message': {'type': 'direct', 'value': 'Tell the cook what to do'},
                    'options': {'type': 'direct', 'value': [{'yes': ''}, {'no': ''}]}
                },
                'output_mapping': {
                    'output': {'type': 'equals', 'value': 'yes'}
                }
            }
            sequence['steps'].append(step)

        # SPDX header string
        spdx_header = (
            "# SPDX-FileCopyrightText: 2025 CERN <home.cern>\n"
            "#\n"
            "# SPDX-License-Identifier: LGPL-2.1-or-later\n"
        )

        # Generate YAML
        yaml_body = yaml.dump_all([header, sequence], sort_keys=False)

        # Combine SPDX header and YAML body
        yaml_string = spdx_header + yaml_body
        return yaml_string

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = RecipeCreatorApp()
    window.resize(300, 150)
    window.show()
    sys.exit(app.exec())
