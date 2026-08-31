# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The scaffold's panels: one shared base, four named regions.

Ported from `pyrade_gui_scaffold` 1.3.0 (see the package docstring for
provenance); upstream keeps each class in a file of its own, this port keeps
the five of them together because none is more than a name.

A panel is an empty styled box until `set_content()` hands it a widget. The
four subclasses exist so the regions are distinct types with distinct object
names - which is what the per-panel stylesheet selector hangs on, and what
lets a test assert it got the panel it asked for.
"""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from pypts.hmi.gui.scaffold.style_config import BoxStyle


class BasePanel(QFrame):
    """
    Shared base for all panel components: visual styling, layout setup, and
    pluggable content via set_content().
    """

    def __init__(self, object_name: str, style: BoxStyle, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # The selector targets this panel's object name, so each panel styles
        # itself without leaking rules onto its children.
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"""
            #{object_name} {{
                background-color: {style.bg_color};
                border: {style.border_width}px solid {style.border_color};
                border-radius: {style.border_radius}px;
            }}
            """
        )

        self.box_layout = QVBoxLayout(self)
        margin = style.margin
        self.box_layout.setContentsMargins(margin, margin, margin, margin)
        self.box_layout.setSpacing(style.spacing)

    def set_content(self, widget: QWidget | None) -> None:
        """
        Replace the panel's content with the given widget.

        **The previous content is deleted**, not detached - so this is the
        one-time hand-over at assembly, never a page switcher. A panel whose
        content has pages holds them in its own QStackedWidget.
        """
        while self.box_layout.count():
            item = self.box_layout.takeAt(0)
            old_widget = item.widget()
            if old_widget:
                old_widget.deleteLater()

        if widget:
            self.box_layout.addWidget(widget)


class TopBar(BasePanel):
    """Full-width bar along the top of the main window."""

    def __init__(self, style: BoxStyle, parent: QWidget | None = None) -> None:
        super().__init__("TopBar", style, parent)


class LeftSidebar(BasePanel):
    """Vertical sidebar along the left side of the main window."""

    def __init__(self, style: BoxStyle, parent: QWidget | None = None) -> None:
        super().__init__("LeftSidebar", style, parent)


class CenterView(BasePanel):
    """Main content area, occupying the upper-right region of the window."""

    def __init__(self, style: BoxStyle, parent: QWidget | None = None) -> None:
        super().__init__("CenterView", style, parent)


class BottomBar(BasePanel):
    """Narrow bar along the bottom of the right-side content area."""

    def __init__(self, style: BoxStyle, parent: QWidget | None = None) -> None:
        super().__init__("BottomBar", style, parent)
