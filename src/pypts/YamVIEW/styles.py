# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pypts.gui_theme import get_theme_colors, get_yamview_stylesheet


dark_style = get_yamview_stylesheet(True)
light_style = get_yamview_stylesheet(False)


def get_editor_theme_colors(dark: bool) -> dict[str, str]:
    return get_theme_colors(dark)
