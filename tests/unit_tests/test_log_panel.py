"""
Unit tests for the LOG OUTPUT panel's filter and worst-level icon
(src/pypts/hmi/gui/log_panel.py, and its header row in center_view.py).

The lines are the panel's display format (`log_tail.format_record()`): level
first, padded to nine characters.
"""

import pytest

pytest.importorskip("PySide6", reason="the GUI is an optional extra")

INFO = "INFO     12:00:00  Recipe loaded."
WARNING = "WARNING  12:00:01  The DMM answered late."
ERROR = "ERROR    12:00:02  The step failed."
CRITICAL = "CRITICAL 12:00:03  Shutting down."
TRACEBACK = "Traceback (most recent call last):"


@pytest.fixture
def panel(qapp):
    from pypts.hmi.gui.log_panel import LogPanel

    return LogPanel()


@pytest.fixture
def center(qapp):
    from pypts.hmi.gui.center_view import CenterContent

    return CenterContent()


def shown_lines(panel):
    return panel.toPlainText().splitlines()


def test_every_group_is_shown_to_start_with(panel):
    for line in (INFO, WARNING, ERROR):
        panel.append_line(line)

    assert shown_lines(panel) == [INFO, WARNING, ERROR]


def test_hiding_a_group_hides_the_lines_already_shown_and_the_new_ones(panel):
    panel.append_line(INFO)
    panel.append_line(WARNING)

    panel.set_group_shown("INFO", False)
    panel.append_line("INFO     12:00:05  Another one.")

    assert shown_lines(panel) == [WARNING]


def test_showing_a_group_again_brings_its_lines_back_in_order(panel):
    panel.set_group_shown("INFO", False)
    for line in (INFO, WARNING, ERROR):
        panel.append_line(line)

    panel.set_group_shown("INFO", True)

    assert shown_lines(panel) == [INFO, WARNING, ERROR]


def test_critical_goes_with_error(panel):
    panel.append_line(CRITICAL)
    panel.set_group_shown("ERROR", False)

    assert shown_lines(panel) == []


def test_a_continuation_line_goes_with_its_record(panel):
    panel.append_line(ERROR)
    panel.append_line(TRACEBACK)
    panel.append_line(INFO)

    panel.set_group_shown("ERROR", False)

    assert shown_lines(panel) == [INFO]


def test_a_line_with_no_record_above_it_is_always_shown(panel):
    panel.set_group_shown("INFO", False)
    panel.set_group_shown("WARNING", False)
    panel.set_group_shown("ERROR", False)

    panel.append_line("No run log to follow.")

    assert shown_lines(panel) == ["No run log to follow."]


def test_the_worst_level_is_the_most_severe_seen(panel):
    seen = []
    panel.worst_level_changed.connect(seen.append)

    panel.append_line(INFO)
    assert panel.worst_level == ""
    panel.append_line(WARNING)
    panel.append_line(ERROR)
    panel.append_line(WARNING)

    assert panel.worst_level == "ERROR"
    assert seen == ["WARNING", "ERROR"]


def test_a_hidden_error_still_counts(panel):
    panel.set_group_shown("ERROR", False)

    panel.append_line(ERROR)

    assert panel.worst_level == "ERROR"


def test_clearing_forgets_the_worst_level_but_keeps_the_filter(panel):
    seen = []
    panel.worst_level_changed.connect(seen.append)
    panel.set_group_shown("INFO", False)
    panel.append_line(WARNING)

    panel.clear()

    assert panel.worst_level == ""
    assert seen == ["WARNING", ""]
    assert panel.is_group_shown("INFO") is False


def test_the_icon_appears_with_a_warning_and_goes_with_a_clear(center):
    icon = center.log_alert_icon
    assert icon.isHidden()

    center.log_panel.append_line(WARNING)
    assert not icon.isHidden()
    assert "warning" in icon.toolTip()

    center.log_panel.append_line(ERROR)
    assert "error" in icon.toolTip()

    center.log_panel.clear()
    assert icon.isHidden()


def test_a_button_click_filters_and_says_so(center):
    said = []
    center.log_filter_changed.connect(lambda group, shown: said.append((group, shown)))
    center.log_panel.append_line(INFO)

    center.log_filter_buttons["INFO"].click()

    assert said == [("INFO", False)]
    assert center.log_panel.toPlainText() == ""


def test_set_log_filter_does_not_say_so(center):
    said = []
    center.log_filter_changed.connect(lambda group, shown: said.append((group, shown)))

    center.set_log_filter({"WARNING": False})

    assert said == []
    assert center.log_filter_buttons["WARNING"].isChecked() is False
    assert center.log_panel.is_group_shown("WARNING") is False


def test_long_lines_wrap_instead_of_scrolling_sideways(panel):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPlainTextEdit

    assert panel.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
    assert panel.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
