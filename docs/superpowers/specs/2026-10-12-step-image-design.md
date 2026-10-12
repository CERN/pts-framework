# Step and sequence images in the GUI's right panel — Design

**Date:** 2026-10-12
**Status:** implemented 2026-10-12 (roadmap §1.62); this file describes what was built
**Modules:** `recipe/` (schema, parser, summary), `step/` (prompt steps, Indexed expansion),
`messages/` (`StepSummary`, `SequenceSummary`), `core/` (load notice), `hmi/gui/`
(right panel), `helper_applications/recipe_creator/` (verificator, via the schema)

## 1. Goal

The right column's picture area (`InteractionPanel.image_label`) shows the CERN logo for
most of a run: only a prompt step with `image_path` puts anything else there. A recipe
author gets one optional key, `image_path`, on **every step and every sequence**, and the
GUI shows that picture while the step runs. When no picture applies, the area shows a
**run card** — what is running and how the run is going — instead of the logo.

### Success criteria

- `image_path` is accepted on every step type (PythonModule, Wait, UserInteraction,
  UserWrite, UserLoading, Sequence, Indexed) and on a sequence document.
- The picture shown is the innermost one that applies (§4.2); it disappears when its step
  ends.
- A missing image never stops a recipe from loading or a step from running: the operator
  is told once, at load, and sees a "No image available" placeholder where it would show.
- With no picture to show during a run, the run card is shown. Idle, before and after a
  run: the CERN logo, as today.
- No new message types; no change to CLI or headless behaviour (they ignore the key).
- `pytest tests`, `ruff check src tests`, `mypy` pass; the documents in §7 describe the code.

## 2. Current state (verified 2026-10-12)

| What | Where |
|---|---|
| `image_path` exists on the three prompt schemas only (`_IMAGE_PATH` sentence) | `recipe/recipe_schema.py` — `UserInteractionStepSchema`, `UserWriteStepSchema`, `UserLoadingStepSchema` |
| Every step type shares `_StepFields` (`description`, `skip`, `continue_on_error`); `_OrdinaryStep` adds name/id/inputs/outputs; `SequenceStepSchema` and `IndexedStepSchema` extend `_StepFields` directly | `recipe_schema.py` |
| Prompt steps resolve the path **at run time** with `resolve_image_path()`, which raises `FileNotFoundError` for a missing file — the step becomes an ERROR | `step/operator_prompt.py:22` |
| `base_dir` is `""` until `load_recipe()` sets it after parsing | `recipe/recipe_parser.py:63` |
| Indexed steps are expanded at load time; the wrapper's `description` is copied onto each generated step unless the template has its own | `step/indexed_step.py` (`_build_one`) |
| `RecipeLoaded` carries `SequenceSummary(sequence_name, steps)` per sequence; each row a `StepSummary(step_id, step_name, description, depth, is_group)`, built by `Sequence.summary_rows()` | `messages/run_events.py`, `recipe/recipe.py` |
| A called sequence runs through the same `run_sequence()`, which emits `SequenceStarted`/`SequenceFinished` — so nested sequences bracket their steps | `step/step.py:898`, `:936`; `step/sequence_step.py:119` |
| CORE shows `recipe.version_notice` to the operator as an ERROR-severity `ModuleError` (WARNING would only be logged) | `core/core.py` (`load_recipe`, ~line 610) |
| The GUI's `show_step_started` / `show_step_finished` / `show_sequence_*` drive the table and `RunProgress`; the sequence handlers only log | `hmi/gui/gui.py` |
| `InteractionPanel._refresh_visual()` falls back to the CERN logo when the path does not exist or the pixmap is null | `hmi/gui/interaction_panel.py` |
| `RunProgress` counts non-`is_group` rows of the shown sequence; every verdict counts | `hmi/gui/run_progress.py` |

## 3. Design — recipe side

### 3.1 Schema (`recipe/recipe_schema.py`)

- `image_path: str | None = Field(default=None, description=_IMAGE_PATH, examples=[...])`
  moves from the three prompt schemas to **`_StepFields`**, so every step type has it. The
  three per-class declarations are removed.
- `SequenceSchema` gets the same field.
- `_IMAGE_PATH` is reworded to fit every step: *"A picture shown on the right while this
  step runs: a path relative to the recipe's own folder, or an absolute one."* The sequence
  field gets its own sentence: *"A picture shown while this sequence runs, for every step
  that has none of its own."*

The verificator reads the schema, so it accepts the key and shows the new hint with no
code of its own (verify against the schema-hints change, which may land first).

### 3.2 Data objects

- `Step.__init__` gains `image_path: str | None = None`, stored as `self.image_path` — the
  value as written in the recipe. Step types that took `image_path` themselves stop doing
  so and use the base attribute.
- `Sequence.__init__` gains `image_path: str | None = None`.
- `SequenceStep` and the parser pass the Sequence step's own `image_path` through like any
  other step field.
- **Indexed:** `image_path` follows `description` — the template's own wins, otherwise the
  wrapper's is copied onto every generated step.

### 3.3 Resolution and the missing-file rule (`recipe/recipe_parser.py`)

`load_recipe()`, after it has set `base_dir`, resolves every `image_path` of every step
(including teardown steps and called-sequence copies) and every sequence to an **absolute
path** — relative to `base_dir`, the rule `resolve_image_path()` uses today.

A file that does not exist is **not** an error:

- the parser logs one WARNING per missing file (wording per `logging_rules.md`), naming
  sequence, step and path;
- the absolute path is kept as it is — the GUI decides what to draw (§4.3);
- the missing files are collected into one operator sentence on the `Recipe`.
  `Recipe.version_notice: str` is **replaced** by `Recipe.load_notices: tuple[str, ...]`:
  the version mismatch sentence (when there is one) and the missing-images sentence (when
  there is one) are entries of it. CORE's `load_recipe` loops over it and shows each entry
  exactly as it shows `version_notice` today (an ERROR-severity `ModuleError`, so it
  reaches the operator). Every reader of `version_notice` moves to `load_notices`.

`parse_recipe()` from text (no `base_dir`) does not resolve: the paths stay as written and
nothing is checked.

`resolve_image_path(image_path, base_dir)` stays in `step/operator_prompt.py`, loses its
`step_name` argument and no longer raises; the parser uses it, and the prompt steps still call
it when they ask (a no-op on an absolute path).

### 3.4 Summaries (`messages/run_events.py`, `recipe/recipe.py`)

- `StepSummary` gains `image_path: str | None = None` (absolute, or None).
- `SequenceSummary` gains `image_path: str | None = None`.
- `Sequence.to_summary()` / `summary_rows()` fill them.

Both stay plain pickle-safe payloads; no union or handler changes.

## 4. Design — GUI side

### 4.1 What the picture area can show

| State | Shown |
|---|---|
| No run (idle, recipe loaded or not, after a run ends) | CERN logo — unchanged |
| Prompt open, prompt has `image_path` | that picture (as today) |
| Prompt open, prompt has no `image_path` | CERN logo (as today) |
| Run in progress, an image applies (§4.2) | that picture |
| Run in progress, no image applies | the run card (§4.4) |
| An image applies but the file is missing or will not load | the "No image available" placeholder (§4.3) |

### 4.2 Which image applies — the running stack

The GUI keeps a stack of what is currently running, built only from events it already
receives:

- `SequenceStarted(name)` pushes the sequence's `image_path` (looked up by name in the
  loaded `RecipeLoaded`; names are unique regardless of case); `SequenceFinished` pops it.
- `StepStarted(step_id)` pushes the step's `image_path` (looked up by `step_id` among the
  `StepSummary` rows); `StepFinished` pops it.

The picture shown is the **innermost non-empty entry**. So a step's image disappears when
the step ends; a step with none shows its sequence's; a step inside a called sequence with
neither shows the image of the `Sequence` step that called it, then that step's sequence,
and so on outward; with nothing anywhere, the run card. A `Sequence` step stays on the
stack while its children run because its `StepFinished` arrives after theirs.

`RunStarted` and `RunFinished` clear the stack. A popped entry is matched by id/name, not
blindly, so a lost event cannot leave a stale picture behind.

### 4.3 The placeholder

- File: `src/pypts/hmi/gui/images/no_image_available.png` — Wikimedia Commons
  *"No image available.svg"* by Cburnett (2007), rendered to PNG, **public domain**
  (ineligible for copyright). Source:
  https://commons.wikimedia.org/wiki/File:No_image_available.svg
- Licence sidecar `no_image_available.png.license` with
  `SPDX-License-Identifier: LicenseRef-PublicDomain` and the author/source; a new
  `LICENSES/LicenseRef-PublicDomain.txt` states that the file is in the public domain and
  gives the Wikimedia source URL.
- Loaded through `resources.py` like the logo, and tinted with the palette's `text_muted`
  in both themes (it is grey on transparent, unreadable on a dark panel untinted).
- `InteractionPanel._refresh_visual()` shows it — instead of the logo — whenever a path was
  given but the file is missing or the pixmap is null. This also covers a prompt's image.

### 4.4 The run card

A widget in the picture area of `InteractionPanel`, swapped with `image_label` (both in a
`QStackedWidget`, or visibility toggled — implementation choice). It shows:

- **Current step:** name and description (from the `StepSummary` of the innermost running
  step).
- **Elapsed:** the run's and the current step's, ticking once a second (a `QTimer` started
  on `RunStarted`, stopped on `RunFinished`; paused time is not excluded).
- **Counts so far:** every verdict that occurred, in the order PASS, FAIL, ERROR, DONE,
  SKIP, STOP (`2 PASS · 1 FAIL`), counted by the rule `RunProgress` uses (no `is_group`
  rows). Plain text; the last-failure line carries the FAIL colours.
- **Last failure:** the name of the most recent step that ended FAIL or ERROR; hidden while
  there is none.

GUI-only: nothing is sent, CORE knows nothing of it. Light and dark palettes from
`palette.py`.

### 4.5 Engineering-mode retest

A single-step retest emits the same events, so the same rules apply with no special case.

## 5. Out of scope (roadmap TODOs)

- Instructions/Markdown text in the panel; warning levels; `on_fail` hints.
- A plot slot filled from step code.
- Showing a step's image when its row is clicked outside a run (preview).
- The verificator checking that image files exist (it validates the format, not the disk).
- CLI/headless display of anything.
- A Wait-step countdown on the run card.

## 6. Tests

- **Schema:** `image_path` accepted on every step type and on a sequence; refused nowhere;
  description/example present (existing schema-hints test).
- **Parser:** relative path resolved against `base_dir`; absolute kept; missing file →
  recipe loads, WARNING logged, notice text set; Indexed wrapper vs template precedence;
  teardown and called-sequence steps resolved.
- **Summaries:** `StepSummary`/`SequenceSummary` carry the absolute path; still pickle-safe
  (`test_messages.py`).
- **Prompt steps:** a missing image no longer makes the step an ERROR.
- **CORE:** a recipe with missing images sends the notice and `RecipeLoaded`; the existing
  version-notice tests move from `version_notice` to `load_notices`.
- **REUSE:** `reuse lint` passes with the new image, sidecar and `LICENSES/` file.
- **GUI (`test_hmi_gui.py`):** stack precedence (step > sequence > calling Sequence step >
  run card); image gone after `StepFinished`; prompt without image shows logo; missing
  file shows the placeholder; logo after `RunFinished`; run card counts and last failure.

## 7. Documents to update in the same change

`recipe_guide.html` (the key on steps and sequences, missing-file rule), `recipe/recipe.md`,
`step/step.md` (Step attribute, prompt steps no longer raise, Indexed precedence),
`messages/messages.md` (the two payload fields), `core/core.md` (the load notice),
`hmi/gui/gui.md` (picture-area states, running stack, placeholder, run card),
`usage_manual.html` (what the operator sees), `recipe_creator.md` if the sync rule still
exists, `pypts_implementation_status.html` (done + the §5 TODOs), and a demo recipe in
`resources/recipes/Development_recipes/`.
