import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtGui import QFont, QColor
# Note: QScintilla for PySide6 requires mixed imports as there's no direct PySide6.QtScintilla
from PyQt5.Qsci import QsciScintilla, QsciLexerYAML

class ScintillaYamlEditor(QsciScintilla):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Basic editor setup
        self.setUtf8(True)
        self.setMarginsFont(QFont("Courier", 10))
        self.setMarginWidth(0, "0000")  # Line number margin
        self.setMarginLineNumbers(0, True)

        # Highlight the current line
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#e6f7ff"))

        # Font and syntax highlighting
        font = QFont("Courier", 10)
        self.setFont(font)
        self.setMarginsFont(font)

        lexer = QsciLexerYAML()
        lexer.setFont(font)
        self.setLexer(lexer)

        # Load example YAML
        sample_yaml = """\
recipe_name: Sample Recipe
recipe_version: 1.0
sequences:
  - name: Start
    steps:
      - action: PowerOn
        timeout: 5
  - name: Stop
    steps:
      - action: PowerOff
        timeout: 3
"""
        self.setText(sample_yaml)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YAML Editor with QScintilla")
        self.setGeometry(100, 100, 800, 600)

        editor = ScintillaYamlEditor(self)

        layout = QVBoxLayout()
        layout.addWidget(editor)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
