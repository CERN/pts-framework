# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The two stylesheets, built from the tokens in palette.py.

Structure only: there is not one colour literal in this file, and there must
never be. A colour to change is a token in palette.py; a *rule* to change is
here. `python -m pypts.hmi.gui.palette` shows what the tokens look like.

The light and dark sheets are still two texts rather than one template applied
twice - they are nearly identical, but not quite (light styles a QTabBar that
dark does not), and merging them would change how one of the two themes looks.
That is a job of its own, not a side effect of moving the colours out.
"""

from pypts.hmi.gui.palette import DARK, LIGHT

LIGHT_QSS = f"""
QMainWindow, QWidget {{
    background-color: {LIGHT.window};
    color: {LIGHT.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QMenuBar {{
    background-color: {LIGHT.text_on_brand};
    border-bottom: 1px solid {LIGHT.border};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 5px 12px;
}}
QMenuBar::item:selected {{
    background-color: {LIGHT.menu_highlight};
    color: {LIGHT.brand};
}}
QMenu {{
    background-color: {LIGHT.text_on_brand};
    border: 1px solid {LIGHT.border};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
}}
QMenu::item:selected {{
    background-color: {LIGHT.menu_highlight};
    color: {LIGHT.brand};
}}
QToolBar {{
    background-color: {LIGHT.toolbar_background};
    border-bottom: 1px solid {LIGHT.border};
    padding: 4px 10px;
    spacing: 4px;
}}
QToolBar QToolButton {{

    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 11px;
    color: {LIGHT.toolbutton};
}}
QToolBar QToolButton:hover {{
    background-color: {LIGHT.menu_highlight};
    color: {LIGHT.brand};
}}
QToolBar QToolButton:disabled {{
    color: {LIGHT.toolbutton_disabled};
}}
QTabBar {{
    background: {LIGHT.brand};
}}
QTabBar::tab {{

    color: {LIGHT.header_underline};
    padding: 6px 16px;
    font-size: 11px;
    border: none;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {LIGHT.brand_accent};
    color: {LIGHT.text_on_brand};
    font-weight: 600;
}}
QTableWidget, QTreeView {{
    background-color: {LIGHT.text_on_brand};
    border: 1px solid {LIGHT.border};
    border-radius: 8px;
    font-size: 12px;
    alternate-background-color: {LIGHT.row_alternate};
    gridline-color: {LIGHT.grid_line};
    selection-background-color: {LIGHT.selection_background};
    selection-color: {LIGHT.text};
}}
/* No QTableWidget::item rule, deliberately: an ::item rule hands item painting
   to the stylesheet, and the model's background brush is then ignored - which
   is what made every PASS/FAIL verdict render as plain text. The step table
   sets those colours per item (step_table.py), so it must keep the default
   painting path. Cell spacing comes from the font size and the row height
   instead. Restoring an ::item rule here means writing a QStyledItemDelegate
   for the verdict badges first - roadmap: the StepTable badge delegate TODO. */
QHeaderView::section {{
    background-color: {LIGHT.header_background};
    color: {LIGHT.brand_accent};
    font-size: 11px;
    font-weight: 600;
    padding: 9px 12px;
    border: none;
    border-bottom: 2px solid {LIGHT.header_underline};
}}
QTableWidget#stepTable {{
    font-size: 12px;
}}
QTableWidget#stepTable QHeaderView::section {{
    font-size: 12px;
    padding: 4px 6px;
}}
QPlainTextEdit {{
    background-color: {LIGHT.log_background};
    color: {LIGHT.log_text};
    border: 1px solid {LIGHT.border};
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
    border: 1px solid {LIGHT.header_underline};
    background-color: {LIGHT.menu_highlight};
    color: {LIGHT.brand};
}}
QPushButton:hover {{
    background-color: {LIGHT.button_hover};
}}
QPushButton#primaryBtn {{
    background-color: {LIGHT.brand};
    color: {LIGHT.text_on_brand};
    border: none;
}}
QPushButton#primaryBtn:hover {{
    background-color: {LIGHT.brand_accent};
}}
QPushButton#primaryBtn[promptSelected="false"] {{
    background-color: {LIGHT.menu_highlight};
    color: {LIGHT.brand};
    border: 1px solid {LIGHT.header_underline};
}}
QPushButton[promptSelected="true"] {{
    background-color: {LIGHT.brand};
    color: {LIGHT.text_on_brand};
    border: 1px solid {LIGHT.brand_dark};
}}
QPushButton#stopBtn {{
    background-color: {LIGHT.danger_background};
    color: {LIGHT.danger};
    border: 1px solid {LIGHT.danger_border};
}}
QDialog#cacheDialog {{
    background-color: {LIGHT.menu_background};
}}
QLabel#cacheDialogTitle {{
    font-size: 17px;
    font-weight: 600;
    color: {LIGHT.accent_text};
}}
QLabel#cacheDialogSubtitle {{
    font-size: 12px;
    color: {LIGHT.text_muted};
    padding-top: 2px;
}}
QLabel#cacheDialogItemLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {LIGHT.text};
}}
QLabel#cacheDialogDetail {{
    font-size: 11px;
    color: {LIGHT.section_label};
}}
QLabel#cacheDialogSize {{
    font-size: 12px;
    font-weight: 600;
    color: {LIGHT.accent_text};
}}
QLabel#cacheDialogSize[empty="true"] {{
    font-weight: 400;
    color: {LIGHT.toolbutton_disabled};
}}
QLabel#cacheDialogNote {{
    font-size: 11px;
    color: {LIGHT.accent_text};
}}
QFrame#cacheDialogSeparator {{
    background-color: {LIGHT.border};
    border: none;
}}
QLabel#cacheDialogTotalLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {LIGHT.text_muted};
}}
QLabel#cacheDialogTotal {{
    font-size: 14px;
    font-weight: 700;
    color: {LIGHT.text};
}}
QLabel#cacheDialogFailure {{
    font-size: 11px;
    color: {LIGHT.danger};
}}
QCheckBox#cacheDialogCheck {{
    font-size: 13px;
    font-weight: 600;
    color: {LIGHT.text};
    spacing: 8px;
}}
QCheckBox#cacheDialogCheck:disabled {{
    color: {LIGHT.toolbutton_disabled};
    font-weight: 400;
}}
QCheckBox#cacheDialogCheck::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {LIGHT.button_border};
    border-radius: 3px;
    background-color: {LIGHT.table_background};
}}
QCheckBox#cacheDialogCheck::indicator:hover {{
    border: 1px solid {LIGHT.brand_accent};
}}
QCheckBox#cacheDialogCheck::indicator:checked {{
    border: 1px solid {LIGHT.brand_accent};
    background-color: {LIGHT.brand_accent};
}}
QCheckBox#cacheDialogCheck::indicator:disabled {{
    border: 1px solid {LIGHT.border};
    background-color: {LIGHT.window};
}}
QPushButton#cacheDialogRemoveBtn {{
    background-color: {LIGHT.danger_background};
    color: {LIGHT.danger};
    border: 1px solid {LIGHT.danger_border};
    font-weight: 600;
}}
QPushButton#cacheDialogRemoveBtn:hover {{
    background-color: {LIGHT.danger_border};
}}
QPushButton#cacheDialogRemoveBtn:disabled {{
    background-color: {LIGHT.window};
    color: {LIGHT.toolbutton_disabled};
    border: 1px solid {LIGHT.border};
}}
QLabel#sectionLabel {{
    font-size: 10px;
    padding-left: 9px;
    font-weight: 600;
    color: {LIGHT.section_label};
    letter-spacing: 0.08em;
}}
QLabel#statusLabel {{
    padding-left: 10px;
    padding-bottom: 2px;
}}
QLabel#recipeLabel {{
    font-size: 12px;
    font-weight: 500;
    color: {LIGHT.brand_accent};
}}
QStatusBar {{
    background-color: {LIGHT.header_background};
    border-top: 1px solid {LIGHT.border};
    color: {LIGHT.text_muted};
    font-size: 10px;
}}
QSplitter::handle {{
    background-color: {LIGHT.border};
    width: 1px;
}}
QAbstractScrollArea {{
    background-clip: padding;
}}
QScrollBar:vertical {{
    background: {LIGHT.scroll_track};
    width: 12px;
    margin: 6px 4px 6px 0;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: {LIGHT.scroll_handle};
    min-height: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: {LIGHT.scroll_handle_hover};
}}
QScrollBar::handle:vertical:pressed {{
    background: {LIGHT.scroll_handle_pressed};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{

}}
QScrollBar:horizontal {{
    background: {LIGHT.scroll_track};
    height: 12px;
    margin: 0 6px 4px 6px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {LIGHT.scroll_handle};
    min-width: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {LIGHT.scroll_handle_hover};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {LIGHT.scroll_handle_pressed};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{

}}
"""

DARK_QSS = f"""
QMainWindow, QWidget {{
    background-color: {DARK.window};
    color: {DARK.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QMenuBar {{
    background-color: {DARK.window};
    border-bottom: 1px solid {DARK.border};
}}
QMenuBar::item {{
    padding: 5px 12px;
}}
QMenuBar::item:selected {{
    background-color: {DARK.menu_highlight};
}}
QMenu {{
    background-color: {DARK.window};
    border: 1px solid {DARK.border};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
}}
QMenu::item:selected {{
    background-color: {DARK.menu_highlight};
}}
QToolBar {{
    background-color: {DARK.toolbar_background};
    border-bottom: 1px solid {DARK.border};
    padding: 4px 10px;
}}
QToolBar QToolButton {{

    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 11px;
    color: {DARK.text};
}}
QToolBar QToolButton:hover {{
    background-color: {DARK.border};
    color: {DARK.accent_text};
}}
QToolBar QToolButton:disabled {{
    color: {DARK.toolbutton_disabled};
}}
QTabBar::tab {{

    color: {DARK.tab_text};
    padding: 6px 16px;
    font-size: 11px;
    border: none;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {DARK.brand_accent};
    color: {DARK.text_on_brand};
    font-weight: 600;
}}
QTableWidget, QTreeView {{
    background-color: {DARK.table_background};
    border: 1px solid {DARK.border};
    border-radius: 8px;
    font-size: 12px;
    color: {DARK.text};
    alternate-background-color: {DARK.row_alternate};
    gridline-color: {DARK.grid_line};
    selection-background-color: {DARK.selection_background};
}}
/* No QTableWidget::item rule, deliberately: an ::item rule hands item painting
   to the stylesheet, and the model's background brush is then ignored - which
   is what made every PASS/FAIL verdict render as plain text. The step table
   sets those colours per item (step_table.py), so it must keep the default
   painting path. Cell spacing comes from the font size and the row height
   instead. Restoring an ::item rule here means writing a QStyledItemDelegate
   for the verdict badges first - roadmap: the StepTable badge delegate TODO. */
QHeaderView::section {{
    background-color: {DARK.window};
    color: {DARK.accent_text};
    font-size: 11px;
    font-weight: 600;
    padding: 9px 12px;
    border: none;
    border-bottom: 2px solid {DARK.header_underline};
}}
QTableWidget#stepTable {{
    font-size: 12px;
}}
QTableWidget#stepTable QHeaderView::section {{
    font-size: 12px;
    padding: 4px 6px;
}}
QPlainTextEdit {{
    background-color: {DARK.log_background};
    color: {DARK.log_text};
    border: 1px solid {DARK.border};
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
    border: 1px solid {DARK.button_border};
    background-color: {DARK.table_background};
    color: {DARK.text};
}}
QPushButton:hover {{
    background-color: {DARK.button_hover};
}}
QPushButton#primaryBtn {{
    background-color: {DARK.brand};
    color: {DARK.text_on_brand};
    border: none;
}}
QPushButton#primaryBtn:hover {{
    background-color: {DARK.brand_accent};
}}
QPushButton#primaryBtn[promptSelected="false"] {{
    background-color: {DARK.table_background};
    color: {DARK.text};
    border: 1px solid {DARK.button_border};
}}
QPushButton[promptSelected="true"] {{
    background-color: {DARK.brand};
    color: {DARK.text_on_brand};
    border: 1px solid {DARK.brand_accent};
}}
QPushButton#stopBtn {{
    background-color: {DARK.danger_background};
    color: {DARK.danger};
    border: 1px solid {DARK.danger_border};
}}
QDialog#cacheDialog {{
    background-color: {DARK.menu_background};
}}
QLabel#cacheDialogTitle {{
    font-size: 17px;
    font-weight: 600;
    color: {DARK.accent_text};
}}
QLabel#cacheDialogSubtitle {{
    font-size: 12px;
    color: {DARK.text_muted};
    padding-top: 2px;
}}
QLabel#cacheDialogItemLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {DARK.text};
}}
QLabel#cacheDialogDetail {{
    font-size: 11px;
    color: {DARK.section_label};
}}
QLabel#cacheDialogSize {{
    font-size: 12px;
    font-weight: 600;
    color: {DARK.accent_text};
}}
QLabel#cacheDialogSize[empty="true"] {{
    font-weight: 400;
    color: {DARK.toolbutton_disabled};
}}
QLabel#cacheDialogNote {{
    font-size: 11px;
    color: {DARK.accent_text};
}}
QFrame#cacheDialogSeparator {{
    background-color: {DARK.border};
    border: none;
}}
QLabel#cacheDialogTotalLabel {{
    font-size: 12px;
    font-weight: 600;
    color: {DARK.text_muted};
}}
QLabel#cacheDialogTotal {{
    font-size: 14px;
    font-weight: 700;
    color: {DARK.text};
}}
QLabel#cacheDialogFailure {{
    font-size: 11px;
    color: {DARK.danger};
}}
QCheckBox#cacheDialogCheck {{
    font-size: 13px;
    font-weight: 600;
    color: {DARK.text};
    spacing: 8px;
}}
QCheckBox#cacheDialogCheck:disabled {{
    color: {DARK.toolbutton_disabled};
    font-weight: 400;
}}
QCheckBox#cacheDialogCheck::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {DARK.button_border};
    border-radius: 3px;
    background-color: {DARK.table_background};
}}
QCheckBox#cacheDialogCheck::indicator:hover {{
    border: 1px solid {DARK.brand_accent};
}}
QCheckBox#cacheDialogCheck::indicator:checked {{
    border: 1px solid {DARK.brand_accent};
    background-color: {DARK.brand_accent};
}}
QCheckBox#cacheDialogCheck::indicator:disabled {{
    border: 1px solid {DARK.border};
    background-color: {DARK.window};
}}
QPushButton#cacheDialogRemoveBtn {{
    background-color: {DARK.danger_background};
    color: {DARK.danger};
    border: 1px solid {DARK.danger_border};
    font-weight: 600;
}}
QPushButton#cacheDialogRemoveBtn:hover {{
    background-color: {DARK.danger_border};
}}
QPushButton#cacheDialogRemoveBtn:disabled {{
    background-color: {DARK.window};
    color: {DARK.toolbutton_disabled};
    border: 1px solid {DARK.border};
}}
QLabel#statusLabel {{
    padding-left: 10px;
    padding-bottom: 2px;
}}
QLabel#recipeLabel {{
    font-size: 12px;
    font-weight: 500;
    color: {DARK.accent_text};
}}
QLabel#sectionLabel {{
    font-size: 10px;
    padding-left: 9px;
    font-weight: 600;
    color: {DARK.text_muted};
    letter-spacing: 0.08em;
}}
QStatusBar {{
    background-color: {DARK.log_background};
    border-top: 1px solid {DARK.border};
    color: {DARK.text_muted};
    font-size: 10px;
}}
QSplitter::handle {{
    background-color: {DARK.border};
    width: 1px;
}}
QAbstractScrollArea {{
    background-clip: padding;
}}
QScrollBar:vertical {{
    background: {DARK.scroll_track};
    width: 12px;
    margin: 6px 4px 6px 0;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: {DARK.scroll_handle};
    min-height: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: {DARK.scroll_handle_hover};
}}
QScrollBar::handle:vertical:pressed {{
    background: {DARK.scroll_handle_pressed};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{

}}
QScrollBar:horizontal {{
    background: {DARK.scroll_track};
    height: 12px;
    margin: 0 6px 4px 6px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {DARK.scroll_handle};
    min-width: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {DARK.scroll_handle_hover};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {DARK.scroll_handle_pressed};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{

}}
"""


def get_stylesheet(dark: bool = False) -> str:
    """The stylesheet for one theme. Applied to the whole QApplication."""
    return DARK_QSS if dark else LIGHT_QSS
