# recipe_verificator module

## What this module does

Validates a recipe YAML file or string and returns **every problem found in one
pass** — no bail-out on first error. The result is a `list[ValidationIssue]`,
each carrying a severity, a dotted field path, a short message, a fix hint, and
a line number.

## Files

| File | Owns |
|---|---|
| `issue.py` | `ValidationIssue` dataclass — the single result type |
| `verificator.py` | Validation pipeline: `verify_file(path)` and `verify_string(content)` |
| `__init__.py` | Public exports: `ValidationIssue`, `verify_file`, `verify_string` |

## The sync rule — **read this before touching either module**

**`verificator.py` is the consumer of `pypts.recipe.rules`. When `rules.py`
changes, `verificator.py` must be updated in the same commit.**

Specifically, if you:

- Add a step type to `STEP_TYPE_REQUIRED` → add a hint in `_step_field_hint`
  and ensure `_STEP_TYPE_VALID` (derived automatically from `STEP_TYPE_REQUIRED`
  and `STEP_TYPE_DEFAULTS`) covers every key the new type accepts.
- Add optional fields to a step type in `STEP_TYPE_DEFAULTS` → nothing extra is
  required; `_STEP_TYPE_VALID` is derived at import time and will pick them up.
- Add a new input type to `INPUT_TYPES` → add a hint branch in
  `_input_type_hint`.
- Add a new output type to `OUTPUT_TYPES` → add a hint branch in
  `_output_type_hint` and `_output_unknown_type_hint`.
- Add a new header field to `HEADER_REQUIRED` → add a hint in
  `_header_required_hint`.
- Add a new sequence field to `SEQUENCE_REQUIRED` or `SEQUENCE_DEFAULTS` →
  add the corresponding check in `_check_sequence` and add the key to
  `_KNOWN_SEQUENCE_KEYS`.
- Remove a field that existed before → add it to `_REMOVED_SEQUENCE_KEYS`
  (sequence level) or add an entry to `_unknown_steptype_hint` (step type
  level) so authors get a targeted message instead of a generic "unknown key".

The rule in one sentence: **every change to `rules.py` is incomplete without
a corresponding update to `verificator.py` and its hint strings.**

## Public API

```python
from pypts.helper_applications.recipe_verificator import (
    verify_file,
    verify_string,
    ValidationIssue,
)

issues: list[ValidationIssue] = verify_file("path/to/recipe.yml")
issues: list[ValidationIssue] = verify_string(yaml_text)
```

Results are sorted: errors first (by line number), then warnings.

## ValidationIssue fields

```python
issue.severity  # "error" | "warning"
issue.field     # dotted path: "header.name", "sequence 'Main'.steps[2].wait_time"
issue.message   # short description of what is wrong
issue.hint      # fix suggestion, with a YAML example where useful
issue.line      # 1-based line number in the YAML source, or None
issue.is_error  # True if severity == "error"
issue.is_warning
str(issue)      # "[ERROR] (line 12) header.name: Missing required field 'name'."
```

## Integration with recipe_creator

`recipe_creator` calls `verify_string(content)` on every edit and `verify_file`
on save. It gets back a `list[ValidationIssue]` and is responsible for rendering
them (e.g., showing `message` in an error list and `hint` in a detail panel).
The verificator never prints to stdout.

## What is checked

**Header:** `name` and `version` required; `description`, `main_sequence`,
`globals`, `report_metadata` optional with type checks.

**Sequences:** `sequence_name` and `steps` (non-empty) required; `teardown_steps`
optional; specific warnings for removed keys (`setup_steps`, `parameters`,
`outputs`, `locals`); generic warnings for truly unknown keys.

**Steps:** `steptype` and `step_name` required on every step; type-specific
required fields from `rules.STEP_TYPE_REQUIRED`; `skip` and `continue_on_error`
type-checked; `inputs` / `outputs` vocabulary validated against
`rules.INPUT_TYPES` and `rules.OUTPUT_TYPES`; unknown keys warned.

**Indexed steps:** delegated to `indexed_step.check_indexed_step` plus the
template is validated as an ordinary step.

**Cross-references:** `main_sequence` names an existing sequence; duplicate
sequence names.

## Known limitations

- Indexed step template line numbers are best-effort (use the wrapper step's
  line when the template's specific field line is not tracked).
- Global variable forward-reference checking (warning when a `{type: global}`
  input names a variable not in `globals`) is not implemented; an earlier step
  may set it dynamically.
- `image_path` existence on disk is not checked.
