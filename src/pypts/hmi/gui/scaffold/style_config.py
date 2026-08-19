# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The scaffold's two configuration dataclasses.

Ported from `pyrade_gui_scaffold` 1.3.0 `style_config.py` (see the package
docstring for provenance). One `BoxStyle` styles all four panels alike; the
`LayoutConfig` stretch factors set the panels' initial proportions, which the
operator can drag afterwards.
"""

import warnings
from dataclasses import dataclass


@dataclass
class BoxStyle:
    """Visual styling configuration for all panels."""

    border_color: str = "black"
    bg_color: str = "transparent"
    border_width: int = 2
    border_radius: int = 4
    margin: int = 10
    spacing: int = 1


@dataclass
class LayoutConfig:
    """Stretch factor configuration for the main window layout."""

    top_bar_stretch: int = 2
    left_sidebar_stretch: int = 1
    center_view_stretch: int = 6
    bottom_bar_stretch: int = 2
    right_column_stretch: int = 4
    middle_row_stretch: int = 8
    handle_width: int = 1
    #: Deprecated upstream in 1.3.0, kept so configs written against the
    #: template still load; use right_column_stretch.
    middle_right_stretch: int | None = None

    def __post_init__(self) -> None:
        if self.middle_right_stretch is not None:
            warnings.warn(
                "LayoutConfig.middle_right_stretch is deprecated; "
                "use right_column_stretch instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.right_column_stretch = self.middle_right_stretch
