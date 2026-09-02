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
  that imports neither is what keeps steps testable stand-alone. The three
  seams the engine needs are plain callables the Sequencer fills in:
  `emit` (progress events out), `should_stop` (abort flag in) and `ask` (a
  question out, the operator's answer back). A bare Runtime() defaults all
  three to no-ops, and *is* the fake context the step tests use.
- The class-level stop event meant one abort flag for every run the process
  would ever do. `should_stop` is per-instance, so it is per-run.
- The reporting metadata returns with the Report port (roadmap Phase 1
  step 4), stamped where it is known rather than carried everywhere.

What is left is exactly what steps communicate through: `globals`, one flat
dict for the whole run. It is the only scope. A per-sequence `locals` frame
existed and was dropped (2026-09-02): it was global in reach and merely
shorter-lived, which is a distinction a recipe author had to think about for
no gain. Anything narrower than the run is a step's own `inputs`/`outputs`.
"""

from collections.abc import Callable
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


class Runtime:
    """One variable scope plus the three seams to the Sequencer, nothing else."""

    def __init__(
        self,
        globals: dict[str, Any] | None = None,
        emit: Callable[[Any], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        ask: Callable[[Any], Any] | None = None,
        base_dir: str = "",
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

    # --- globals: one flat dict for the whole run -----------------------------

    def get_global(self, name: str) -> Any:
        return self.globals[name]

    def set_global(self, name: str, value: Any) -> None:
        self.globals[name] = value
