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
| `recipe_schema.py` | The format rules: the constants (same names as the old `rules.py`, read by the Recipe Creator and `step_source.py`) and the Pydantic models every document is validated with — `HeaderSchema`, `SequenceSchema`, `AnyStepSchema` and one model per steptype. Only `recipe_parser.py` uses the models |
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

For a tool that checks a recipe rather than loads it — the Recipe Creator's verificator
(`helper_applications/recipe_creator/recipe_creator.md`):

- `parse_recipe(text, file_name, check_version=False)` — the whole load, without the version
  check (no log line, empty `version_notice`).
- `validate_document(raw, schema_cls, context)` — one normalized document against
  `HeaderSchema` or `SequenceSchema`: `([], model)` or `(problems, None)`, where each
  `SchemaProblem` carries `where` and `message` (the two halves of the sentence a
  `RecipeError` carries), `path` (the location in the document, as the YAML nests it, union
  tags left out, positions from 0) and `kind` (Pydantic's error type).
- `sequence_context(document, number)` — how a problem names a sequence document.
- `recipe_schema.STEP_SCHEMAS` — each steptype's model, to ask which keys it takes.

## The load pipeline (`recipe_parser.py`)

1. **Read** the file (`load_recipe` only). Unreadable → `RecipeError`.
2. **Parse** the YAML: document 1 is the header, every further document is a sequence. Empty
   file, bad YAML or a non-mapping header → `RecipeError`.
3. **Normalize** — the recipe language is case-insensitive. Keys of the header, sequences,
   steps and input/output entries are lowercased, and so are a step's `steptype` and an
   entry's `type`. Other values keep their case, and so do input/output *entry names*. An
   `Indexed` step's `template` is normalized as a step.
4. **Validate** (`recipe_schema.py`, via `validate_document()`) —
   `HeaderSchema.model_validate()` on the header, `SequenceSchema.model_validate()` on every
   sequence document, which checks every step through `AnyStepSchema`. **All problems are
   collected and raised as one `RecipeError`**, so the author fixes the file in one round.
   Each problem (`SchemaProblem`) is Pydantic's own message at a location
   `_describe_problem()` makes
   findable: `sequence 'Main', steps[1] 'Only wait': wait_time: Field required` — steps
   counted from 1 and named, the union tag Pydantic puts in the path left out, a number key
   shown as a name (`outputs -> 1`), not a position. Three messages are reworded: a missing
   or bare `steptype:` / output `type:` reads `Field required`, an unknown one
   `steptype 'x' is not one of: …`, and a non-mapping where a model is expected
   `Input should be a valid dictionary` (without Pydantic's class name). The header
   then comes back as `model_dump()` with its defaults filled in (`report_metadata` names
   stripped); each sequence as `model_dump(exclude_unset=True)` — only what the recipe
   wrote, with numbers read as text where a name is expected, so the step constructors keep
   their own defaults and an `Indexed` wrapper's unset `skip` stays unset.
5. **Version check** (unless `check_version=False`) — `_check_framework_version()` compares the header's `version` (the
   pypts version the recipe was written for) with the running pypts, **major.minor only**.
   Warn-only during the refactor: an ERROR in the log and `Recipe.version_notice` set; the
   recipe still loads, and CORE shows the notice to the operator. Hard refusal is planned for
   ~v1.0.
6. **Expand** — every `Indexed` step becomes one ordinary step mapping per parameter set
   (`step/indexed_step.py`). Nothing downstream ever sees the steptype.
7. **Build** — first the checks that need the whole file: duplicate sequence names
   (case-insensitive), at least one sequence, `main_sequence` exists (case-insensitive; empty
   means the first sequence). Then each sequence, each step through
   `step.registry.build_step()` (a `KeyError`, `ValueError` or `TypeError` from a constructor
   becomes a `RecipeError` naming sequence, position and step), and a `Sequence` step gets a
   fresh copy of the sequence it calls (below). `_build_sequence()` fills a sequence's
   absent optional keys from `SEQUENCE_DEFAULTS` with `apply_defaults()`.

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
(`sequence_name` required, and not empty or only spaces; `step_name`, `inputs`, `outputs`, `id` refused with the reasons in
`step/sequence_step.REFUSED_KEYS`; not an `Indexed` template) is checked by
`SequenceStepSchema` and `IndexedStepSchema` in `recipe_schema.py`.

`step_source.py` walks the same depth-first order to give every step-table row its click-panel text.

**Stage 1 (transitional):** every sequence document is still built, each as the root of its
own tree, so any sequence can still be started. Stage 2 makes main the only runnable one and
adds the "never called from main" warning.

## Format rules (`recipe_schema.py`)

The constants below are plain data, read by the Recipe Creator's verificator and
`step_source.py`. The models in the same file encode the same rules for validation;
`tests/unit_tests/test_recipe_schema.py` pins every model's required fields against
`STEP_REQUIRED` / `STEP_TYPE_REQUIRED`.

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

What the models add to the constants:

- A bare key (`description:`, read by YAML as `None`) counts as absent: an optional field
  keeps its default, a required one is `Field required` (`_RecipeModel`).
- Unknown keys are ignored in the header and in a sequence document, and **refused on a
  step** (`extra="forbid"`) — every step key becomes a constructor argument.
- A text field (`name`, `step_name`, `message`, `module`, …) takes text or a number, read
  as its text; a YAML boolean, date or list is refused. Mapping keys (`globals`, `inputs`,
  `outputs`) and global names stay exactly as written - a global is found by plain dict
  lookup. `report_metadata` entries must be strings (a number is refused, not coerced).
- Every ordinary step also takes the `Step` constructor's `id`, `inputs` and `outputs`.
- An `Indexed` template may leave out `step_name` (it is checked under the indexed step's
  name); a `parameter_sets` entry (`ParameterSet`) carries `inputs` and/or `expect` and
  nothing else.

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
2. Add its model to `recipe_schema.py` (subclass `_OrdinaryStep`, `steptype` a `Literal` of
   the lowercase name) and to the `AnyStepSchema` union; `test_recipe_schema.py`'s
   `_ONE_OF_EACH` needs one valid example, and pins the model against the constants.
3. Update the Recipe Creator's verificator hints in the same commit — the sync rule in
   `helper_applications/recipe_creator/recipe_creator.md`.
4. Document it in `recipe_guide.html`.

## Known gaps

- Nested sequences: stage 1 (engine and parser) is done; only-main-runs and the "never called
  from main" warning come with stage 2 (roadmap, `plans/sequence_step_design.md`).
- The version check is warn-only until the compatibility policy (~v1.0).
