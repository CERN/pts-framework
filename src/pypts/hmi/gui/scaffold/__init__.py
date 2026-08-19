# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The vendored GUI scaffold: the four-panel main-window layout the PTS GUI
builds on.

A PySide6 port of `pyrade_gui_scaffold` 1.3.0 by Anders Vesterholm-Lavesen
(https://gitlab.cern.ch/rade/rade-core/utils/gui_template), vendored rather
than depended on for two reasons recorded in gui.md section 6: upstream is
PyQt6, whose GPL licensing is exactly what the PySide6 migration removed from
this project, and vendoring keeps the framework free of the dependency.
TODO(roadmap): upstream ships no license file - clearance from its author is
being sought; until then this port stays attribution-plus-TODO.

The port is faithful: same class names, same public API (`MainWindow`,
`BoxStyle`, `LayoutConfig`, `panel.set_content(widget)`), same behaviour,
upstream's test suite ported beside it (tests/unit_tests/test_gui_scaffold.py).
The only structural change is packaging taste: upstream's five single-class
component files are one `panels.py` here.

    main_window.py   MainWindow - the nested-splitter four-panel layout
    panels.py        BasePanel + TopBar / LeftSidebar / CenterView / BottomBar
    style_config.py  BoxStyle, LayoutConfig

The scaffold owns the layout; the content is plugged in with one
`set_content()` call per panel - and only one: `set_content()` *deletes* the
previous widget, so page switching happens inside the content widget (a
QStackedWidget), never by calling it again. See gui.md for how the PTS GUI
maps onto the four regions.
"""

from pypts.hmi.gui.scaffold.main_window import MainWindow
from pypts.hmi.gui.scaffold.style_config import BoxStyle, LayoutConfig

__all__ = ["BoxStyle", "LayoutConfig", "MainWindow"]
