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
  that imports neither is what keeps steps testable stand-alone. The two
  seams the engine needs are plain callables the Sequencer fills in:
  `emit` (progress events out) and `should_stop` (abort flag in). A bare
  Runtime() defaults both to no-ops, and *is* the fake context the step
  tests use.
- The class-level stop event meant one abort flag for every run the process
  would ever do. `should_stop` is per-instance, so it is per-run.
- The reporting metadata returns with the Report port (roadmap Phase 1
  step 4), stamped where it is known rather than carried everywhere.

What is left is exactly what steps communicate through: the two variable
scopes. `globals` is one flat dict for the whole recipe; locals live on a
stack with one dict per running sequence, and only the top frame is ever
read or written - a subsequence cannot see its caller's locals.
"""

from collections.abc import Callable
from typing import Any


def _never_stop() -> bool:
    return False


def _discard(event: Any) -> None:
    pass


class Runtime:
    """Variable scopes plus the two seams to the Sequencer, nothing else."""

    def __init__(
        self,
        globals: dict[str, Any] | None = None,
        emit: Callable[[Any], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        base_dir: str = "",
    ) -> None:
        self.globals: dict[str, Any] = globals if globals is not None else {}
        #: The folder the recipe file came from - what a PythonModuleStep's
        #: relative `module:` path resolves against, so test code lives beside
        #: its recipe. Empty for a recipe parsed from text.
        self.base_dir = base_dir
        self.local_stack: list[dict[str, Any]] = []
        #: Where progress events go. The Sequencer passes its outbox's send();
        #: typed Any because a Callable[[SequencerToCore], None] would drag the
        #: link union in here and fail contravariance against the no-op default.
        self.emit: Callable[[Any], None] = emit if emit is not None else _discard
        #: Polled between steps. The Sequencer passes its stop_requested flag.
        if should_stop is None:
            should_stop = _never_stop
        self.should_stop: Callable[[], bool] = should_stop

    # --- locals: one frame per running sequence, top frame only ---------------

    def push_locals(self, locals: dict[str, Any]) -> None:
        self.local_stack.append(locals)

    def pop_locals(self) -> dict[str, Any]:
        return self.local_stack.pop()

    def get_local(self, name: str) -> Any:
        return self.local_stack[-1][name]

    def set_local(self, name: str, value: Any) -> None:
        self.local_stack[-1][name] = value

    # --- globals: one flat dict for the whole recipe --------------------------

    def get_global(self, name: str) -> Any:
        return self.globals[name]

    def set_global(self, name: str, value: Any) -> None:
        self.globals[name] = value
