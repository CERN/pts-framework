# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
ViewTabBar: the Run | Results tabs above the left pane.

A plain QTabBar, plus one thing a stylesheet cannot do: make a single tab pulse.
When a run ends with results the operator has not looked at, the Results tab
takes the selected-tab background and breathes slowly to a darker blue and
back until the tab is opened (gui.md §14).
"""

from PySide6.QtCore import QEasingCurve, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QTabBar

from pypts.hmi.gui.palette import get_palette

TAB_RUN = 0
TAB_RESULTS = 1

#: One fade in and out, in milliseconds. Slow on purpose: it is a reminder,
#: not an alarm.
PULSE_PERIOD_MS = 2400

#: The tab's box as styles.py draws it: `border-radius: 4px 4px 0 0`,
#: `margin-right: 2px`. The pulse paints under a tab, so it has to know the
#: shape it fills.
_TAB_RADIUS = 4
_TAB_MARGIN_RIGHT = 2


class ViewTabBar(QTabBar):
    """The two tabs. The assembler connects `currentChanged` to the left stack."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.addTab("Run")
        self.addTab("Results")

        self._dark = False
        #: The tab that is pulsing, or None.
        self._pulsing_tab: int | None = None
        #: How far the pulse is from the base colour to the dark one: 0.0 to 1.0.
        self._pulse_level = 0.0

        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setKeyValueAt(0.5, 1.0)
        self._pulse.setEndValue(0.0)
        self._pulse.setDuration(PULSE_PERIOD_MS)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse_value)

        # Opening the pulsing tab is what it asks for, so that ends it.
        self.currentChanged.connect(self._on_current_changed)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def pulsing_tab(self) -> int | None:
        return self._pulsing_tab

    def start_pulse(self, index: int) -> None:
        """Pulse a tab until it is opened. A tab already open does not pulse."""
        if index == self.currentIndex():
            return
        self._pulsing_tab = index
        self._pulse.start()

    def stop_pulse(self) -> None:
        """Stop pulsing. Safe to call when nothing pulses."""
        self._pulse.stop()
        self._pulsing_tab = None
        self._pulse_level = 0.0
        self.update()

    def _on_current_changed(self, index: int) -> None:
        if index == self._pulsing_tab:
            self.stop_pulse()

    def _on_pulse_value(self, value: float) -> None:
        self._pulse_level = value
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt virtual
        """
        The pulse paints under one tab; the stylesheet then paints the tabs.

        Only the background pulses: the selected-tab background, blended
        towards `tab_pulse_background` by the pulse's level. An unselected tab
        has no background of its own, so the fill shows through and the label
        stays as the stylesheet draws it - one label, not a second one fading
        in on top.
        """
        if self._pulsing_tab is not None:
            palette = get_palette(self._dark)
            rect = self.tabRect(self._pulsing_tab).adjusted(0, 0, -_TAB_MARGIN_RIGHT, 0)
            base = QColor(palette.tab_selected_background)
            peak = QColor(palette.tab_pulse_background)
            level = self._pulse_level
            background = QColor.fromRgbF(
                base.redF() + (peak.redF() - base.redF()) * level,
                base.greenF() + (peak.greenF() - base.greenF()) * level,
                base.blueF() + (peak.blueF() - base.blueF()) * level,
            )

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Rounded on top only: round all four corners, and cut the bottom two off.
            painter.setClipRect(rect)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(
                QRect(rect).adjusted(0, 0, 0, _TAB_RADIUS), _TAB_RADIUS, _TAB_RADIUS
            )
            painter.end()

        super().paintEvent(event)
