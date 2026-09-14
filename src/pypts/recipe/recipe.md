<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# recipe — the data layer

Data only. No execution, no queues, no imports of the Sequencer.

## Files

| File | Owns |
|------|------|
| `recipe.py` | `Recipe`, `Sequence`, `RecipeError` — the data objects |
| `rules.py` | Format constants: required fields, defaults, step-type registry, metadata defaults |
| `recipe_parser.py` | The full load pipeline: read YAML → normalize → validate → build |
| `validator.py` | Field-presence and type checks; produces `RecipeError` on failure |
| `step_source.py` | Resolves module paths for `PythonModule` steps (file-based and package-based) |

## Public entry points

```python
Recipe.from_file(path)           # load from disk
Recipe.from_yaml_text(text)      # load from string (tests, verificator)
```

Both raise `RecipeError` on any failure — one exception type for CORE to catch.

## Key types

**`Recipe`**:
- `name`, `description`, `version`, `globals`, `main_sequence`
- `sequences: dict[str, Sequence]`
- `report_metadata: tuple[str, ...]` — globals stamped on every CSV row
- `base_dir`, `file_name` — set only when loaded from disk
- `version_notice` — non-empty when the recipe's `version` major.minor differs from the
  running framework's (warn-only, not an error)

**`Sequence`**:
- `name`, `description`, `steps`, `teardown_steps`
- `to_summary()` — pickle-safe projection sent to the HMI as `SequenceSummary`

## Format rules (`rules.py`)

- `HEADER_REQUIRED` — fields that must be present (`name`, `version`)
- `HEADER_DEFAULTS` — what absent optional fields mean
- `STEP_TYPES` — maps YAML `steptype` strings to step classes
- `REPORT_METADATA_DEFAULT` — `("serial_number",)` — the convention, not a constraint

## Adding a step type

1. Implement the class in `src/pypts/step/` (see `step/step.md`).
2. Add `"StepTypeName": StepClass` to `STEP_TYPES` in `rules.py`.
3. Add the type name to the verificator's allowed list (see `recipe_verificator/recipe_verificator.md`).

## Known gaps

- `parameters` / `outputs` (subsequence calling) are parsed but unused — execution engine
  does not support subsequences yet.
- `test_package` / `step_source.py` resource-based loading is implemented; file-based
  loading is the default.
