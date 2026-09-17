<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# recipe — the data layer

Data only. No execution, no queues, no imports of the Sequencer. A `Sequence` holds `Step`
objects, but the step classes and the steptype registry belong to `pypts.step`
(`step/step.md`). The user-facing format reference is `recipe_guide.html` at the repo root.

## Files

| File | Owns |
|------|------|
| `recipe.py` | `Recipe`, `Sequence`, `RecipeError` — the data objects, plus the `from_file` / `from_yaml_text` facades |
| `rules.py` | The format rules as data: required fields, defaults, the legal steptypes and input/output types. Definitions only — no code acts here |
| `validator.py` | Mandatory-field and shape checks against `rules.py`; each function returns a list of problem strings |
| `recipe_parser.py` | The whole load pipeline (below), `normalize_*`, `apply_defaults`, `current_recipe_version()` |
| `step_source.py` | `step_sources_by_sequence(path)` — for each step-table row, the sequence document it belongs to as written and the step's lines in it, for the GUI's click panel |

## Public entry points

```python
Recipe.from_file(path)                       # load from disk; sets base_dir
Recipe.from_yaml_text(text, file_name="")    # load from a string (tests, tools)
```

Both delegate to `recipe_parser.load_recipe()` / `parse_recipe()` (imported inside the
methods — the module-level dependency is parser → data) and raise `RecipeError` on any load
failure — one exception type for CORE to catch.

`recipe_parser.current_recipe_version()` is the `major.minor` a recipe should declare to match
the running pypts (empty when there is no package metadata). Templates, generators and tests
ask it rather than rebuilding the rule.

## The load pipeline (`recipe_parser.py`)

1. **Read** the file (`load_recipe` only). Unreadable → `RecipeError`.
2. **Parse** the YAML: document 1 is the header, every further document is a sequence. Empty
   file, bad YAML or a non-mapping header → `RecipeError`.
3. **Normalize** — the recipe language is case-insensitive. Keys of the header, sequences,
   steps and input/output entries are lowercased, and so is an entry's `type`. Values keep
   their case (`steptype: PythonModule` stays as written), and so do input/output *entry
   names*. An `Indexed` step's `template` is normalized as a step.
4. **Validate** (`validator.py`) — header, every sequence, every step. **All problems are
   collected and raised as one `RecipeError`**, so the author fixes the file in one round.
5. **Version check** — `_check_framework_version()` compares the header's `version` (the
   pypts version the recipe was written for) with the running pypts, **major.minor only**.
   Warn-only during the refactor: an ERROR in the log and `Recipe.version_notice` set; the
   recipe still loads, and CORE shows the notice to the operator. Hard refusal is planned for
   ~v1.0.
6. **Defaults** — `apply_defaults()` fills every absent (or `None`) optional key from
   `HEADER_DEFAULTS` / `SEQUENCE_DEFAULTS`; mutable defaults are copied.
7. **Expand** — every `Indexed` step becomes one ordinary step mapping per parameter set
   (`step/indexed_step.py`). Nothing downstream ever sees the steptype.
8. **Build** — first the checks that need the whole file: duplicate sequence names
   (case-insensitive), at least one sequence, `main_sequence` exists (case-insensitive; empty
   means the first sequence). Then each sequence, each step through
   `step.registry.build_step()` (a `KeyError`, `ValueError` or `TypeError` from a constructor
   becomes a `RecipeError` naming sequence, position and step), and a `Sequence` step gets a
   fresh copy of the sequence it calls (below). Last, `report_metadata` must be a list of
   non-empty strings.

## Key types

**`Recipe`**:
- `name`, `description`, `version`, `globals`, `main_sequence`
- `sequences: dict[str, Sequence]` — in document order
- `report_metadata: tuple[str, ...]` — globals the Report stamps on every CSV row and in
  the HTML header
- `version_notice` — empty, or the operator sentence from the version check
- `file_name` — set by both entry points when given; `base_dir` — the file's folder, set only
  by `from_file` (what a `PythonModule` step's relative `module:` resolves against)
- `to_summary()` — every sequence's `SequenceSummary`, for `RecipeLoaded`

**`Sequence`**:
- `name`, `description`, `steps`, `teardown_steps`
- `to_summary()` — pickle-safe `SequenceSummary`: one `StepSummary` per step **including the
  teardown steps**, in run order, depth-first over calls (`summary_rows(depth)`): a `Sequence`
  step's row is followed by its own rows, and every row carries `depth` and `is_group`

## Sequence steps — the call tree

A `steptype: Sequence` step calls another sequence document by `sequence_name`
(`step/step.md` §2.8; design in `plans/sequence_step_design.md`). The parser builds a
**fresh copy** of the called sequence for every call (`_build_steps()` →
`_called_sequence()`), so no two calls share a `Step` or a UUID, and a sequence may be called
any number of times. Refused with sequence, position and chain: an unknown `sequence_name`, a
call to the main sequence, and recursion (`Main -> A -> B -> A`). The shape of the call
(`sequence_name` required; `step_name`, `inputs`, `outputs`, `id` refused; not an `Indexed`
template) is checked by the validator through `step/sequence_step.check_sequence_step()`.

`step_source.py` walks the same depth-first order to give every step-table row its click-panel text.

**Stage 1 (transitional):** every sequence document is still built, each as the root of its
own tree, so any sequence can still be started. Stage 2 makes main the only runnable one and
adds the "never called from main" warning.

## Format rules (`rules.py`)

| Name | Meaning |
|------|---------|
| `HEADER_REQUIRED` | `name`, `version` |
| `HEADER_SINGLE_VALUE` | Header fields that may not be a list or mapping |
| `HEADER_DEFAULTS` | `description`, `main_sequence` (empty = first), `globals` (`{}`), `report_metadata` |
| `REPORT_METADATA_DEFAULT` | `("serial_number",)` — a convention, not a constraint; `[]` means none |
| `SEQUENCE_REQUIRED` / `SEQUENCE_DEFAULTS` | `sequence_name`, `steps` (at least one) / `description`, `teardown_steps` |
| `STEP_REQUIRED` | `steptype`, `step_name` |
| `UNNAMED_STEP_TYPES` | `("sequence",)` — exempt from `step_name`; a Sequence step is named after the sequence it calls |
| `STEP_COMMON_DEFAULTS` | `description`, `skip`, `continue_on_error` (default `True`) — accepted by every steptype |
| `STEP_TYPE_REQUIRED` | Per lowercase steptype: the extra required keys. **Its keys are the only steptypes a recipe may name** |
| `STEP_TYPE_DEFAULTS` | Per steptype: its optional keys and their defaults |
| `EXPANDED_STEP_TYPES` | `("indexed",)` — in the rules, never in the registry |
| `INPUT_TYPES` | `global` (needs `global_name`). A non-mapping input is a literal |
| `OUTPUT_TYPES` | `pass`, `passfail`, `equals` (`value`), `range` (`min`, `max`), `global` (`global_name`). Every output is a mapping naming its type |

Removed sequence keys, on purpose: `setup_steps`, `parameters` / `outputs`, `locals`. There is
one variable scope, `globals`, for the whole run.

## `step_source.py` — the click panel's YAML

The GUI is another process and must not learn the recipe format, so this reads the file for
it: `step_sources_by_sequence(path)` → `{sequence_name: (StepSource per row, ...)}`. A
`StepSource` is **the sequence document the row's step belongs to, exactly as written**
(comments and formatting kept, from just after its `---` to just before the next), plus the
step's `first_line` / `last_line` in it (0-based, inclusive), which the panel highlights.
A row inside a called sequence gets that sequence's document; every row an `Indexed` step
expands into highlights the authored `Indexed` block. Line positions come from
`yaml.compose_all` nodes; a list item is bounded by the next item's first line, with the blank
lines and comments in front of it trimmed off.

The row order must match `Sequence.to_summary()` (steps, then teardown, an `Indexed` step once
per parameter set, each call followed by the rows of the sequence it calls);
`tests/unit_tests/test_recipe.py` pins the two together. A failure is a DEBUG line and an
empty result (or a missing sequence), never an exception for the GUI.

## Adding a step type

The authoritative checklist is `step/step.md` §4. On the recipe side:

1. Add its required keys to `STEP_TYPE_REQUIRED` and its optional keys to
   `STEP_TYPE_DEFAULTS`, keyed lowercase. A unit test pins these keys against
   `step/registry.py`'s `STEP_TYPES`.
2. Update the Recipe Creator's verificator hints in the same commit — the sync rule in
   `helper_applications/recipe_creator/recipe_creator.md`.
3. Document it in `recipe_guide.html`.

## Known gaps

- Nested sequences: stage 1 (engine and parser) is done; only-main-runs and the "never called
  from main" warning come with stage 2 (roadmap, `plans/sequence_step_design.md`).
- The version check is warn-only until the compatibility policy (~v1.0).
