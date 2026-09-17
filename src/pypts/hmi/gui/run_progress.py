# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
RunProgress: the small green bar at the right end of the recipe label row.

GUI only - nothing is sent and CORE knows nothing of it (gui.md §15). The total
comes from the `SequenceSummary` the step table is filled from; the progress
from the `StepFinished` events the table already receives.

**What counts is a step that does work**, wherever it sits: a step of the
sequence itself, a step of any sequence it calls, and the teardown steps. A
`Sequence` call row (`is_group`) does not count - it finishes only after
every step inside it, so it would add a tick that stands for nothing new.

**Every verdict counts**, SKIP and STOP included. The engine sends one
`StepFinished` per row even for a row it never ran, so the bar reaches the end
of every run, a stopped one too.
"""

from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from pypts.messages.common_messages import StepOutcome
from pypts.messages.run_events import SequenceSummary

#: The bar's size, in pixels. Small: it is a glance, not a panel.
_BAR_WIDTH = 180
_BAR_HEIGHT = 8


def progress_text(done: int, total: int) -> str:
    """What the label beside the bar says: `6 / 15 (40 %)`, rounded down."""
    percent = 0
    if total > 0:
        percent = done * 100 // total
    return f"{done} / {total} ({percent} %)"


class RunProgress(QWidget):
    """The bar and its label. Hidden until a sequence with steps is shown."""

    def __init__(self) -> None:
        super().__init__()
        self.bar = QProgressBar()
        self.bar.setObjectName("runProgressBar")
        # The label beside it says the numbers; Qt's own text inside an 8 px
        # bar would be unreadable.
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(_BAR_WIDTH, _BAR_HEIGHT)

        self.label = QLabel()
        self.label.setObjectName("runProgressLabel")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.bar, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignVCenter)

        #: The ids of the rows that count, from the sequence on show.
        self._counted: set[UUID] = set()
        #: The counted rows that have finished. A set, so an event seen twice
        #: is still one step.
        self._finished: set[UUID] = set()
        self.setVisible(False)

    def show_sequence(self, sequence: SequenceSummary) -> None:
        """A sequence was put on the table: count its steps, start from empty."""
        self._counted = set()
        for step in sequence.steps:
            if not step.is_group:
                self._counted.add(step.step_id)
        self.reset()

    def reset(self) -> None:
        """Back to empty - a run is starting on the sequence already shown."""
        self._finished = set()
        self._refresh()

    def step_finished(self, outcome: StepOutcome) -> None:
        """One tick, if the row is one that counts."""
        if outcome.step_id in self._counted:
            self._finished.add(outcome.step_id)
            self._refresh()

    def _refresh(self) -> None:
        total = len(self._counted)
        done = len(self._finished)
        # A range of 0..0 turns a QProgressBar into a busy indicator, so a
        # sequence with nothing to count shows no bar at all.
        self.setVisible(total > 0)
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.label.setText(progress_text(done, total))
