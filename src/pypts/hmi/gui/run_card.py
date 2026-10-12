# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
RunCard: what the picture area shows during a run when no picture applies.

It draws a RunDisplay - the state is there, this is only the view (gui.md §18):
the step running now and what it does, how long the run and the step have
taken, the verdicts so far and the last step that failed. The clocks tick
once a second while the card is running; time spent paused is not taken off.
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pypts.hmi.gui.palette import get_palette
from pypts.hmi.gui.run_display import RunDisplay

#: What the card says above the step name.
HEADING = "NOW RUNNING"

#: Shown in place of a step name between steps.
NO_STEP = "-"


def elapsed_text(seconds: float) -> str:
    """`4:07`, or `1:02:07` from an hour on. Negative counts as zero."""
    total = int(max(seconds, 0))
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{rest:02d}"
    return f"{minutes}:{rest:02d}"


class RunCard(QWidget):
    """The run card. refresh() redraws it from the RunDisplay it was given."""

    def __init__(self, display: RunDisplay) -> None:
        super().__init__()
        self._display = display
        self._dark = False

        self.heading_label = QLabel(HEADING)
        self.step_label = QLabel(NO_STEP)
        self.step_label.setWordWrap(True)
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.elapsed_label = QLabel()
        self.counts_label = QLabel()
        self.counts_label.setWordWrap(True)
        self.last_failure_label = QLabel()
        self.last_failure_label.setWordWrap(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        column.addStretch()
        for label in (
            self.heading_label,
            self.step_label,
            self.description_label,
            self.elapsed_label,
            self.counts_label,
            self.last_failure_label,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
        column.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.set_dark(False)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        palette = get_palette(dark)
        self.heading_label.setStyleSheet(
            f"font-size:11px; font-weight:600; color:{palette.section_label};"
        )
        self.step_label.setStyleSheet(f"font-size:16px; font-weight:600; color:{palette.text};")
        self.description_label.setStyleSheet(f"font-size:12px; color:{palette.text_muted};")
        self.elapsed_label.setStyleSheet(f"font-size:13px; color:{palette.text};")
        self.counts_label.setStyleSheet(f"font-size:13px; color:{palette.text};")
        failed = palette.verdicts["FAIL"]
        self.last_failure_label.setStyleSheet(
            f"font-size:12px; color:{failed.text}; background-color:{failed.background};"
            "border-radius:4px; padding:2px 8px;"
        )

    def start(self) -> None:
        """Draw now and tick once a second."""
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def is_ticking(self) -> bool:
        return self._timer.isActive()

    def refresh(self) -> None:
        display = self._display
        now = time.monotonic()
        step, step_started_at = display.current_step()
        if step is None:
            self.step_label.setText(NO_STEP)
            self.description_label.setText("")
            elapsed = f"Run {elapsed_text(now - display.run_started_at)}"
        else:
            self.step_label.setText(step.step_name)
            self.description_label.setText(step.description)
            elapsed = (
                f"Run {elapsed_text(now - display.run_started_at)}"
                f"  ·  Step {elapsed_text(now - step_started_at)}"
            )
        self.description_label.setVisible(bool(self.description_label.text()))
        self.elapsed_label.setText(elapsed)
        self.counts_label.setText(display.count_text())
        self.counts_label.setVisible(bool(display.count_text()))
        if display.last_failure:
            self.last_failure_label.setText(f"Last failure: {display.last_failure}")
            self.last_failure_label.setVisible(True)
        else:
            self.last_failure_label.setText("")
            self.last_failure_label.setVisible(False)
