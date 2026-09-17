# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The stylesheet, built from the tokens in palette.py.

Structure only: there is not one colour literal in this file, and there must
never be. A colour to change is a token in palette.py; a *rule* to change is
here. `python -m pypts.hmi.gui.palette` shows what the tokens look like.

There is one template, applied to the palette of the theme in use, so a rule
exists in both themes or in neither. Where the themes want a different colour
for the same rule, that is one token with a different value in each palette -
never a second copy of the rule.
"""

from pypts.hmi.gui.palette import DARK, LIGHT, Palette, get_palette


def get_stylesheet(dark: bool = False) -> str:
    """The stylesheet for one theme. Applied to the whole QApplication."""
    return _build_qss(get_palette(dark))


def _build_qss(palette: Palette) -> str:
    """
    The whole stylesheet, in the colours of one palette.

    The theme swatches in the settings dialog are the one place that names
    LIGHT and DARK directly: they picture both themes side by side, whichever
    one is in use.
    """
    return f"""
QMainWindow, QWidget {{
    background-color: {palette.window};
    color: {palette.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QMenuBar {{
    background-color: {palette.menu_background};
    border-bottom: 1px solid {palette.border};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 5px 12px;
}}
QMenuBar::item:selected {{
    background-color: {palette.menu_highlight};
    color: {palette.menu_highlight_text};
}}
QMenu {{
    background-color: {palette.menu_background};
    border: 1px solid {palette.border};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
}}
QMenu::item:selected {{
    background-color: {palette.menu_highlight};
    color: {palette.menu_highlight_text};
}}
QToolBar {{
    background-color: {palette.toolbar_background};
    border-bottom: 1px solid {palette.border};
    padding: 4px 10px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 11px;
    color: {palette.toolbutton};
}}
QToolBar QToolButton:hover {{
    background-color: {palette.toolbutton_hover};
    color: {palette.toolbutton_hover_text};
}}
QToolBar QToolButton:disabled {{
    color: {palette.toolbutton_disabled};
}}
QTabBar {{
    background: {palette.header_background};
}}
QTabBar::tab {{
    color: {palette.tab_text};
    padding: 6px 16px;
    font-size: 11px;
    border: none;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {palette.tab_selected_background};
    color: {palette.tab_selected_text};
}}
QTableWidget, QTreeView {{
    background-color: {palette.table_background};
    color: {palette.text};
    border: 1px solid {palette.border};
    border-radius: 8px;
    font-size: 12px;
    alternate-background-color: {palette.row_alternate};
    gridline-color: {palette.grid_line};
    selection-background-color: {palette.selection_background};
    selection-color: {palette.selection_text};
}}
/* No QTableWidget::item rule, deliberately: an ::item rule hands item painting
   to the stylesheet, and the model's background brush is then ignored - which
   is what made every PASS/FAIL verdict render as plain text. The step table
   sets those colours per item (step_table.py), so it must keep the default
   painting path. Cell spacing comes from the font size and the row height
   instead. Restoring an ::item rule here means writing a QStyledItemDelegate
   for the verdict badges first - roadmap: the StepTable badge delegate TODO. */
QHeaderView::section {{
    background-color: {palette.header_background};
    color: {palette.accent_text};
    font-size: 11px;
    font-weight: 600;
    padding: 9px 12px;
    border: none;
    border-bottom: 2px solid {palette.header_underline};
}}
QTableWidget#stepTable {{
    font-size: 12px;
}}
QTableWidget#stepTable QHeaderView::section {{
    font-size: 12px;
    padding: 4px 6px;
}}
QPlainTextEdit {{
    background-color: {palette.log_background};
    color: {palette.log_text};
    border: 1px solid {palette.border};
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
    border: 1px solid {palette.button_border};
    background-color: {palette.button_background};
    color: {palette.button_text};
}}
QPushButton:hover {{
    background-color: {palette.button_hover};
}}
QPushButton#primaryBtn {{
    background-color: {palette.brand};
    color: {palette.text_on_brand};
    border: none;
}}
QPushButton#primaryBtn:hover {{
    background-color: {palette.brand_accent};
}}
QPushButton#primaryBtn[promptSelected="false"] {{
    background-color: {palette.button_background};
    color: {palette.button_text};
    border: 1px solid {palette.button_border};
}}
QPushButton[promptSelected="true"] {{
    background-color: {palette.brand};
    color: {palette.text_on_brand};
    border: 1px solid {palette.brand_dark};
}}
QPushButton#stopBtn {{
    background-color: {palette.danger_background};
    color: {palette.danger};
    border: 1px solid {palette.danger_border};
}}
QPushButton#settingsDangerBtn {{
    background-color: {palette.danger_background};
    color: {palette.danger};
    border: 1px solid {palette.danger_border};
    font-weight: 600;
}}
QPushButton#settingsDangerBtn:hover {{
    background-color: {palette.danger_border};
}}
QPushButton#settingsDangerBtn:disabled {{
    background-color: {palette.window};
    color: {palette.toolbutton_disabled};
    border: 1px solid {palette.border};
}}
QListWidget#settingsNav {{
    background-color: {palette.panel_background};
    border: none;
    border-right: 1px solid {palette.border};
    padding: 14px 8px;
    font-size: 13px;
    outline: 0;
}}
QListWidget#settingsNav::item {{
    padding: 9px 12px;
    margin-bottom: 2px;
    border-radius: 6px;
    color: {palette.text};
}}
QListWidget#settingsNav::item:hover {{
    background-color: {palette.menu_highlight};
}}
QListWidget#settingsNav::item:selected {{
    background-color: {palette.brand_accent};
    color: {palette.text_on_brand};
}}
QFrame#settingsFooter {{
    border-top: 1px solid {palette.border};
}}
QLabel#settingsFooterNote, QLabel#settingsSubtitle {{
    font-size: 12px;
    color: {palette.text_muted};
}}
QLabel#settingsPageTitle, QLabel#settingsResultTitle {{
    font-size: 18px;
    font-weight: 600;
    color: {palette.accent_text};
}}
QFrame#settingsCard {{
    border: 1px solid {palette.border};
    border-radius: 8px;
}}
QFrame#settingsCard[modified="true"] {{
    border: 1px solid {palette.brand_accent};
}}
QLabel#settingsCardTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {palette.text};
}}
QLabel#settingsCardHint {{
    font-size: 11px;
    color: {palette.section_label};
}}
QLabel#settingsError, QLabel#settingsProblem, QLabel#settingsRefused {{
    font-size: 12px;
    color: {palette.danger};
}}
QLabel#settingsSaved {{
    font-size: 12px;
    color: {palette.text};
}}
QPushButton#settingsReset {{
    background-color: transparent;
    border: none;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
    color: {palette.accent_text};
}}
QPushButton#settingsReset:hover {{
    color: {palette.button_text};
}}
QPushButton#settingsSegment, QPushButton#settingsPreset {{
    background-color: {palette.window};
    color: {palette.text};
    border: 1px solid {palette.button_border};
    border-radius: 6px;
    padding: 4px 14px;
    font-size: 12px;
}}
QPushButton#settingsPreset {{
    padding: 3px 10px;
    font-size: 11px;
    border-radius: 11px;
}}
QPushButton#settingsSegment:hover, QPushButton#settingsPreset:hover {{
    border: 1px solid {palette.brand_accent};
}}
QPushButton#settingsSegment:checked {{
    background-color: {palette.brand_accent};
    color: {palette.text_on_brand};
    border: 1px solid {palette.brand_accent};
}}
QPushButton#settingsSwitch {{
    background-color: {palette.window};
    color: {palette.text_muted};
    border: 1px solid {palette.button_border};
    border-radius: 15px;
    padding: 0;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#settingsSwitch:checked {{
    background-color: {palette.brand_accent};
    color: {palette.text_on_brand};
    border: 1px solid {palette.brand_accent};
}}
QPushButton#settingsThemeCard {{
    background-color: {palette.window};
    border: 2px solid {palette.border};
    border-radius: 10px;
    padding: 0;
}}
QPushButton#settingsThemeCard:hover {{
    border: 2px solid {palette.button_border};
}}
QPushButton#settingsThemeCard:checked {{
    border: 2px solid {palette.brand_accent};
}}
QLabel#settingsThemeName {{
    font-size: 13px;
    font-weight: 600;
    color: {palette.text};
}}
QLabel#settingsThemeHint {{
    font-size: 11px;
    color: {palette.section_label};
}}
QFrame#themeSwatchLight {{
    background-color: {LIGHT.window};
    border: 1px solid {LIGHT.border};
}}
QFrame#themeSwatchLightBar {{
    background-color: {LIGHT.brand};
    border: none;
}}
QFrame#themeSwatchDark {{
    background-color: {DARK.window};
    border: 1px solid {DARK.border};
}}
QFrame#themeSwatchDarkBar {{
    background-color: {DARK.brand_accent};
    border: none;
}}
QDialog#settingsDialog QLineEdit, QDialog#settingsDialog QSpinBox {{
    background-color: {palette.table_background};
    color: {palette.text};
    border: 1px solid {palette.button_border};
    border-radius: 4px;
    padding: 4px 6px;
}}
QDialog#settingsDialog QLineEdit:focus, QDialog#settingsDialog QSpinBox:focus {{
    border: 1px solid {palette.brand_accent};
}}
QDialog#settingsDialog QLineEdit:disabled, QDialog#settingsDialog QSpinBox:disabled {{
    background-color: {palette.window};
    color: {palette.toolbutton_disabled};
}}
QPushButton#settingsBrowse {{
    font-size: 12px;
    padding: 4px 12px;
}}
QDialog#settingsDialog QPushButton#primaryBtn:disabled {{
    background-color: {palette.window};
    color: {palette.toolbutton_disabled};
    border: 1px solid {palette.border};
}}
QLabel#idleHint {{
    font-size: 12px;
    color: {palette.section_label};
}}
QLabel#sectionLabel {{
    font-size: 10px;
    padding-left: 9px;
    font-weight: 600;
    color: {palette.section_label};
    letter-spacing: 0.08em;
}}
QLabel#statusLabel {{
    padding-left: 10px;
    padding-bottom: 2px;
}}
QLabel#versionLabel {{
    font-size: 10px;
    color: {palette.text_muted};
    padding-right: 10px;
}}
QProgressBar#runProgressBar {{
    background-color: {palette.progress_track};
    border: none;
    border-radius: 4px;
}}
QProgressBar#runProgressBar::chunk {{
    background-color: {palette.progress_fill};
    border-radius: 4px;
}}
QLabel#runProgressLabel {{
    font-size: 11px;
    color: {palette.text_muted};
}}
QLabel#recipeLabel {{
    font-size: 12px;
    font-weight: 500;
    color: {palette.accent_text};
}}
QStatusBar {{
    background-color: {palette.status_background};
    border-top: 1px solid {palette.border};
    color: {palette.text_muted};
    font-size: 10px;
}}
QSplitter::handle {{
    background-color: {palette.border};
    width: 1px;
}}
QAbstractScrollArea {{
    background-clip: padding;
}}
QScrollBar:vertical {{
    background: {palette.scroll_track};
    width: 12px;
    margin: 6px 4px 6px 0;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: {palette.scroll_handle};
    min-height: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: {palette.scroll_handle_hover};
}}
QScrollBar::handle:vertical:pressed {{
    background: {palette.scroll_handle_pressed};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
}}
QScrollBar:horizontal {{
    background: {palette.scroll_track};
    height: 12px;
    margin: 0 6px 4px 6px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {palette.scroll_handle};
    min-width: 32px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {palette.scroll_handle_hover};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {palette.scroll_handle_pressed};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
}}
"""
