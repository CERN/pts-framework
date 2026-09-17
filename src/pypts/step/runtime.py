# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The execution context a step runs against.

The old Runtime (old_code/recipe.py) carried much more: the Qt thread that
hosted the event proxy, a class-level stop Event shared by every run in the
process, the event and report queues, and the reporting metadata (serial
number, pypts version, ...). None of that came along:

- Qt and the queues belong to the Sequencer and the frontends - a Runtime
  that imports neither is what keeps steps testable stand-alone. The five
  seams the engine needs are plain callables the Sequencer fills in:
  `emit` (progress events out), `should_stop` (abort flag in), `ask` (a
  question out, the operator's answer back), `hold_if_paused` (block before
  a main step while the operator's Pause holds the run) and
  `drop_pending_pause` (the main steps are over, so a Pause still waiting
  for a step to hold before has nothing left to hold). A bare Runtime()
  defaults all five to no-ops, and *is* the fake context the step tests use.
- The class-level stop event meant one abort flag for every run the process
  would ever do. `should_stop` is per-instance, so it is per-run.
- The reporting metadata returns with the Report port (roadmap Phase 1
  step 4), stamped where it is known rather than carried everywhere.

What is left is exactly what steps communicate through: `globals`, one flat
dict for the whole run. It is the only scope. A per-sequence `locals` frame
existed and was dropped (2026-09-02): it was global in reach and merely
shorter-lived, which is a distinction a recipe author had to think about for
no gain. Anything narrower than the run is a step's own `inputs`/`outputs`.

Beside the seams, four plain attributes say where the step lists are running,
because a sequence may call another (step/sequence_step.py): `group_path` and
`depth` (set by `entering()`), `in_teardown`, and `halt_reason`, which is how a
`continue_on_error: false` halt inside a called sequence ends the whole run.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


class PromptUnanswered(Exception):
    """
    Nobody answered a question put through `ask`: timed out, cancelled, or
    the run stopped.

    It lives here rather than on one step type because it belongs to the
    `ask` seam, which every step that blocks on a person shares.
    """


def _never_stop() -> bool:
    return False


def _discard(event: Any) -> None:
    pass


def _cannot_ask(request: Any) -> Any:
    """No engine behind this Runtime, so nobody can be asked. Declines."""
    return None


def _never_hold(step_name: str, position: int, total: int) -> None:
    """No engine behind this Runtime, so nobody can pause it."""


def _nothing_to_drop() -> None:
    """No engine behind this Runtime, so no pause can be pending."""


class Runtime:
    """One variable scope, the five seams to the Sequencer, and where the step lists run."""

    def __init__(
        self,
        globals: dict[str, Any] | None = None,
        emit: Callable[[Any], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        ask: Callable[[Any], Any] | None = None,
        base_dir: str = "",
        hold_if_paused: Callable[[str, int, int], None] | None = None,
        drop_pending_pause: Callable[[], None] | None = None,
    ) -> None:
        self.globals: dict[str, Any] = globals if globals is not None else {}
        #: The folder the recipe file came from - what a PythonModuleStep's
        #: relative `module:` path resolves against, so test code lives beside
        #: its recipe. Empty for a recipe parsed from text.
        self.base_dir = base_dir
        #: Where progress events go. The Sequencer passes its outbox's send();
        #: typed Any because a Callable[[SequencerToCore], None] would drag the
        #: link union in here and fail contravariance against the no-op default.
        self.emit: Callable[[Any], None] = emit if emit is not None else _discard
        #: Polled between steps. The Sequencer passes its stop_requested flag.
        if should_stop is None:
            should_stop = _never_stop
        self.should_stop: Callable[[], bool] = should_stop
        #: Put one request to the operator and block until it is answered;
        #: None means nobody answered. The Sequencer passes ask_operator(),
        #: which owns the register-before-send ordering so no step can get it
        #: wrong. Typed Any for the same reason as emit.
        #: MUST only be called from the sequence thread - see Sequencer.
        self.ask: Callable[[Any], Any] = ask if ask is not None else _cannot_ask
        #: Called by the step layer before each main step - never a teardown
        #: step, never a step that is only being recorded SKIP - with the
        #: step's name and its 1-based position among `total` main steps.
        #: Returns at once unless the operator paused the run; then it blocks
        #: until the hold ends, by Resume or by Stop. The Sequencer passes
        #: hold_if_paused(). MUST only be called from the sequence thread.
        if hold_if_paused is None:
            hold_if_paused = _never_hold
        self.hold_if_paused: Callable[[str, int, int], None] = hold_if_paused
        #: Called once when the main steps have ended, before teardown. A
        #: Pause that is still waiting for a step to hold before lapses here,
        #: because teardown is never held. The Sequencer passes
        #: drop_pending_pause().
        if drop_pending_pause is None:
            drop_pending_pause = _nothing_to_drop
        self.drop_pending_pause: Callable[[], None] = drop_pending_pause

        # --- where the step lists are running: plain state, not seams --------
        #: The sequence names from the run's first sequence down to the one
        #: running now, joined with "/": `Main/PowerCycle`. Empty outside any
        #: sequence. Set by entering(); rides on every StepExecuted.
        self.group_path = ""
        #: How deep the running sequence is called: 0 for the run's first
        #: sequence, 1 for a sequence it calls. Indents the operator's lines.
        self.depth = 0
        #: True while a teardown list runs, at any depth. A sequence called from
        #: teardown inherits it, so everything in it runs to the end.
        self.in_teardown = False
        #: Why the rest of the run is skipped after a `continue_on_error: false`
        #: step came back ERROR or FAIL; empty while nothing has halted. Shared
        #: by every step list of the run, so a halt inside a called sequence
        #: ends the whole run and not only the list it happened in.
        self.halt_reason = ""

    # --- globals: one flat dict for the whole run -----------------------------

    def get_global(self, name: str) -> Any:
        return self.globals[name]

    def set_global(self, name: str, value: Any) -> None:
        self.globals[name] = value

    # --- nesting ----------------------------------------------------------------

    @contextmanager
    def entering(self, sequence_name: str) -> Iterator[None]:
        """
        Run the block inside `sequence_name`: path extended, one level deeper.

        The first sequence of a run starts the path and stays at depth 0; a
        sequence entered inside another is one level deeper. Both are restored
        when the block ends, however it ends.
        """
        outer_path = self.group_path
        outer_depth = self.depth
        if outer_path:
            self.group_path = f"{outer_path}/{sequence_name}"
            self.depth = outer_depth + 1
        else:
            self.group_path = sequence_name
        try:
            yield
        finally:
            self.group_path = outer_path
            self.depth = outer_depth
