# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
RunDisplay: what the right column's picture area shows during a run. No Qt.

GUI only - nothing is sent and CORE knows nothing of it (gui.md §18). It is fed
the events the window already receives and answers two questions:

  image_path   the picture to show now, or None for the run card
  the run card's numbers: the current step, its start, the run's start, the
               verdict counts and the last failure

**The running stack.** `SequenceStarted` pushes the sequence's picture,
`StepStarted` the step's; their `...Finished` pop them. The picture shown is
the **innermost** one set, so a step's picture goes when the step ends, a step
with none shows its sequence's, and a step inside a called sequence with
neither shows the picture of the `Sequence` step that called it - which is
still running, because its `StepFinished` comes after its children's - and so
on outward. Nothing set anywhere: the run card.

A pop is matched by id or name, not blind: it removes the matching entry and
anything left above it, so a lost event cannot leave a stale picture on screen.

**What counts** is what `RunProgress` counts: a step that does work, not a
`Sequence` call row (`is_group`). Every verdict counts.
"""

from dataclasses import dataclass
from uuid import UUID

from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import RecipeLoaded, StepSummary

#: The order the run card lists its verdict counts in.
COUNT_ORDER = (
    ResultType.PASS,
    ResultType.FAIL,
    ResultType.ERROR,
    ResultType.DONE,
    ResultType.SKIP,
    ResultType.STOP,
)

_SEQUENCE = "sequence"
_STEP = "step"


@dataclass
class _Running:
    """One entry of the running stack."""

    kind: str
    #: The step's UUID, or the sequence's lowercased name.
    key: UUID | str
    image_path: str | None
    #: The step's row, None for a sequence.
    step: StepSummary | None = None
    #: time.monotonic() when it started - a step's, for the run card.
    started_at: float = 0.0


class RunDisplay:
    """The right column's state during a run, from the events alone."""

    def __init__(self) -> None:
        self._steps: dict[UUID, StepSummary] = {}
        self._sequence_images: dict[str, str | None] = {}
        self._stack: list[_Running] = []
        self.running = False
        self.run_started_at = 0.0
        self.counts: dict[ResultType, int] = {}
        #: The name of the latest step that ended FAIL or ERROR, "" for none.
        self.last_failure = ""

    # --- the recipe -------------------------------------------------------------

    def set_recipe(self, recipe: RecipeLoaded | None) -> None:
        """Index every row and every sequence picture; None forgets them."""
        self._steps = {}
        self._sequence_images = {}
        if recipe is not None:
            for sequence in recipe.sequences:
                # Names are unique regardless of case, and a called sequence's
                # SequenceStarted carries the same name as its own document.
                self._sequence_images[sequence.sequence_name.lower()] = sequence.image_path
                for step in sequence.steps:
                    self._steps[step.step_id] = step
        self.run_finished()

    # --- the run ----------------------------------------------------------------

    def run_started(self, now: float) -> None:
        self._stack = []
        self.running = True
        self.run_started_at = now
        self.counts = {}
        self.last_failure = ""

    def run_finished(self) -> None:
        self._stack = []
        self.running = False

    def sequence_started(self, sequence_name: str) -> None:
        key = sequence_name.lower()
        self._stack.append(_Running(_SEQUENCE, key, self._sequence_images.get(key)))

    def sequence_finished(self, sequence_name: str) -> None:
        self._pop(_SEQUENCE, sequence_name.lower())

    def step_started(self, step_id: UUID, now: float) -> None:
        step = self._steps.get(step_id)
        image_path = None
        if step is not None:
            image_path = step.image_path
        self._stack.append(_Running(_STEP, step_id, image_path, step, now))

    def step_finished(self, outcome: StepOutcome) -> None:
        self._pop(_STEP, outcome.step_id)
        step = self._steps.get(outcome.step_id)
        if step is None or step.is_group:
            return
        self.counts[outcome.result] = self.counts.get(outcome.result, 0) + 1
        if outcome.result in (ResultType.FAIL, ResultType.ERROR):
            self.last_failure = outcome.step_name

    def _pop(self, kind: str, key: UUID | str) -> None:
        """Remove the innermost matching entry and anything still above it."""
        for index in range(len(self._stack) - 1, -1, -1):
            entry = self._stack[index]
            if entry.kind == kind and entry.key == key:
                del self._stack[index:]
                return

    # --- what to show -----------------------------------------------------------

    @property
    def image_path(self) -> str | None:
        """The innermost picture set on the running stack; None: the run card."""
        for entry in reversed(self._stack):
            if entry.image_path:
                return entry.image_path
        return None

    def current_step(self) -> tuple[StepSummary | None, float]:
        """The innermost running step and when it started; (None, 0.0) between steps."""
        for entry in reversed(self._stack):
            if entry.kind == _STEP:
                return entry.step, entry.started_at
        return None, 0.0

    def count_text(self) -> str:
        """"3 PASS · 1 FAIL", in COUNT_ORDER; "" before the first step ends."""
        parts = []
        for result_type in COUNT_ORDER:
            count = self.counts.get(result_type, 0)
            if count:
                parts.append(f"{count} {result_type.name}")
        return " · ".join(parts)
