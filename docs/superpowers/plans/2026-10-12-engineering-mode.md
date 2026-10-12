# Engineering Mode (GUI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit → Engineering Mode in the GUI gives the engineer two tools on the step table:
1. **Quick retest** — click / ctrl-click / shift-click rows to highlight them, press **Space**: only
   those steps run; every other row comes back SKIP. **No report, no run folder**; the run is
   logged in the session log.
2. **Leave steps out** — a tick box in each name cell; unticked rows are greyed. **Start** runs
   normally and **writes the report**; the unticked steps come back SKIP.

**Architecture:** The recipe stays in CORE. The GUI already knows every row's step UUID
(`RecipeLoaded` → `StepSummary.step_id`). It sends `StartSequence` with two new fields —
`excluded_step_ids` and `write_report` — which CORE copies into `RunSequence`. The Sequencer puts
the exclusions on the `Runtime`; `Step.run_steps()` gives each excluded step a skip reason, so the
existing SKIP path settles its row and (when there is a report) writes its CSV row. With
`write_report=False` the Sequencer makes no run folder and no run log, and says so on `RunStarted`;
CORE then routes nothing of that run to the Report.

**Tech Stack:** Python 3.11, PySide6, pytest.

**Spec:** conversation of 2026-10-12. Decisions taken by the user:
1. A step that reads a global a skipped step would have set simply ERRORs — no warning.
2. **Every** row can be left out, teardown rows included — no special care for teardown.
3. Picking one step inside a called sequence runs **that step only**: the Sequence row is entered,
   every other row inside it (its teardown included) is SKIP. Selecting / unticking a group row
   acts on all its children.
4. Quick retest (Space): **no report**; the full log, in the **session log, no run folder**.
   Leave-steps-out (Start): an ordinary run **with** the report.
5. Menu: **Edit → Engineering Mode**, checkable.
6. **GUI only.** CLI, headless and `Pts` are untouched (they keep the defaults).
7. In engineering mode a click **selects**; the YAML click panel is **off** until the mode is off.
8. The tick box lives **inside the name cell** (Qt check state) — no new column.
9. Lifetime: **session only**. Selection and ticks are cleared on recipe load / unload, on
   switching the displayed sequence, and when the mode is switched off. Nothing goes to config.

Decisions taken in this plan (flag in review if wrong):
- A **group row's name click selects** in engineering mode; folding moves to double-click and the
  right-click Expand all / Collapse all (both already exist).
- Space and the tick boxes are **inert during a run**, like Start. The selection survives the run,
  so Space can be pressed again to repeat the retest.
- Space with an empty selection does nothing (DEBUG line).
- A highlighted row that is also unticked does **not** run on Space (unticked always wins).
- The selection highlight is painted per cell like today's click highlight (Name + Description
  only), so the Result chips keep their colours. It needs one new palette colour.
- A permanent status-bar label "ENGINEERING MODE" while the mode is on — a safety cue that a run
  may be partial.

## Global Constraints

- No commits, no staging (user commits).
- HMI↔CORE stays pickle-safe: the new fields are `tuple[UUID, ...]` and `bool`.
- Every handler `match` stays closed with `unhandled()`.
- `%`-style logging; INFO for the technician, DEBUG for developers (`logger/logging_rules.md`).
- `CONFIG_VERSION` unchanged — nothing is added to config.
- Documentation moves with the code (CLAUDE.md): routing change ⇒ `core/core.md` **and**
  `messages/messages.md`.
- Keep each file's line endings (repo is `eol=lf`).

## The skip reason

One constant in `step/step.py`:

```python
#: The reason an engineering-mode exclusion is recorded with.
LEFT_OUT_REASON = "Not run: left out in engineering mode."
```

---

## Task 1 — Messages carry the exclusions

**Files:** `messages/core_hmi_communication.py`, `messages/core_sequencer_communication.py`,
`messages/run_events.py`, `tests/unit_tests/test_messages.py`

- [ ] `StartSequence`: add `excluded_step_ids: tuple[UUID, ...] = ()` and `write_report: bool = True`.
  Docstring: the GUI's engineering mode is the only sender of non-defaults.
- [ ] `RunSequence`: the same two fields, same defaults.
- [ ] `RunStarted`: add `write_report: bool = True` — the Sequencer's word on whether this run has
  a report, which CORE routes on (see Task 4: CORE must not route on what it *asked*, because the
  Sequencer may refuse the run).
- [ ] `test_messages.py`: the new fields round-trip through pickle; defaults unchanged.

## Task 2 — The step layer skips excluded steps

**Files:** `step/runtime.py`, `step/step.py`, `tests/unit_tests/test_step.py`

- [ ] `Runtime.__init__` takes `excluded_step_ids: frozenset[UUID] = frozenset()` and stores it.
- [ ] `Step.run_steps()`: the list-wide `skip_reason` stays sticky as today. Add a **per-step**
  reason: `step_skip = skip_reason`; if empty and `step.id in runtime.excluded_step_ids`,
  `step_skip = LEFT_OUT_REASON`. Use `step_skip` for the hold check, the "started" line,
  the DEBUG line and `step.run(..., skip_reason=step_skip)`. An exclusion **does not** end the
  list and **does** apply inside `run_to_end` (teardown) lists. No hold before an excluded step.
- [ ] A Sequence step that is excluded goes through the existing `_skip_contents()` path, so its
  children settle SKIP too (whether or not they are listed).
- [ ] Docstring of `run_steps()`: add the exclusion bullet.
- [ ] Tests (`test_step.py`): excluded step is SKIP with `LEFT_OUT_REASON` and the next step runs;
  excluded teardown step is SKIP while the others run; excluded Sequence step settles every child;
  a Sequence step that is **not** excluded but has excluded children runs only the kept ones;
  no excluded set ⇒ behaviour unchanged.

## Task 3 — The Sequencer honours them

**Files:** `sequencer/sequencer.py`, `tests/unit_tests/test_sequencer.py`

- [ ] `case RunSequence(...)`: also take `excluded_step_ids`, `write_report`; pass them to
  `run_sequence()` → `execute_sequence()`.
- [ ] `execute_sequence()`: `Runtime(..., excluded_step_ids=frozenset(excluded_step_ids))`.
- [ ] `write_report=False`: do **not** call `start_run_folder()`; `run_dir = run_log_path = ""`
  (the existing `if run_log_path:` already skips `end_run_log()`). `RunStarted(write_report=...)`.
- [ ] Operator line at the run's start, when anything is excluded (INFO, wording to check against
  `logging_rules.md`):
  `Engineering run: %d of %d steps left out.` and, when `write_report` is False, one more INFO
  `Engineering run: no report and no run folder; this run is in the session log.`
- [ ] Tests: `write_report=False` makes no folder and sends `RunStarted(run_dir="", run_log_path="",
  write_report=False)`; exclusions reach the Runtime (a two-step recipe, one excluded → SKIP).

## Task 4 — CORE forwards, and keeps a no-report run away from the Report

**Files:** `core/core.py`, `tests/unit_tests/test_core.py`

- [ ] `handle_hmi_message`: `case StartSequence(...)` passes both fields; `start_sequence()` puts
  them on `RunSequence`. DEBUG line names the count of exclusions and `write_report`.
- [ ] New `self.run_has_report: bool = True`. Set it from `RunStarted.write_report` when that
  arrives; reset it to True on `RunFinished` after routing.
- [ ] `handle_sequencer_message`: while `run_has_report` is False, `RunStarted`, `SequenceStarted`,
  `RunMetadata`, `StepExecuted` and `RunFinished` are **not** sent to the Report and no
  `GenerateReport` follows `RunFinished`. The HMI still gets everything it gets today.
  `StepExecuted` with no report is dropped with no log line per step (one DEBUG line at
  `RunStarted` says the run has no report).
- [ ] Tests: a `RunStarted(write_report=False)` … `RunFinished` sequence reaches the HMI and
  nothing reaches the Report; the next ordinary run reaches the Report again.

## Task 5 — The shared client

**Files:** `hmi/hmi_client.py`, `tests/unit_tests/test_hmi_client.py`

- [ ] `start_sequence(sequence_name, excluded_step_ids=(), write_report=True)` sends both.
  CLI callers untouched.
- [ ] Test: the fields land on the `StartSequence` sent.

## Task 6 — The step table: selection and tick boxes

**Files:** `hmi/gui/step_table.py`, `hmi/gui/palette.py`, `tests/unit_tests/test_hmi_gui.py`

- [ ] Palette: one new colour per theme for the selection highlight (distinct from
  `header_background`, which the click panel uses).
- [ ] `set_engineering_mode(on: bool)`: on — every name cell becomes `ItemIsUserCheckable`,
  `Checked`; the YAML panel is closed. Off — check state removed from every name cell (the box
  disappears), grey and selection cleared.
- [ ] **Selection.** Own set of selected rows, painted per cell (Name + Description), not Qt's
  selection (which would tint the chips — see the existing comment). In `_clicked_cell`, while in
  engineering mode and not running: read `QApplication.keyboardModifiers()` — plain click =
  only this row, Ctrl = toggle this row, Shift = range from the last plain/ctrl click. Clicking a
  group row (any column) selects/deselects it **and all its children**. Return before the panel
  code. Double-click on a group row folds (name column included, in engineering mode only).
- [ ] **Tick boxes.** `itemChanged` on a name cell: unticking a group unticks its children;
  ticking a child ticks its ancestors; signals blocked while cascading. Unticked rows' Name and
  Description get the palette's muted foreground; ticked rows get it removed.
- [ ] Locked during a run: `set_running(True)` removes `ItemIsUserCheckable` (state kept) and
  selection clicks are ignored; `set_running(False)` restores.
- [ ] Two queries, both returning `tuple[UUID, ...]` in row order:
  - `retest_exclusions()` — every row **not** to run for Space: a leaf runs when it is selected
    and ticked; a group runs when any row under it runs; everything else is excluded. Empty
    selection ⇒ `None` (nothing to run).
  - `left_out_exclusions()` — every unticked row.
- [ ] `show_sequence()` and `clear()` drop selection and ticks; when the mode is on,
  `show_sequence()` gives the new rows their tick boxes.
- [ ] `set_dark()`: repaint the selection highlight and grey in the new theme (unlike the click
  panel, the selection outlives a theme switch).
- [ ] Tests (`test_hmi_gui.py`, offscreen): plain/ctrl/shift selection; group selection takes its
  children; `retest_exclusions()` for a nested recipe (child selected ⇒ group runs, siblings
  excluded); unticking a group unticks children; ticking a child ticks the group; mode off clears
  everything; clicks ignored while running; YAML panel not opened in engineering mode.

## Task 7 — The window: menu, Space, Start, status

**Files:** `hmi/gui/gui.py`, `tests/unit_tests/test_hmi_gui.py`

- [ ] `_build_menu()`: `self.engineering_action = edit_menu.addAction("Engineering Mode")`,
  checkable, with a tooltip, placed above the Settings separator. Toggled → `step_table.set_engineering_mode()`,
  status-bar label shown/hidden, INFO `Engineering mode switched on.` / `... off.`
- [ ] Space: a `QShortcut(Qt.Key.Key_Space, step_table)` with
  `WidgetWithChildrenShortcut` context — so Space typed in the interaction panel's text fields
  is never taken. Handler: engineering mode on, recipe loaded, no run, `retest_exclusions()` not
  None ⇒ `self.start_sequence(name, exclusions, write_report=False)`; otherwise a DEBUG line.
- [ ] Start (`_start_or_resume`, start branch): in engineering mode pass
  `left_out_exclusions()` with `write_report=True`. Outside it, unchanged.
- [ ] Recipe loaded / unloaded and switching sequence already rebuild or clear the table — check
  the ticks and selection are cleared through that path (Task 6) and nothing else is needed.
- [ ] `show_run_started` / `show_run_finished` already call `step_table.set_running()` — verify
  the lock and unlock happen through them.
- [ ] Tests: the action toggles the table mode and the label; Space sends `StartSequence` with
  `write_report=False` and the right exclusions; Start in engineering mode sends the unticked
  set with `write_report=True`; Space outside engineering mode sends nothing.

## Task 8 — Documentation

- [ ] `step/step.md` — `excluded_step_ids` on the Runtime, `LEFT_OUT_REASON`, the per-step rule
  in `run_steps()`.
- [ ] `sequencer/sequencer.md` — the two `RunSequence` fields; no folder/run log when
  `write_report` is False; the two INFO lines.
- [ ] `core/core.md` — `start_sequence()` forwarding, `run_has_report`, the routing table rows
  for a no-report run.
- [ ] `messages/messages.md` — the new fields on `StartSequence`, `RunSequence`, `RunStarted`.
- [ ] `hmi/hmi.md` — `start_sequence()` signature.
- [ ] `hmi/gui/gui.md` — a new section: Engineering Mode (menu, selection, Space, tick boxes,
  locks, lifetime, YAML panel off, group click/fold change, status label).
- [ ] `logger/logging_rules.md` — only if the new INFO lines are fixed phrases there.
- [ ] `usage_manual.html` — Engineering Mode for the user: how to switch on, Space retest
  (no report, session log), unticking (report written, SKIP rows with the reason).
- [ ] `pypts_implementation_status.html` — move 1.59 from *planned* to *done*, with verification
  and any TODOs it opened.

## Task 9 — Gates

- [ ] `pytest tests`, `ruff check src tests`, `mypy` — all green.
- [ ] Manual GUI check (`python run_pypts.py`) with the all-steptypes demo recipe: retest two rows
  including one inside a called sequence; untick a group and run with Start; confirm the report
  folder appears only for the Start run and the session log holds the retest.
- [ ] Documentation check: re-read every document above against the final code.
