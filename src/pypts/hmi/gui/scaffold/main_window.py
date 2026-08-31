# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The scaffold's main window: four panels joined by draggable splitters.

Ported from `pyrade_gui_scaffold` 1.3.0 `main_window.py` (see the package
docstring for provenance).

Layout structure (every joint is a draggable QSplitter handle):

    TopBar          full width, top
    LeftSidebar     left column
    CenterView      right column, upper
    BottomBar       right column, lower
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QMainWindow, QSplitter

from pypts.hmi.gui.scaffold.panels import BottomBar, CenterView, LeftSidebar, TopBar
from pypts.hmi.gui.scaffold.style_config import BoxStyle, LayoutConfig


class MainWindow(QMainWindow):
    """The four-panel window. Content is plugged into the panels, not here."""

    def __init__(
        self,
        title: str = "App",
        width: int = 1000,
        height: int = 700,
        style: BoxStyle | None = None,
        layout: LayoutConfig | None = None,
    ) -> None:
        super().__init__()
        # Upstream used mutable dataclass defaults in the signature; fresh
        # instances per window is the same behaviour without the shared state.
        if style is None:
            style = BoxStyle()
        if layout is None:
            layout = LayoutConfig()

        self.setWindowTitle(title)
        self.resize(width, height)
        self._layout_cfg = layout
        self._initial_sizes_applied = False

        # Panels
        self.top_bar = TopBar(style=style)
        self.left_sidebar = LeftSidebar(style=style)
        self.center_view = CenterView(style=style)
        self.bottom_bar = BottomBar(style=style)

        # Right column: CenterView over BottomBar
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.addWidget(self.center_view)
        self.right_splitter.addWidget(self.bottom_bar)

        # Middle row: LeftSidebar beside the right column
        self.middle_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.middle_splitter.addWidget(self.left_sidebar)
        self.middle_splitter.addWidget(self.right_splitter)

        # Outer: TopBar above the middle row
        self.outer_splitter = QSplitter(Qt.Orientation.Vertical)
        self.outer_splitter.addWidget(self.top_bar)
        self.outer_splitter.addWidget(self.middle_splitter)

        for splitter in (self.outer_splitter, self.middle_splitter, self.right_splitter):
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(layout.handle_width)

        # Stretch factors govern how *resize* space is distributed; the
        # initial proportions are applied after the first paint, below.
        self.outer_splitter.setStretchFactor(0, layout.top_bar_stretch)
        self.outer_splitter.setStretchFactor(1, layout.middle_row_stretch)
        self.middle_splitter.setStretchFactor(0, layout.left_sidebar_stretch)
        self.middle_splitter.setStretchFactor(1, layout.right_column_stretch)
        self.right_splitter.setStretchFactor(0, layout.center_view_stretch)
        self.right_splitter.setStretchFactor(1, layout.bottom_bar_stretch)

        self.setCentralWidget(self.outer_splitter)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt virtual
        """Schedule initial sizing after first paint, so size() reflects real geometry."""
        super().showEvent(event)
        if self._initial_sizes_applied:
            return
        self._initial_sizes_applied = True
        QTimer.singleShot(0, self._apply_initial_sizes)

    def _apply_initial_sizes(self) -> None:
        """Override sizeHint-driven floors with the configured stretch ratios."""
        cfg = self._layout_cfg

        def split(total: int, first_share: int, second_share: int) -> list[int]:
            denominator = first_share + second_share or 1
            first = total * first_share // denominator
            return [first, total - first]

        outer_total = self.outer_splitter.size().height()
        self.outer_splitter.setSizes(
            split(outer_total, cfg.top_bar_stretch, cfg.middle_row_stretch)
        )

        middle_total = self.middle_splitter.size().width()
        self.middle_splitter.setSizes(
            split(middle_total, cfg.left_sidebar_stretch, cfg.right_column_stretch)
        )

        right_total = self.right_splitter.size().height()
        self.right_splitter.setSizes(
            split(right_total, cfg.center_view_stretch, cfg.bottom_bar_stretch)
        )
