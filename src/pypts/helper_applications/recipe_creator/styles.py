# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
dark_style = """
* {
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
}
QWidget {
    background-color: #2b2b2b;
    color: #f0f0f0;
}
QMenuBar {
    background-color: #2b2b2b;
}
QMenuBar::item {
    background: transparent;
    color: #f0f0f0;
}
QMenuBar::item:selected {
    background: #444;
}
QMenu {
    background-color: #2b2b2b;
    color: #f0f0f0;
}
QMenu::item:selected {
    background-color: #444;
}
QTreeWidget, QTextEdit {
    background-color: #3c3f41;
    color: #f0f0f0;
    selection-background-color: #2e2e2e;
    selection-color: #ffffff;
    alternate-background-color: #2f2f2f;
}
QHeaderView::section {
    background-color: #2b2b2b;
    color: #f0f0f0;
    padding: 4px;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #2b2b2b;
    border: none;
    width: 10px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #5c5c5c;
    border-radius: 5px;
}
QPushButton {
    background-color: #4a4a4a;
    color: #f0f0f0;
    border: 1px solid #5a5a5a;
    padding: 5px;
}
QPushButton:hover {
    background-color: #5c5c5c;
}
"""

light_style = """
    * {
        font-family: "Segoe UI", sans-serif;
        font-size: 10pt;
    }
    QHeaderView::section {
        padding: 4px;
    }
    QScrollBar:vertical, QScrollBar:horizontal {
        border: none;
        width: 10px;
    }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        border-radius: 5px;
    }
    QPushButton {
        color: #f0f0f0;
        padding: 5px;
    }
"""
