# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Color tokens and stylesheets for the modernized pypts GUI."""

CERN_BLUE = "#0033A0"
CERN_DARK = "#002080"
MTA_BLUE = "#005BAC"
CEM_BLUE = "#1E73BE"
ACCENT_RED = "#CC0000"

STATUS_COLORS = {
    "PASS": {"bg": "#C8E6C9", "text": "#1B4F24"},
    "FAIL": {"bg": "#F28B82", "text": "#7B0000"},
    "DONE": {"bg": "#B2EBF2", "text": "#004D52"},
    "SKIP": {"bg": "#FFF9C4", "text": "#C49000"},
    "ERROR": {"bg": "#FFCC80", "text": "#BF360C"},
    "STOP": {"bg": "#D3D3D3", "text": "#4B4B4B"},
    "PENDING": {"bg": "#E8EAF0", "text": "#555555"},
    "RUNNING": {"bg": "#DBEAFE", "text": "#1D4ED8"},
}

LOG_LEVEL_COLORS = {
    "INFO": "#6abf69",
    "DEBUG": "#6897bb",
    "WARNING": "#FFCC80",
    "WARN": "#FFCC80",
    "ERROR": "#F28B82",
    "CRITICAL": "#ff7c9c",
}

LIGHT_QSS = f"""
QMainWindow, QWidget {{
    background-color: #f5f7fa;
    color: #1a1a2e;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QMenuBar {{
    background-color: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 5px 12px;
}}
QMenuBar::item:selected {{
    background-color: #E3ECF9;
    color: {CERN_BLUE};
}}
QMenu {{
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
}}
QMenu::item:selected {{
    background-color: #E3ECF9;
    color: {CERN_BLUE};
}}
QToolBar {{
    background-color: #F8FAFC;
    border-bottom: 1px solid #e2e8f0;
    padding: 4px 10px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 11px;
    color: #424242;
}}
QToolBar QToolButton:hover {{
    background-color: #E3ECF9;
    color: {CERN_BLUE};
}}
QToolBar QToolButton:disabled {{
    color: #BDBDBD;
}}
QTabBar {{
    background: {CERN_BLUE};
}}
QTabBar::tab {{
    background: transparent;
    color: #B3CFF0;
    padding: 6px 16px;
    font-size: 11px;
    border: none;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {MTA_BLUE};
    color: #ffffff;
    font-weight: 600;
}}
QTableWidget, QTreeView {{
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    font-size: 12px;
    alternate-background-color: #fafbfe;
    selection-background-color: #EEF5FF;
    selection-color: #1a1a2e;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid #f0f0f0;
}}
QHeaderView::section {{
    background-color: #F0F4FA;
    color: {MTA_BLUE};
    font-size: 11px;
    font-weight: 600;
    padding: 9px 12px;
    border: none;
    border-bottom: 2px solid #B3CFF0;
}}
QPlainTextEdit {{
    background-color: #f5f5f5;
    color: #333333;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    font-family: "Courier New", monospace;
    font-size: 11px;
    padding: 6px 8px;
}}
QPushButton {{
    font-size: 13px;
    font-weight: 500;
    padding: 7px 18px;
    border-radius: 6px;
    border: 1px solid #B3CFF0;
    background-color: #E3ECF9;
    color: {CERN_BLUE};
}}
QPushButton:hover {{
    background-color: #c8d8f4;
}}
QPushButton#primaryBtn {{
    background-color: {CERN_BLUE};
    color: #ffffff;
    border: none;
}}
QPushButton#primaryBtn:hover {{
    background-color: {MTA_BLUE};
}}
QPushButton#primaryBtn[promptSelected="false"] {{
    background-color: #E3ECF9;
    color: {CERN_BLUE};
    border: 1px solid #B3CFF0;
}}
QPushButton[promptSelected="true"] {{
    background-color: {CERN_BLUE};
    color: #ffffff;
    border: 1px solid {CERN_DARK};
}}
QPushButton#stopBtn {{
    background-color: #FFEBEE;
    color: {ACCENT_RED};
    border: 1px solid #FFCDD2;
}}
QLabel#sectionLabel {{
    font-size: 10px;
    font-weight: 600;
    color: #94a3b8;
    letter-spacing: 0.08em;
}}
QLabel#recipeLabel {{
    font-size: 12px;
    font-weight: 500;
    color: {MTA_BLUE};
}}
QStatusBar {{
    background-color: #F0F4FA;
    border-top: 1px solid #e2e8f0;
    color: #718096;
    font-size: 10px;
}}
QSplitter::handle {{
    background-color: #e2e8f0;
    width: 1px;
}}
QAbstractScrollArea {{
    background-clip: padding;
}}
QScrollBar:vertical {{
    background: #edf2f7;
    width: 12px;
    margin: 6px 4px 6px 0;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: #b7c7db;
    min-height: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: #90a9c9;
}}
QScrollBar::handle:vertical:pressed {{
    background: #6e8eb7;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: #edf2f7;
    height: 12px;
    margin: 0 6px 4px 6px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: #b7c7db;
    min-width: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #90a9c9;
}}
QScrollBar::handle:horizontal:pressed {{
    background: #6e8eb7;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""

DARK_QSS = f"""
QMainWindow, QWidget {{
    background-color: #2b2b2b;
    color: #f0f0f0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QMenuBar {{
    background-color: #2b2b2b;
    border-bottom: 1px solid #3a3a3a;
}}
QMenuBar::item {{
    padding: 5px 12px;
}}
QMenuBar::item:selected {{
    background-color: #444444;
}}
QMenu {{
    background-color: #2b2b2b;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
}}
QMenu::item:selected {{
    background-color: #444444;
}}
QToolBar {{
    background-color: #232323;
    border-bottom: 1px solid #3a3a3a;
    padding: 4px 10px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 11px;
    color: #f0f0f0;
}}
QToolBar QToolButton:hover {{
    background-color: #3a3a3a;
    color: #7AABDF;
}}
QToolBar QToolButton:disabled {{
    color: #555555;
}}
QTabBar::tab {{
    background: transparent;
    color: #B3CFF0;
    padding: 6px 16px;
    font-size: 11px;
    border: none;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {MTA_BLUE};
    color: #ffffff;
    font-weight: 600;
}}
QTableWidget, QTreeView {{
    background-color: #3c3f41;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    font-size: 12px;
    color: #f0f0f0;
    alternate-background-color: #404346;
    selection-background-color: #1a2840;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid #3a3a3a;
}}
QHeaderView::section {{
    background-color: #2b2b2b;
    color: #7AABDF;
    font-size: 11px;
    font-weight: 600;
    padding: 9px 12px;
    border: none;
    border-bottom: 2px solid #005BAC44;
}}
QPlainTextEdit {{
    background-color: #1e1e1e;
    color: #b0b0b0;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    font-family: "Courier New", monospace;
    font-size: 11px;
    padding: 6px 8px;
}}
QPushButton {{
    font-size: 13px;
    font-weight: 500;
    padding: 7px 18px;
    border-radius: 6px;
    border: 1px solid #5a5a5a;
    background-color: #3c3f41;
    color: #f0f0f0;
}}
QPushButton:hover {{
    background-color: #5c5c5c;
}}
QPushButton#primaryBtn {{
    background-color: {CERN_BLUE};
    color: #ffffff;
    border: none;
}}
QPushButton#primaryBtn:hover {{
    background-color: {MTA_BLUE};
}}
QPushButton#primaryBtn[promptSelected="false"] {{
    background-color: #3c3f41;
    color: #f0f0f0;
    border: 1px solid #5a5a5a;
}}
QPushButton[promptSelected="true"] {{
    background-color: {CERN_BLUE};
    color: #ffffff;
    border: 1px solid {MTA_BLUE};
}}
QPushButton#stopBtn {{
    background-color: #3a1a1a;
    color: #F28B82;
    border: 1px solid #5a2a2a;
}}
QLabel#recipeLabel {{
    font-size: 12px;
    font-weight: 500;
    color: #7AABDF;
}}
QLabel#sectionLabel {{
    font-size: 10px;
    font-weight: 600;
    color: #666666;
    letter-spacing: 0.08em;
}}
QStatusBar {{
    background-color: #1e1e1e;
    border-top: 1px solid #3a3a3a;
    color: #666666;
    font-size: 10px;
}}
QSplitter::handle {{
    background-color: #3a3a3a;
    width: 1px;
}}
QAbstractScrollArea {{
    background-clip: padding;
}}
QScrollBar:vertical {{
    background: #232a33;
    width: 12px;
    margin: 6px 4px 6px 0;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: #55697f;
    min-height: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: #6b829b;
}}
QScrollBar::handle:vertical:pressed {{
    background: #85a2c4;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: #232a33;
    height: 12px;
    margin: 0 6px 4px 6px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: #55697f;
    min-width: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #6b829b;
}}
QScrollBar::handle:horizontal:pressed {{
    background: #85a2c4;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
"""


def get_stylesheet(dark: bool = False) -> str:
    return DARK_QSS if dark else LIGHT_QSS
