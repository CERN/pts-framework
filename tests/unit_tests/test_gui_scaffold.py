# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the vendored GUI scaffold (src/pypts/hmi/gui/scaffold/).

The scaffold is a PySide6 port of `pyrade_gui_scaffold` 1.3.0; these tests are
its upstream test suite, ported alongside it so the port stays honest - every
behaviour upstream pins (panel wiring, style forwarding, set_content
semantics, the deferred initial-sizing pass) is pinned here too.

Like the other GUI tests: needs a display or QT_QPA_PLATFORM=offscreen;
pytest-qt provides `qapp`.
"""

import warnings

import pytest

pytest.importorskip("PySide6", reason="the GUI is an optional extra")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter

from pypts.hmi.gui.scaffold.main_window import MainWindow
from pypts.hmi.gui.scaffold.panels import (
    BasePanel,
    BottomBar,
    CenterView,
    LeftSidebar,
    TopBar,
)
from pypts.hmi.gui.scaffold.style_config import BoxStyle, LayoutConfig

# --------------------------------------------------------------------------
# Style configuration
# --------------------------------------------------------------------------


def test_box_style_defaults():
    style = BoxStyle()
    assert style.border_color == "black"
    assert style.bg_color == "transparent"
    assert style.border_width == 2
    assert style.border_radius == 4
    assert style.margin == 10
    assert style.spacing == 1


def test_layout_config_defaults():
    layout = LayoutConfig()
    assert layout.top_bar_stretch == 2
    assert layout.left_sidebar_stretch == 1
    assert layout.center_view_stretch == 6
    assert layout.bottom_bar_stretch == 2
    assert layout.right_column_stretch == 4
    assert layout.middle_row_stretch == 8
    assert layout.handle_width == 1


def test_middle_right_stretch_is_a_deprecated_alias():
    """Upstream renamed it in 1.3.0; the alias still works but warns."""
    with pytest.warns(DeprecationWarning, match="middle_right_stretch"):
        layout = LayoutConfig(middle_right_stretch=7)
    assert layout.right_column_stretch == 7


def test_no_warning_when_the_alias_is_unused():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        LayoutConfig(right_column_stretch=5)


# --------------------------------------------------------------------------
# BasePanel
# --------------------------------------------------------------------------


@pytest.fixture
def style():
    return BoxStyle()


def test_panel_carries_its_object_name_and_style(qapp, style):
    panel = BasePanel("TestPanel", style)
    assert panel.objectName() == "TestPanel"
    sheet = panel.styleSheet()
    assert "#TestPanel" in sheet
    assert style.bg_color in sheet
    assert style.border_color in sheet


def test_panel_layout_margins_come_from_the_style(qapp, style):
    panel = BasePanel("TestPanel", style)
    margins = panel.box_layout.contentsMargins()
    assert margins.left() == style.margin
    assert margins.top() == style.margin
    assert margins.right() == style.margin
    assert margins.bottom() == style.margin


def test_set_content_holds_exactly_one_widget(qapp, style):
    """set_content is a hand-over, and it *deletes* what was there before -
    which is why page switching happens inside the content, never by calling
    it twice (see gui.md section 6)."""
    panel = BasePanel("TestPanel", style)
    panel.set_content(QLabel("First"))
    assert panel.box_layout.count() == 1
    panel.set_content(QLabel("Second"))
    assert panel.box_layout.count() == 1
    panel.set_content(None)
    assert panel.box_layout.count() == 0


@pytest.mark.parametrize(
    ("panel_class", "expected_name"),
    [
        (TopBar, "TopBar"),
        (LeftSidebar, "LeftSidebar"),
        (CenterView, "CenterView"),
        (BottomBar, "BottomBar"),
    ],
)
def test_each_concrete_panel_names_itself(qapp, style, panel_class, expected_name):
    panel = panel_class(style=style)
    assert panel.objectName() == expected_name
    panel.set_content(QLabel("Content"))
    assert panel.box_layout.count() == 1


# --------------------------------------------------------------------------
# MainWindow
# --------------------------------------------------------------------------


def test_window_defaults_and_customisation(qapp):
    window = MainWindow()
    assert window.windowTitle() == "App"
    custom = MainWindow(title="Test App", width=800, height=600)
    assert custom.windowTitle() == "Test App"
    assert custom.size().width() == 800
    assert custom.size().height() == 600


def test_the_four_panels_exist(qapp):
    window = MainWindow()
    assert isinstance(window.top_bar, TopBar)
    assert isinstance(window.left_sidebar, LeftSidebar)
    assert isinstance(window.center_view, CenterView)
    assert isinstance(window.bottom_bar, BottomBar)


def test_one_style_is_forwarded_to_every_panel(qapp):
    window = MainWindow(style=BoxStyle(bg_color="#abcdef"))
    assert "#abcdef" in window.top_bar.styleSheet()
    assert "#abcdef" in window.left_sidebar.styleSheet()
    assert "#abcdef" in window.center_view.styleSheet()
    assert "#abcdef" in window.bottom_bar.styleSheet()


def test_splitters_are_wired_and_central(qapp):
    window = MainWindow()
    assert isinstance(window.outer_splitter, QSplitter)
    assert isinstance(window.middle_splitter, QSplitter)
    assert isinstance(window.right_splitter, QSplitter)
    assert window.outer_splitter.orientation() == Qt.Orientation.Vertical
    assert window.middle_splitter.orientation() == Qt.Orientation.Horizontal
    assert window.right_splitter.orientation() == Qt.Orientation.Vertical
    assert window.centralWidget() is window.outer_splitter


def test_handle_width_is_configurable(qapp):
    window = MainWindow(layout=LayoutConfig(handle_width=7))
    assert window.outer_splitter.handleWidth() == 7
    assert window.middle_splitter.handleWidth() == 7
    assert window.right_splitter.handleWidth() == 7


def test_stretch_factors_match_the_layout_config(qapp):
    window = MainWindow()
    # QSplitter.setStretchFactor mutates the child's QSizePolicy stretch;
    # there is no getter on the splitter itself, so read it off the policy.
    assert window.outer_splitter.widget(0).sizePolicy().verticalStretch() == 2
    assert window.outer_splitter.widget(1).sizePolicy().verticalStretch() == 8
    assert window.middle_splitter.widget(0).sizePolicy().horizontalStretch() == 1
    assert window.middle_splitter.widget(1).sizePolicy().horizontalStretch() == 4
    assert window.right_splitter.widget(0).sizePolicy().verticalStretch() == 6
    assert window.right_splitter.widget(1).sizePolicy().verticalStretch() == 2


def test_initial_splitter_ratios_follow_the_config(qapp):
    """The deferred QTimer.singleShot(0, ...) sizing pass must actually run,
    or the panels open at their sizeHint floors instead of the configured
    proportions."""
    window = MainWindow(width=1000, height=700)
    window.show()
    qapp.processEvents()  # let the deferred sizing pass fire

    middle = window.middle_splitter.sizes()
    assert sum(middle) > 0
    assert abs(middle[0] / sum(middle) - 1 / 5) < 0.05

    right = window.right_splitter.sizes()
    assert sum(right) > 0
    assert abs(right[0] / sum(right) - 6 / 8) < 0.05

    outer = window.outer_splitter.sizes()
    assert sum(outer) > 0
    assert abs(outer[0] / sum(outer) - 2 / 10) < 0.05

    window.close()
