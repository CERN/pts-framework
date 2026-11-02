"""
One shared QSS stylesheet for the whole app. PyradeXYGraphWidget applies
it once (see graph_widget.py's __init__) and it cascades to every
descendant, including widgets inside SignalTreeWidget's own per-row
stylesheets - Qt combines ancestor stylesheets rather than a closer one
blocking a farther one.

Built entirely from palette() references, not hardcoded colors, so it
follows the OS light/dark theme instead of fighting it.

SPACING is the base unit every margin/padding here is a multiple of (an
8px grid) - section headers (_titled(), in graph_widget.py) and their
content widgets (SignalTreeWidget/MathDockWidget/LogPanel) share it so
their left edges line up.
"""

SPACING = 8  # px

GLOBAL_STYLESHEET = f"""
QToolBar {{
    background: palette(window);
    border: none;
    border-bottom: 1px solid palette(mid);
    padding: 4px {SPACING // 2}px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    padding: 4px 10px;
    border: 1px solid transparent;
    border-radius: 4px;
    color: palette(text);
}}
QToolBar QToolButton:hover {{
    background: palette(midlight);
    border-color: palette(mid);
}}
QToolBar QToolButton:pressed {{
    background: palette(mid);
}}
QToolBar QToolButton:disabled {{
    color: palette(mid);
}}
QToolBar QLabel {{
    color: palette(mid);
    padding: 0 2px;
}}
QToolBar::separator {{
    background: palette(mid);
    width: 1px;
    margin: 6px 6px;
}}

QComboBox {{
    padding: 3px {SPACING}px;
    border: 1px solid palette(mid);
    border-radius: 4px;
    background: palette(base);
    min-height: 20px;
}}
QComboBox:hover {{
    border-color: palette(highlight);
}}
QComboBox:disabled {{
    color: palette(mid);
    background: palette(window);
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    border: 1px solid palette(mid);
    selection-background-color: palette(highlight);
    outline: none;
}}

QPushButton {{
    padding: 5px {SPACING + 4}px;
    border: 1px solid palette(mid);
    border-radius: 4px;
    background: palette(button);
}}
QPushButton:hover {{
    background: palette(midlight);
}}
QPushButton:pressed {{
    background: palette(mid);
}}

/* _titled()'s section header (graph_widget.py) - objectName-scoped so
this doesn't also restyle every other QLabel (crosshair readout, math
dock stat labels, etc). Left padding matches SignalTreeWidget/
MathDockWidget/LogPanel's content margins - see each __init__. */
QLabel#sectionHeader {{
    font-weight: 600;
    padding: {SPACING - 2}px {SPACING}px;
    background: palette(button);
    border-bottom: 1px solid palette(mid);
}}

QSplitter::handle {{
    background: palette(mid);
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

QCheckBox {{
    spacing: 6px;
}}
"""
