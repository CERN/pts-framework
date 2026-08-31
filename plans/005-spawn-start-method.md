# Plan 005: The launcher pins multiprocessing to "spawn" on every platform

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 800db1c..HEAD -- src/pypts/launcher/startup.py tests/unit_tests/test_startup.py`
> (Plan 003 is expected to have touched `test_startup.py` — that is not
> drift.) If `startup.py` changed, compare the excerpts below first.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED — Linux behavior change that cannot be fully verified on the
  Windows dev machine; see STOP conditions and the verification note.
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `800db1c`, 2026-08-21

## Why this matters

On Linux, `multiprocessing` defaults to `fork`. The launcher can create a live
`QApplication` **in its own process** before it forks the Logger, Core and GUI
children: `ConfigHandler.bootstrap()` runs first, and on the `CREATED` (first
run on a machine) or `DISCARDED` (broken config) outcomes,
`show_config_popup()` → `_open_message_box()` does `QApplication([])` and
`box.exec()` in the launcher. Forking a process that holds an initialized Qt
and a display connection is unsupported by Qt — children can abort or hang on
the duplicated connection. The trigger paths are exactly the first-ever run on
a new bench and every run with a broken config: the runs a new Linux machine
hits first, misdiagnosed as config problems. On Windows this is invisible
because Windows always spawns.

Decision (maintainer, 2026-08-21): fix it structurally — pin the start method
to `"spawn"` in `main()` — rather than only moving the popup. That kills the
whole fork-hazard class and makes Linux behave like Windows, where all current
testing happens. Cost: slower child startup on Linux (interpreter boot + module
re-import per child), accepted. There are no deployed benches yet, so the
behavior change is free.

Why this is safe by construction: **Windows already runs spawn**, and the whole
framework works there — every `Process` target (`logger_main`, `core_main`,
`gui_main`) and every argument passed to them (`QueueWrapper`-wrapped
`multiprocessing.Queue`s, plain values) is already proven picklable-and-
importable under spawn semantics. `src/pypts/__main__.py` is properly
`if __name__ == "__main__"` guarded:

```python
from pypts.launcher import startup

if __name__ == "__main__":
    startup.main()
```

## Current state

- `src/pypts/launcher/startup.py` — the launcher. Imports at lines 34–56
  include `from multiprocessing import Process, Queue` (line 39). `main()`
  starts at line 78; its first statements are argparse setup, then
  `config = ConfigHandler.bootstrap()` at line 117, the popup branches at
  119–137, the first `Queue()` at line 143, and the three `Process(...)`
  creations at lines 154, 195, 203.
- The popup implementation (`startup.py:246-259`):

  ```python
  def _open_message_box(title: str, text: str, *, warning: bool) -> None:
      """One modal QMessageBox. Separate so tests can make it fail on purpose."""
      from PySide6.QtWidgets import QApplication, QMessageBox

      if QApplication.instance() is None:
          QApplication([])
      ...
  ```

  This stays **unchanged** — under spawn, children no longer inherit it.

- Key ordering fact: `Queue()` objects are created from the *default context*
  at call time, so the start method must be pinned **before the first
  `Queue()` is created** (line 143). The top of `main()` is the right place.

Repo conventions: `%`-style logging (not relevant here — no logging exists yet
at the insertion point, which is why the code comment carries the reasoning
instead); plain readable Python; decisions recorded in the roadmap.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `.venv\Scripts\python.exe -m pytest tests -q` | all pass, exit 0 |
| Lint | `.venv\Scripts\python.exe -m ruff check src tests` | no NEW findings |
| Typecheck | `.venv\Scripts\python.exe -m mypy` | `Success: no issues found` |
| Smoke run (manual) | `.venv\Scripts\python.exe -m pypts --mode cli --no-debug-monitor` then type `exit` | banner/prompt appears; exits cleanly; last log lines include `All modules stopped cleanly` |

If pytest errors with `PermissionError ... pytest-of-Dzbanan`, add
`--basetemp=C:\Git\pts-framework\.pytest-tmp` (disposable, do not commit).

## Scope

**In scope** (the only files you should modify):

- `src/pypts/launcher/startup.py`
- `tests/unit_tests/test_startup.py` (one small test)
- `resources/roadmap/pypts_roadmap.md` (one entry, Step 3)
- `plans/README.md` (your status row)

**Out of scope** (do NOT touch):

- `_open_message_box` / `show_config_popup` — correct once spawn is pinned.
- `src/pypts/__main__.py` — already correctly guarded.
- Anything under `src/pypts/core`, `hmi`, `logger` — child entry points are
  already spawn-proven on Windows.

## Git workflow

- Branch off `architecture_refactor`: `advisor/005-spawn-start-method`.
- Commit style: short lowercase summary. One commit.
- Do NOT push or open an MR unless the operator instructed it.

## Steps

### Step 1: Pin the start method at the top of `main()`

In `startup.py`:

1. Extend the multiprocessing import (line 39):

   ```python
   from multiprocessing import Process, Queue, get_start_method, set_start_method
   ```

2. Insert as the **first statements of `main()`** (before the argparse block):

   ```python
   # Children are always spawned, never forked - on every platform. Two
   # reasons. The bootstrap notice below can create a QApplication in this
   # process, and forking a process that holds live Qt state is unsupported
   # (children can abort or hang on the duplicated display connection). And
   # Windows - where all development runs - always spawns, so pinning spawn
   # makes Linux exercise the same code paths instead of quietly different
   # ones. Must happen before the first Queue() below: queues are built from
   # the default context at call time.
   if get_start_method(allow_none=True) != "spawn":
       set_start_method("spawn")
   ```

   The guard makes a second in-process call to `main()` (or an embedding
   caller that already pinned spawn) a no-op instead of a `RuntimeError`.

**Verify**: `.venv\Scripts\python.exe -m ruff check src/pypts/launcher/startup.py`
→ no findings; `.venv\Scripts\python.exe -m mypy` → clean.

### Step 2: One test that the pin is in place and idempotent

In `tests/unit_tests/test_startup.py` — a direct test of the guard, without
running `main()` (which would spawn real processes):

`test_main_pins_the_spawn_start_method_before_building_anything(monkeypatch)`:

- Monkeypatch `startup.get_start_method` to return `"fork"` and
  `startup.set_start_method` to record its calls into a list.
- Monkeypatch `startup.ConfigHandler.bootstrap` to raise a sentinel exception
  (e.g. `class Abort(Exception)`) so `main()` stops right after the pin,
  before any argparse-dependent or process-spawning code matters — and
  monkeypatch `sys.argv` to `["pypts"]` so argparse sees no stray pytest args.
- Call `startup.main()` inside `pytest.raises(Abort)`.
- Assert the recorded calls equal `[("spawn",)]` (or `["spawn"]` depending on
  how you record).
- Second half: monkeypatch `startup.get_start_method` to return `"spawn"` and
  repeat; assert `set_start_method` was **not** called (idempotence).

Note: argparse runs after the pin in Step 1's placement, and
`ConfigHandler.bootstrap` is called after argparse — so the sentinel fires
after the pin and after argparse. Keep the `sys.argv` monkeypatch so argparse
parses cleanly.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_startup.py -q`
→ all pass including the new test.

### Step 3: Record the decision in the roadmap

In `resources/roadmap/pypts_roadmap.md`, in the section
"## TODO — Agreed architecture change: two processes, threads inside the
engine", append to the "### TODO checklist" list:

```
- [x] **DONE (plans/005):** the launcher pins `set_start_method("spawn")` on
      every platform, first thing in `main()`. Closes the Linux fork hazard
      (the bootstrap notice can create a QApplication in the launcher before
      the children exist), and makes Linux exercise the same spawn semantics
      Windows always had. Cost accepted: slower child startup on Linux.
      Linux end-to-end run still owed - see the verification note in the plan.
```

**Verify**: `git diff --stat` → exactly the four in-scope files modified.

### Step 4: Manual smoke run on Windows

Run the smoke command from the table (`--mode cli --no-debug-monitor`, type
`exit`). Windows was already spawn, so this confirms the guard itself did not
disturb startup.

**Verify**: clean exit; the newest log file in the configured logs dir ends
with the Logger stopping after `All modules stopped cleanly`.

## Test plan

Step 2's unit test (pin present + idempotent). The behavioral proof on Linux
is explicitly deferred — see Maintenance notes.

## Done criteria

ALL must hold:

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` exits 0
- [ ] `.venv\Scripts\python.exe -m ruff check src tests` — no NEW findings
- [ ] `.venv\Scripts\python.exe -m mypy` → `Success: no issues found`
- [ ] `grep -n "set_start_method" src/pypts/launcher/startup.py` shows the
      guarded call at the top of `main()`
- [ ] Manual smoke run (Step 4) exits cleanly
- [ ] `git status` shows only the four in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `main()`'s opening does not match the description (drift since `800db1c`).
- The smoke run hangs or a child process fails to start after the change on
  Windows — the guard should be a no-op there; a behavior change on Windows
  means something unexpected (e.g. an import started a context earlier).
- You are tempted to use `set_start_method("spawn", force=True)` — the
  `force` flag papers over a context someone else already fixed, which is
  exactly the situation that should be reported instead.

## Maintenance notes

- **Linux verification is still owed.** No CI job runs the launcher end-to-end
  (the functional suite is all placeholders), so the first Linux
  `python -m pypts --mode cli --no-debug-monitor` after this change should be
  watched: expect slower startup (spawn re-imports per child) and confirm all
  processes come up and exit 0. The roadmap entry from Step 3 says this owed
  check out loud.
- Under spawn on Linux, any future code that passes a `Process` target or
  argument that is not picklable/importable will now fail on Linux the same
  way it always failed on Windows — that is the point; reviewers of future
  launcher changes should know fork is no longer there to hide it.
- The known roadmap question "why does reaching `main_loop` take seconds"
  (§1.4 TODO) may read slightly worse on Linux after this change (spawn is
  slower than fork). If startup time becomes a complaint, the recorded
  monitor-before-core ordering finding in `plans/README.md`
  (considered-and-not-planned) is the first cheap win.
