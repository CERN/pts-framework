<!-- SPDX-FileCopyrightText: 2025 CERN <home.cern> -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Porting changes — the August 2026 engine + GUI session

A condensed tracking file for the burst of porting work done on
`architecture_refactor` in mid-August 2026, and — its most important half —
the **findings backlog** from the review that closed the session. The roadmap
(`pypts_roadmap.md`) stays the single source of truth for status and plan;
this file is the session's index into it, plus the review results that are
recorded nowhere else. Update it the way the roadmap is updated: when a
finding below is fixed or a decision is taken, flip it here in the same
change.

---

## 1. What was built (chronological; details in the roadmap section named)

| Increment | Roadmap | What works now |
|---|---|---|
| Engine skeleton | §1.13 | `recipe/` pure data layer (loud `RecipeError`s), `step/` (base `Step` lifecycle, `StepResult`, `Runtime`, registry replacing `eval()`, `WaitStep`), `Sequencer.execute_sequence()` real, `Core.load_recipe()` real, `UseRecipe` live-object handoff. F3/F11/F12/F16 fixed by construction; F6 last-wins kept deliberately. End-to-end: `wait_recipe.yml` runs in the CLI |
| GUI groundwork | §1.14 | Old GUI (868 lines + proxy + command loop) studied and written up in `src/pypts/hmi/gui/gui.md`; `pyrade_gui_scaffold` 1.3.0 vendored as a **PySide6 port** in `hmi/gui/scaffold/` (upstream is PyQt6/unlicensed — clearance TODO still open). The framework references the upstream repo nowhere |
| Operator GUI + protocol | §1.15 | Four-panel screen: top bar (Open/sequence dropdown/Start/Stop, event-driven states), UUID-keyed step table with the old verdict colors, CenterView stack (logo idle / prompt / serial pages, exactly-once answer guard), status line. `StopSequence` rides HmiToCore + CoreToSequencer; `RecipeLoaded` carries the full summary (`StepSummary`/`SequenceSummary`, teardown rows included); window [X] = shutdown handshake; CLI `stop_sequence` verb. Forced light mode (`force_light_mode()`) |
| PythonModuleStep, minimal | §1.16 | `action_type: method` only; `module:` = file beside the recipe (`Recipe.base_dir` → `Runtime.base_dir`) or dotted import. Demo: `resources/recipes/pythonmodulestep_demo.yml` + `example_tests.py` — PASS/PASS/FAIL(on purpose)/PASS → `Run finished: FAIL` |

Suite growth over the session: 248 passed / 69 skipped → **350 passed / 51
skipped**; `ruff` and `mypy` clean throughout; every increment verified
end-to-end in the CLI on Windows.

## 2. Review findings (code review agent, verified by execution) — OPEN

Severity order. None fixed yet; the split proposed was: fix 1–3 now (engine),
4–5 now (GUI), and record the parity gaps below.

- [ ] **R-1 (critical)** `process_outputs()` sits outside `run()`'s except
      (`step/step.py` `else:` branch): a judging failure (output key missing,
      unknown output type, non-numeric `range`) escapes the step — no
      `StepFinished` (GUI row stuck on "Running..."), no `SequenceFinished`,
      `RunFinished(ERROR)` with zero outcomes, blamed on the Sequencer. Test
      blind spot: judging tests never go through `run()`.
- [ ] **R-2 (critical)** `PythonModuleStep` re-executes the user's module on
      **every step** (`load_python_module` per `_step()`, no cache): the old
      engine imported once per process, so module-level state persisted.
      Also writes `__pycache__` beside the operator's recipes.
- [ ] **R-3 (important)** Non-`RecipeError` load failures escape
      `Core.load_recipe` into the poll catch-all — operator sees *nothing*.
      Triggers: empty `steps:`/`globals:`/`locals:` (None), `steptype: 5`,
      scalar step entries. Needs type validation in `from_document` +
      defensive `except Exception` → `report_own_error` in CORE.
- [ ] **R-4 (important)** A dead/wedged CORE makes the GUI window
      unclosable: `allow_close` is only ever set by the `StopHmi` handshake.
      Needs the bounded-grace fallback the CLI already has
      (`wait_until_stopped`).
- [ ] **R-5 (important)** `LoadRecipe` mid-run swaps the recipe under the
      running sequence and repaints the table with new step ids (rest of the
      run's events miss their rows). Reachable from the CLI. CORE should
      refuse it while a run is in flight.
- [ ] **R-6 (trivial)** stray "-1" typo at the end of a `startup.py`
      docstring line (in the uncommitted `--no-debug-monitor` edit).

Checked and clean: prompt exactly-once gate under Qt re-entrancy,
HMI-boundary pickle safety, heartbeat shutdown, re-run isolation. One noted
future gap: `GUI.on_stop()` does not `center.cancel_pending()` — harmless
until something sends prompts.

## 3. Functional parity gaps vs old_code (parity audit agent) — OPEN

The audit produced a full capability matrix; most capabilities are ported or
deferred-with-a-recorded-TODO. These nine were **missing with no document
tracking them** (now tracked here):

- [ ] **M-1** `UserPromptRequest.options: tuple[str, ...]` collapsed the old
      response-key ≠ button-caption pair (`- 'yes': 'Press me'`; empty
      caption → `key.capitalize()`; no options → one unlabelled button).
      Baked into a pickled frozen dataclass — **decide the shape before the
      `User*` step port**, later is a protocol change.
- [ ] **M-2** The embedding API is gone (`run_recipe_app`/`run_pts`/`PtsApi`):
      no supported way to drive the engine from another Python program.
- [ ] **M-2b** No scripted/non-interactive path: no `--recipe` autoload, no
      "load X, run Y, exit with a code" for CI/headless benches (roadmap
      Phase 1 §5 gestures at CLI features but does not record this loss).
- [ ] **M-3** Per-step **inputs/outputs no longer reach any frontend** —
      `StepOutcome` has no field for them; the old result tree showed every
      measured value. The operator's only view of measurements is gone.
- [ ] **M-4** The report's TDMS discovery + FFT/time-domain matplotlib plots
      embedded in HTML are absent from every Report TODO.
- [ ] **M-5** Abort no longer produces per-step **STOP** results: old code
      marked the interrupted and every un-run step STOP (table grayed, CSV
      rows); new code just stops emitting — remaining rows stay "Pending"
      unexplained. Worth doing with the Report port.
- [ ] **M-5b** Window title no longer becomes "PTS: <recipe>" (matters with
      several benches open).
- [ ] **M-6** `indexed: true` on an input is now **silently ignored** (the
      step runs once with the whole list as the value) — contradicts the
      loader's "loud refusal" principle. Make it a load-time refusal until
      `IndexedStep` is ported.
- [ ] **M-7** Step-level `continue_on_error:` now makes a recipe **fail to
      load** on ported types (old engine accepted it on 6 of 10 types;
      `comprehensive_recipe.yml` carries it 8×). Tolerate-and-warn like the
      header-level key until the policy is designed.

## 4. Standing decisions worth remembering (recorded in roadmap/gui.md too)

- Last-judging-entry-wins verdicts (F6) kept for parity, pinned by test.
- Only ERROR stops a sequence; `continue_on_error`/`critical` policy is a
  design TODO, not ported.
- Stops land at step boundaries; `RunStarted` ⇒ exactly one `RunFinished`.
- `UseRecipe` carries the live `Recipe` (in-process link only); the HMI
  boundary stays pickle-tested plain values.
- No dark mode for now: `force_light_mode()` pins the light scheme.
- Scaffold license clearance from its author is still owed (roadmap §1.14).
