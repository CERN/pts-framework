"""
RunRecord: what the Summary tab says about the last run (gui.md §14). No Qt.

GUI only - nothing is sent and CORE knows nothing of it. It is fed the events
the window already receives, and keeps its own copy of everything it shows, so
the summary of a run outlives a reload of its recipe: only an unload or the
next run replaces it.

**What counts** is what the step card and `RunProgress` count: a step that does
work, not a `Sequence` call row (`is_group`). The group rows are known from the
`RecipeLoaded` the run started under.

**Times** are the GUI's own, from when the events arrive (`time.monotonic()`),
as on the step card - they can differ from the report's `duration_s` by the
time a message takes. The start is also kept as a wall-clock time to show.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pypts.hmi.gui.run_display import COUNT_ORDER
from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.core_hmi_communication import ReportReady
from pypts.messages.run_events import RecipeLoaded, RunStarted

#: How many of the slowest steps the summary lists.
SLOWEST_COUNT = 5

#: The verdicts a pass rate is taken over: the steps that were judged.
JUDGED = (ResultType.PASS, ResultType.FAIL, ResultType.ERROR)

#: The verdicts listed as failures.
FAILED = (ResultType.FAIL, ResultType.ERROR)

#: What the Report names the CSV while the run is on, and keeps when the
#: rename at the end fails (report.py `LIVE_CSV_NAME`).
_LIVE_CSV_NAME = "report.csv"


@dataclass
class StepTime:
    """One step and how long it took, for the slowest-steps list."""

    step_id: UUID
    step_name: str
    seconds: float


@dataclass
class RunRecord:
    """One run, from its RunStarted on."""

    recipe_name: str
    recipe_version: str
    #: The sequence the GUI asked to run; "" when it did not start this run.
    sequence_name: str
    pypts_version: str
    #: False for an engineering-mode retest: no run folder, no report.
    write_report: bool
    started_wall: datetime
    started_at: float
    run_dir: str = ""
    run_log_path: str = ""
    finished_at: float | None = None
    #: None while the run is on.
    result: ResultType | None = None
    report_path: str = ""
    report_dir: str = ""
    #: The recipe's report_metadata globals, in the order they arrived.
    metadata: dict[str, str] = field(default_factory=dict)
    #: The steps that did work, in the order they finished.
    outcomes: list[StepOutcome] = field(default_factory=list)
    #: Group rows (Sequence steps) of the recipe the run started under.
    group_ids: frozenset[UUID] = frozenset()
    _step_starts: dict[UUID, float] = field(default_factory=dict)
    _durations: dict[UUID, float] = field(default_factory=dict)

    # --- Building it ------------------------------------------------------------

    @classmethod
    def start(
        cls,
        event: RunStarted,
        sequence_name: str,
        recipe: RecipeLoaded | None,
        now: float,
        wall: datetime,
    ) -> "RunRecord":
        """A new run's record. `recipe` is the one loaded, for its group rows."""
        group_ids = set()
        recipe_version = event.recipe_version
        if recipe is not None:
            for sequence in recipe.sequences:
                for step in sequence.steps:
                    if step.is_group:
                        group_ids.add(step.step_id)
            if not recipe_version:
                recipe_version = recipe.recipe_version
        return cls(
            recipe_name=event.recipe_name,
            recipe_version=recipe_version,
            sequence_name=sequence_name,
            pypts_version=event.pypts_version,
            write_report=event.write_report,
            started_wall=wall,
            started_at=now,
            run_dir=event.run_dir,
            run_log_path=event.run_log_path,
            group_ids=frozenset(group_ids),
        )

    def step_started(self, step_id: UUID, now: float) -> None:
        self._step_starts[step_id] = now

    def step_finished(self, outcome: StepOutcome, now: float) -> None:
        if outcome.step_id in self.group_ids:
            return
        self.outcomes.append(outcome)
        started = self._step_starts.pop(outcome.step_id, None)
        if started is not None:
            self._durations[outcome.step_id] = now - started

    def finish(self, result: ResultType, outcomes: tuple[StepOutcome, ...], now: float) -> None:
        """
        The run is over. RunFinished's outcomes are the whole record, so they
        replace the ones collected step by step - which a lost event would leave short.
        """
        self.result = result
        self.finished_at = now
        self.outcomes = [outcome for outcome in outcomes if outcome.step_id not in self.group_ids]

    def set_metadata(self, values: tuple[tuple[str, str], ...]) -> None:
        for name, value in values:
            self.metadata[name] = value

    def report_ready(self, event: ReportReady) -> None:
        self.report_path = event.report_path
        self.report_dir = event.report_dir

    # --- What it says -----------------------------------------------------------

    def duration(self, now: float) -> float:
        """Seconds from the start to the end, or to `now` while the run is on."""
        if self.finished_at is None:
            return now - self.started_at
        return self.finished_at - self.started_at

    def counts(self) -> dict[ResultType, int]:
        counts: dict[ResultType, int] = {}
        for outcome in self.outcomes:
            counts[outcome.result] = counts.get(outcome.result, 0) + 1
        return counts

    def counts_text(self) -> str:
        """"3 PASS · 1 FAIL", in COUNT_ORDER; "" before the first step ends."""
        counts = self.counts()
        parts = []
        for result_type in COUNT_ORDER:
            if counts.get(result_type, 0):
                parts.append(f"{counts[result_type]} {result_type.name}")
        return " · ".join(parts)

    def pass_rate_text(self) -> str:
        """
        "92 % passed (12 of 13 judged steps)" - PASS over PASS, FAIL and ERROR;
        DONE, SKIP and STOP judged nothing. "" when no step was judged.
        """
        counts = self.counts()
        judged = 0
        for result_type in JUDGED:
            judged += counts.get(result_type, 0)
        if judged == 0:
            return ""
        passed = counts.get(ResultType.PASS, 0)
        percent = int(passed * 100 / judged)
        return f"{percent} % passed ({passed} of {judged} judged steps)"

    def failures(self) -> list[StepOutcome]:
        """The steps that ended FAIL or ERROR, in run order."""
        return [outcome for outcome in self.outcomes if outcome.result in FAILED]

    def slowest(self, count: int = SLOWEST_COUNT) -> list[StepTime]:
        """The `count` steps that took longest, longest first; only steps that were timed."""
        times = []
        for outcome in self.outcomes:
            seconds = self._durations.get(outcome.step_id)
            if seconds is not None:
                times.append(StepTime(outcome.step_id, outcome.step_name, seconds))
        times.sort(key=lambda step_time: step_time.seconds, reverse=True)
        return times[:count]

    def run_folder(self) -> str:
        """The run's folder: named at the start, or by the report."""
        if self.run_dir:
            return self.run_dir
        return self.report_dir

    def csv_path(self) -> str:
        """
        The run's CSV: next to the report, with its name - or report.csv when
        the Report could not rename it. "" when neither is on disk.
        """
        if self.report_path:
            named = Path(self.report_path).with_suffix(".csv")
            if named.is_file():
                return str(named)
        folder = self.run_folder()
        if folder:
            live = Path(folder) / _LIVE_CSV_NAME
            if live.is_file():
                return str(live)
        return ""

