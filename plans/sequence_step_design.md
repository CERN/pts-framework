# SequenceStep — nested sequences under one main sequence

Design agreed 2026-09-16 (brainstorming session). Not yet implemented.
Status and stage tracking: `pypts_implementation_status.html` (TODO — Nested sequences).

This **reverses** the 2026-09-01 decision "SequenceStep — to be dropped" (`step/step.md` §2.8).
The docs must say the decision changed, with the date and reason, not silently contradict it.

---

## 1. Goal

- A recipe has exactly **one executable sequence: `main_sequence`**. Nothing else can be started
  (GUI, CLI, API, headless).
- Every other sequence document is a **group of steps** that main may call with a
  `steptype: Sequence` step. Groups may call groups, to any depth.
- A group is a **real group at run time**: its own verdict, its own `teardown_steps`, its own row
  in the step table with its children indented under it.
- Full flexibility of calls: a sequence may be called any number of times, from any `steps` or
  `teardown_steps` list (e.g. `Sequence3` ×45, then `Sequence2` ×2, then `Sequence3` again).
  Repetition is written as repeated `Sequence` steps. **No `repeat` key** (user: "if I need it,
  I will ask for it").
- `Indexed` and `Sequence` do **not mix**: a sequence is a group, `Indexed` is parametrization.
  An `Indexed` step inside a called sequence works as today; an `Indexed` whose `template` is a
  `Sequence` step is refused.

## 2. Recipe format and loading

### 2.1 Format

Every sequence is its own YAML document with today's structure (`sequence_name`, `description`,
`steps`, `teardown_steps`). A call:

```yaml
- steptype: Sequence
  sequence_name: PowerCycle      # required; matched case-insensitively
  description: optional          # row shows this, else the called sequence's description
  skip: false                    # optional (common default)
  continue_on_error: true        # optional (common default); false = group ERROR/FAIL halts the run
```

Refused on a `Sequence` step (`RecipeError`): `step_name`, `inputs`, `outputs`, `id`.
The group's name everywhere (table row, log, `group_path`) is `sequence_name`.

### 2.2 Loading (`recipe/recipe_parser.py`)

1. All documents are read, normalized and validated as today; duplicate sequence names refused.
2. **Only `main_sequence` is built**, recursively. At every `Sequence` step (in `steps` or
   `teardown_steps`) the parser builds a **fresh copy** of the called sequence — new `Step`
   objects, new UUIDs — wrapped in a `SequenceStep`. Two calls = two independent copies.
3. Refused with a `RecipeError` naming sequence, position and chain:
   - a call to the main sequence (`main sequence 'Main' cannot be called`);
   - an unknown `sequence_name` (lists the sequences that exist);
   - recursion — a sequence reaching itself directly or indirectly (`Main -> A -> B -> A`).
     Repeated, non-recursive calls are **not** a cycle;
   - an `Indexed` step whose `template` is a `Sequence` step.
4. Sequences never reached from main (directly or indirectly): **WARNING**, recipe still loads.
5. `Indexed` steps inside any sequence are expanded as today, before that sequence's copy is built.

### 2.3 What loading produces

- `Recipe.main_sequence` is the root of the tree that runs.
- `Recipe.sequences` still holds every sequence as written (Creator, verificator); only main's
  tree executes.
- `Recipe.to_summary()` returns **main only**, depth-first. Each `StepSummary` carries `depth` and
  `is_group`. A group's teardown children come after its step children, as today.

## 3. Execution

Design choice **A** (agreed over B, a SequenceStep with its own `run()`): the step lifecycle stays
written once.

- `Runtime` gains plain **state** (not seams): `halted`, and a nesting context — `depth`,
  `group_path`, `in_teardown` — that `SequenceStep` enters/leaves around its child
  (context manager, restored on exit).
- `Step` gains one replaceable method: **"decide my verdict"** (default = today's
  `process_outputs` judging). `SequenceStep` replaces `_step()` and that method.
- `step.md` §4 rule becomes: a type replaces `_step()`; a type that contains other steps may also
  replace the verdict method.
- `StepResult.subresults` is written by `SequenceStep` (the child results).

### 3.1 A group running

`SequenceStep.run()` (inherited) emits `StepStarted` (row shows running), enters the group
(depth+1, path `Main/PowerCycle`), runs its copy through the existing `run_sequence()` —
steps, then teardown — and leaves. Verdict: **worst of all children, teardown included** (same rule
as `run_sequence()` today; all SKIP → SKIP). Then `StepFinished` + `StepExecuted`.

### 3.2 Halt (`continue_on_error: false`)

- The failing step sets `runtime.halted`. Every step loop at every depth checks it beside the stop
  check: the rest of the group, every enclosing group and the rest of main are recorded SKIP
  (`Not run: the sequence stopped at step 'measure_v'.`).
- Teardowns still run, innermost first: the group's, each enclosing group's, then main's.
- A halt is **never STOP**: the run ends with its real ERROR/FAIL
  (`test_a_step_that_halts_the_run_reports_error_not_stop` stays valid).
- The same flag on a `Sequence` step halts the run on the group's verdict.

### 3.3 Stop

Unchanged semantics, checked between steps at every depth; remaining steps SKIP, all teardowns run,
run ends STOP.

### 3.4 Pause

- Held before the next real step at **any depth**; not before a group row itself (the group's
  first child is where it holds).
- Never held inside teardown at any depth, including a group called from teardown.
- A pause with no step left to hold before lapses **only when main's steps end**
  (`drop_pending_pause` at depth 0 only), not at a group's end.

### 3.5 Teardown

Everything under a `teardown_steps` list, at any depth, runs to the end: no hold, no Stop, no
halt, a failing step does not skip its siblings. `in_teardown` is inherited by groups called from
teardown.

### 3.6 `skip: true` on a Sequence step

The group's main steps are recorded SKIP at every depth; its **teardown still runs**. The group
verdict is the normal aggregate (e.g. a DONE teardown → DONE; no teardown → SKIP).

### 3.6a A group the run never reaches (added 2026-09-17)

When Stop or a halt happened before a group, the group row, every row inside it at every depth
**and its teardown rows** are recorded SKIP with the run's reason. Nothing inside runs — nothing
was set up. (Unlike `skip: true`, which is the author's decision and still runs the teardown.)

### 3.6b Counting (added 2026-09-17)

Totals count **real steps only**, at every depth; group rows are not counted. This covers the
`Sequence '…' finished: …` log line, the run summary lines and `RunFinished.outcomes` (every real
step, flat, in execution order).

### 3.6c Step-layer hooks, as implemented

Design A needs one more hook than first described, because a group the run never reaches must
still settle its children's rows. A type that contains steps sets `contains_steps = True` and
replaces `_step()`, `_verdict()` and `_skip_contents()`; it keeps its child results on
`child_results`, which `run()` copies to `StepResult.subresults`. Everything else stays in `Step`.

### 3.7 Logs

Wording unchanged, indented two spaces per depth level:

```
Step 2/3 'PowerCycle' started.
  Sequence 'PowerCycle' started: 2 steps.
  Step 1/2 'power_off' DONE (0.2 s).
  Step 2/2 'measure_v' FAIL (1.1 s) - measure_v = 4.2, expected between 4.9 and 5.1 ...
  Teardown step 1/1 'power_on' DONE (0.3 s).
  Sequence 'PowerCycle' finished: FAIL - 2 completed, 1 failed, 1.6 s.
Step 2/3 'PowerCycle' FAIL (1.6 s).
```

`SequenceStarted` / `SequenceFinished` are still emitted per group (they come from
`run_sequence()`); frontends log them at DEBUG only.

## 4. Messages, entry point, frontends, report

### 4.1 Messages (`messages/`, all plain values — pickle-safe)

- `StepSummary(step_id, step_name, description)` gains `depth: int`, `is_group: bool`. A group
  row's `step_name` is its `sequence_name`.
- `StepExecuted` gains `group_path: str` (e.g. `Main/PowerCycle`).
- `StepStarted`, `StepFinished`, `StepOutcome` unchanged; rows are still keyed by `step_id`.
- `StartSequence(sequence_name)` → **`StartRun()`** (no fields).
- `RunSequence(recipe, sequence_name)` → **`RunSequence(recipe)`**.
- `RecipeLoaded` carries `main_sequence` and a single `SequenceSummary` — main's tree.
- Unions, `match` handlers, `messages.md`, `test_messages.py` follow.

### 4.2 Entry point

CORE and the Sequencer always run `recipe.main_sequence`. The "no such sequence" branch in
`Sequencer.execute_sequence()` goes.

### 4.3 GUI

- `top_bar.py`: sequence combo removed; Start runs main.
- `gui.py`: `show_selected_sequence` removed; on `RecipeLoaded` the table shows main's tree;
  `open_recipe_and_start()` loses its sequence argument.
- `step_table.py`: still a `QTableWidget`. Group rows bold; name indented by `depth`. Group rows
  go running → verdict like any row. Hover YAML and highlighting per row as today.

### 4.4 CLI

`start_sequence <name>` → `start`. Recipe summary lists main only. Step lines indented by depth
(CLI keeps a `step_id → depth` map from `RecipeLoaded`).

### 4.5 API and launcher — breaking change

`--sequence` removed (`startup.py`, headless). `Pts.run()` and `open_gui()` lose `sequence_name`.
`api_showcase.py`, `api.md` updated.

### 4.6 Report (`report/report.py`)

- New column **`group_path`** after `sequence_name`, from `StepExecuted`.
- **Leaf rows only**: a `StepExecuted` whose `step_type` is `SequenceStep` is not written.
- `sequence_name` on a row = the sequence the step is defined in (last element of `group_path`),
  no longer "the last `SequenceStarted`" (wrong after a group ends).
- `report.html` shows `group_path`; regenerating HTML from CSV still works.

### 4.7 GUI results panel (added 2026-09-17)

The results tree nests steps under **group nodes**: a group is a node with its verdict chip, its
steps and nested groups are its children, each step keeping its Inputs / Outputs as today. The
panel learns which rows are groups and their depth from the `StepSummary` rows of `RecipeLoaded`.
The PASS / FAIL / TOTAL badges count real steps only (§3.6b).

## 5. Recipe Creator and verificator

### 5.1 Verificator (`verificator.py`, per the sync rule in `recipe_creator.md`)

Sequence step shape (`sequence_name` required; `step_name`/`inputs`/`outputs`/`id` refused);
unknown sequence **error**; call to main **error**; recursion **error** with chain;
`Indexed` template = `Sequence` **error**; unreachable sequence **warning**. Line numbers point at
the `sequence_name:` line.

### 5.2 Creator UI

- Add-step menu lists `STEP_TYPE_REQUIRED` already → `Sequence` appears.
- `rc_model._default_step()` and `ListStepView` / `CardStepView` / `PanelsStepView` assume
  `step_name`; for a `Sequence` step they show `[Sequence] PowerCycle` and the default step
  writes no `step_name`.
- `StepFormWidget`: `sequence_name` is a dropdown of the recipe's other sequence names (main
  excluded).
- **Call-tree preview**: read-only panel, main → groups → nested groups, rebuilt on model change;
  repeated calls listed each time; recursion marked red.
- **Go to called sequence**: button on the Sequence step form, and double-click in the tree,
  switch the editor to that sequence document.

## 6. Documentation (same change as the code it describes)

- `step.md` §1 table, §2.8 (dropped → implemented, dated, why), §3.1 / §3.7 (halt, pause at
  depth), §4 (widened rule).
- `recipe.md`, `sequencer.md`, `messages.md`, `gui.md`, `hmi.md`, `api.md`, `launcher.md`,
  `report.md`, `recipe_creator.md`.
- `rules.py` comments (`SEQUENCE_DEFAULTS` note on `SequenceStep` being dropped).
- `recipe_guide.html` (new Sequence step section; §12), `usage_manual.html` (no dropdown, `start`,
  no `--sequence`, `group_path` column), `migration_instructions.html` (old
  `sequence: {type: internal, name}` → new form), roadmap status.
- Demo recipe `resources/recipes/sequencestep_demo.yml`: main calls a group twice, a nested group,
  a group in teardown, an `Indexed` inside a group.

## 7. Tests

- Parser: tree built; fresh UUIDs per call; repeated calls allowed; refusals (unknown, main,
  recursion, Indexed-template); unreachable warning.
- Step layer: group verdict incl. teardown; halt at depth (teardowns innermost first, real
  ERROR/FAIL not STOP); Stop at depth; pause at depth, lapses only at main's end; skip with teardown
  running; group in teardown runs to the end; log indentation.
- Summary `depth` / `is_group`; messages round-trip; report `group_path`, leaf rows only,
  `sequence_name` correct after a group; CLI `start`; verificator; Creator model.
- All three quality gates (`pytest tests`, `ruff check src tests`, `mypy`).

## 8. Delivery stages

Each stage passes the quality gates, is reviewable alone, and updates its module context files.
Nothing is committed by Claude; the user reviews and commits each stage.

Stage 1 is transitional in two ways, both closed by stage 2: every sequence document is still
built (each as the root of its own tree), so the existing sequence dropdown keeps working; and
the "never called from main" warning is added in stage 2, when only main can start.

1. **Engine** — rules, parser, `SequenceStep`, Runtime context, verdict method, halt, pause, logs;
   the payload fields the engine fills (`StepSummary.depth` / `is_group`,
   `StepExecuted.group_path`, defaulted so existing senders keep working); tests; `step.md`,
   `recipe.md`, `messages.md`.
2. **Only main starts, end to end** — `StartRun`, `RunSequence(recipe)`, CORE / Sequencer,
   `hmi_client`, GUI combo and `open_recipe_and_start`, CLI `start`, API / launcher / headless.
   One stage because removing `StartSequence` breaks every caller at once.
3. **Display + report** — step table indentation and bold groups, CLI indentation, results
   panel group nodes, report `group_path` / leaf rows / `sequence_name`.
4. **Verificator + Creator UI.**
5. **Docs sweep + demo recipe** — `recipe_guide`, `usage_manual`, `migration_instructions`,
   roadmap.
