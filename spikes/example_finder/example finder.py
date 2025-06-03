# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
import os
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QWidget, QLabel, QLineEdit, QListWidget, QListWidgetItem, QFileDialog, QPlainTextEdit
)
from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PyQt5.QtCore import Qt, QRegExp

class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Simple syntax highlighter for Python code."""
    def __init__(self, document):
        super().__init__(document)
        
        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("blue"))
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "def", "class", "if", "else", "elif", "import", "from", "return", "for", "while", 
            "try", "except", "finally", "with", "as", "pass", "break", "continue", "in", "not", 
            "and", "or", "is", "lambda", "yield", "assert", "del", "global", "nonlocal", "raise"
        ]
        self.highlighting_rules = [(QRegExp(f"\\b{word}\\b"), keyword_format) for word in keywords]
        
        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("darkRed"))
        self.highlighting_rules.append((QRegExp("\".*\"|'.*'"), string_format))
        
        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("green"))
        self.highlighting_rules.append((QRegExp("#[^\n]*"), comment_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

class ExampleFinderApp(QMainWindow):
    def __init__(self):
        super().__init__()

        # Set window title and dimensions
        self.setWindowTitle("Example Finder")
        self.setGeometry(100, 100, 800, 600)

        # Directory where Python files are located
        self.directory = None

        # Main layout widget
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        
        # Overall layout
        main_layout = QHBoxLayout(self.main_widget)
        
        # Left side: search and keyword list
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout)

        # Search bar for keywords
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search keywords...")
        left_layout.addWidget(self.search_bar)

        # Keyword list (replace with real keyword list)
        self.keyword_list = QListWidget()
        self.keywords = []  # Dynamic keywords from files
        left_layout.addWidget(self.keyword_list)

        # Middle layout: Example files matching keyword
        mid_layout = QVBoxLayout()
        main_layout.addLayout(mid_layout)

        # Example list
        self.example_list = QListWidget()
        self.example_list.itemClicked.connect(self.update_description)  # Update description when clicked
        self.example_list.itemDoubleClicked.connect(self.open_file_in_editor)  # Double-click to open file
        mid_layout.addWidget(self.example_list)

        # Right layout: Description and info
        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout)

        # Description display
        self.description_box = QTextEdit()
        self.description_box.setReadOnly(True)
        self.description_box.setText("Description:\n\nSelect a keyword to view matching example files.")
        right_layout.addWidget(self.description_box)

        # Python code preview box
        self.preview_box = QPlainTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setPlaceholderText("Python file preview will appear here.")
        right_layout.addWidget(self.preview_box)
        
        # Initialize syntax highlighter for preview box
        self.highlighter = PythonSyntaxHighlighter(self.preview_box.document())

        # Bottom layout for buttons
        bottom_layout = QHBoxLayout()
        right_layout.addLayout(bottom_layout)

        # Buttons
        self.help_button = QPushButton("Help")
        self.load_directory_button = QPushButton("Load Directory")
        self.close_button = QPushButton("Close")
        
        bottom_layout.addWidget(self.help_button)
        bottom_layout.addWidget(self.load_directory_button)
        bottom_layout.addWidget(self.close_button)

        # Set up button actions
        self.close_button.clicked.connect(self.close)
        self.load_directory_button.clicked.connect(self.load_directory)

        # Keyword click action
        self.keyword_list.itemClicked.connect(self.keyword_clicked)

        # Search bar action to filter keywords
        self.search_bar.textChanged.connect(self.filter_keywords)

    def update_keyword_list(self, keywords):
        """Updates the keyword list displayed in the GUI."""
        self.keyword_list.clear()  # Clear the current list
        for keyword in keywords:
            self.keyword_list.addItem(QListWidgetItem(keyword))

    def keyword_clicked(self, item):
        """Triggered when a keyword is clicked, searches files for the keyword."""
        selected_keyword = item.text()
        matching_files = self.search_files_by_keyword(selected_keyword)
        self.update_example_list(matching_files)

    def search_files_by_keyword(self, keyword):
        matching_files = []
        if self.directory:
            for filename in os.listdir(self.directory):
                if filename.endswith(".py"):
                    filepath = os.path.join(self.directory, filename)
                    with open(filepath, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                        for line in lines:
                            if line.startswith("# Keywords:"):
                                keywords_in_line = line.replace("# Keywords:", "").strip().split(',')
                                keywords_in_line = [k.strip().lower() for k in keywords_in_line]
                                if keyword.lower() in keywords_in_line:
                                    matching_files.append(filename)
                                    break
        return matching_files

    def update_example_list(self, example_list):
        """Updates the example list displayed in the GUI."""
        self.example_list.clear()  # Clear the current list
        for example in example_list:
            self.example_list.addItem(QListWidgetItem(example))

    def filter_keywords(self):
        """Filters the keyword list based on search input."""
        search_term = self.search_bar.text().lower()
        if search_term:
            filtered_keywords = [keyword for keyword in self.keywords if search_term in keyword.lower()]
        else:
            filtered_keywords = self.keywords
        self.update_keyword_list(filtered_keywords)

    def load_directory(self):
        """Loads the directory containing Python files."""
        self.directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if self.directory:
            self.keywords = self.extract_keywords_from_files()
            self.update_keyword_list(self.keywords)

    def extract_keywords_from_files(self):
        keywords_set = set()
        if self.directory:
            for filename in os.listdir(self.directory):
                if filename.endswith(".py"):
                    filepath = os.path.join(self.directory, filename)
                    with open(filepath, 'r', encoding='utf-8') as file:
                        lines = file.readlines()
                        for line in lines:
                            if line.startswith("# Keywords:"):
                                keywords_in_line = line.replace("# Keywords:", "").strip().split(',')
                                keywords_in_line = [k.strip() for k in keywords_in_line]
                                keywords_set.update(keywords_in_line)
        return sorted(keywords_set)

    def get_description_from_file(self, filepath):
        description_lines = []
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                for line in lines:
                    if line.startswith("# Description:"):
                        description_lines.append(line.replace("# Description:", "").strip())
        return "\n".join(description_lines)

    def update_description(self, item):
        filename = item.text()
        if self.directory:
            filepath = os.path.join(self.directory, filename)
            if os.path.exists(filepath):
                description = self.get_description_from_file(filepath)
                self.description_box.setText(f"Description:\n\n{description}" if description else "No description available.")
                
                # Load preview of file content
                self.load_file_preview(filepath)
            else:
                self.description_box.setText("File not found.")

    def load_file_preview(self, filepath):
        """Loads the content of the file into the preview box, excluding description, keywords lines, and leading blank lines."""
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                # Exclude lines that start with "# Description:" or "# Keywords:"
                filtered_lines = [
                    line for line in lines if not line.startswith("# Description:") and not line.startswith("# Keywords:")
                ]
                # Remove leading blank lines
                content_without_leading_blanks = "\n".join(line for line in filtered_lines).lstrip("\n")
                
                # Set the cleaned content to the preview box
                self.preview_box.setPlainText(content_without_leading_blanks)
        else:
            self.preview_box.setPlainText("File not found.")



    def open_file_in_editor(self, item):
        filename = item.text()
        if self.directory:
            filepath = os.path.join(self.directory, filename)
            if os.path.exists(filepath):
                try:
                    if sys.platform == "win32":
                        os.startfile(filepath)
                    elif sys.platform == "darwin":
                        subprocess.call(('open', filepath))
                    else:
                        subprocess.call(('xdg-open', filepath))
                except Exception as e:
                    print(f"Failed to open file: {e}")
            else:
                print(f"File not found: {filepath}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ExampleFinderApp()
    window.show()
    sys.exit(app.exec_())
