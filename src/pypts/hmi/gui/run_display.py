# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
RunDisplay: what the right column's picture area shows during a run. No Qt.

GUI only - nothing is sent and CORE knows nothing of it (gui.md §18). It is fed
the events the window already receives and answers two questions:

  image_path   the picture to show now, or None for the logo
  the header's numbers: the current step, its start, the run's start, the
               verdict counts and the last failure

**The running stack.** `SequenceStarted` pushes the sequence's picture,
`StepStarted` the step's; their `...Finished` pop them. The picture shown is
the **innermost** one set, so a step's picture goes when the step ends, a step
with none shows its sequence's, and a step inside a called sequence with
neither shows the picture of the `Sequence` step that called it - which is
still running, because its `StepFinished` comes after its children's - and so
on outward. Nothing set anywhere: the logo.

A pop is matched by id or name, not blind: it removes the matching entry and
anything left above it, so a lost event cannot leave a stale picture on screen.

**What counts** is what `RunProgress` counts: a step that does work, not a
`Sequence` call row (`is_group`). Every verdict counts.

**Looking back at a step** (gui.md §19). Every step that starts is remembered
with the picture that was on screen for it - the innermost one, worked out as
above at the moment it started - its start and finish times and its outcome.
`review(step_id)` hands that back for a clicked row. It is recorded rather than
worked out from the recipe because a Sequence step runs its own copy of the
called sequence, and the rows do not say which sequence a group calls. A step
that has not run yet in this run has only its own picture to show.
"""

from dataclasses import dataclass
from uuid import UUID

from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import RecipeLoaded, StepSummary

#: The order the header lists its verdict counts in.
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
    #: time.monotonic() when it started - a step's, for the header.
    started_at: float = 0.0


#: Where a looked-back step is in the run.
REVIEW_PENDING = "pending"
REVIEW_RUNNING = "running"
REVIEW_FINISHED = "finished"


@dataclass
class _Seen:
    """One step as this run saw it."""

    #: The picture on screen while it ran; None when it was the logo.
    image_path: str | None
    started_at: float
    finished_at: float | None = None
    outcome: StepOutcome | None = None


@dataclass
class StepReview:
    """What the picture area shows for a step clicked during or after a run."""

    step: StepSummary
    #: REVIEW_PENDING, REVIEW_RUNNING or REVIEW_FINISHED.
    state: str
    #: The picture it had (or, pending, its own); None: the step's card.
    image_path: str | None
    #: None until it has finished.
    outcome: StepOutcome | None = None
    #: Seconds from its start to its finish; None until it has finished.
    duration: float | None = None


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
        #: Every step the current (or last) run started, by id.
        self._seen: dict[UUID, _Seen] = {}
        #: True from a run's start until the recipe changes: only then is
        #: there a run to look back at.
        self.has_run = False

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
        self._seen = {}
        self.has_run = False

    # --- the run ----------------------------------------------------------------

    def run_started(self, now: float) -> None:
        self._stack = []
        self.running = True
        self.has_run = True
        self.run_started_at = now
        self.counts = {}
        self.last_failure = ""
        self._seen = {}

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
        # What is on screen for it now that it is the innermost entry.
        self._seen[step_id] = _Seen(self.image_path, now)

    def step_finished(self, outcome: StepOutcome, now: float) -> None:
        self._pop(_STEP, outcome.step_id)
        seen = self._seen.get(outcome.step_id)
        if seen is None:
            # A row the engine never started (SKIP): nothing was on screen for it.
            seen = _Seen(None, now)
            self._seen[outcome.step_id] = seen
        seen.finished_at = now
        seen.outcome = outcome
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
        """The innermost picture set on the running stack; None: the logo."""
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

    def is_running_step(self, step_id: UUID) -> bool:
        """Whether `step_id` is the innermost running step - the live view already shows it."""
        step, _started_at = self.current_step()
        return step is not None and step.step_id == step_id

    def review(self, step_id: UUID) -> StepReview | None:
        """
        A step to look back at, or None: an unknown row, or no run since the
        recipe was loaded.
        """
        step = self._steps.get(step_id)
        if step is None or not self.has_run:
            return None
        seen = self._seen.get(step_id)
        if seen is None:
            return StepReview(step, REVIEW_PENDING, step.image_path)
        if seen.outcome is None or seen.finished_at is None:
            return StepReview(step, REVIEW_RUNNING, seen.image_path)
        duration = seen.finished_at - seen.started_at
        return StepReview(step, REVIEW_FINISHED, seen.image_path, seen.outcome, duration)

    def count_text(self) -> str:
        """"3 PASS · 1 FAIL", in COUNT_ORDER; "" before the first step ends."""
        parts = []
        for result_type in COUNT_ORDER:
            count = self.counts.get(result_type, 0)
            if count:
                parts.append(f"{count} {result_type.name}")
        return " · ".join(parts)
