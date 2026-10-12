# Verificator hints from the recipe schema — Design

**Date:** 2026-10-12
**Status:** design approved in conversation, awaiting spec review
**Modules:** `recipe/` (schema), `helper_applications/recipe_creator/` (verificator)

## 1. Goal

The recipe format's author-facing wording lives next to the format. Adding a step type, an
output type, or a header/sequence/step field means editing `recipe/recipe_schema.py` only;
the "sync rule" in `recipe_creator.md` disappears, replaced by a test that fails when a field
has no text.

The text is written so that a later change can show it in the Recipe Creator's form as
tooltips (one text, two consumers). That wiring is **not** part of this change.

### Success criteria

- Every author-writable field of every recipe model carries a `description`; every required
  field carries `examples`; a test enforces both.
- The verificator holds no per-field, per-steptype or per-output-type wording of its own.
- Verdicts, `ValidationIssue.field` / `.message` / `.line`, the public API
  (`verify_file`, `verify_string`, `ValidationIssue`) and the framework's validation are
  unchanged. Only `ValidationIssue.hint` wording changes.
- `pytest tests`, `ruff check src tests`, `mypy` pass; the documents in §6 describe the code.

## 2. Current state (verified 2026-10-12)

The verdict is already Pydantic: `verificator._run` validates with
`recipe_parser.validate_document()` against `HeaderSchema` / `SequenceSchema`, then runs
`recipe_parser.parse_recipe(check_version=False)`. What the verificator still owns in text:

| Table / function in `verificator.py` | Content |
|---|---|
| `_DOCUMENT_FIELD_HINTS` | header and sequence field hints |
| `_step_field_hint` (`hints` dict + `step_name`) | per (steptype, field) hints |
| `_input_type_hint` | `global` input missing `global_name` |
| `_output_type_hint` (`hints` dict) | per (output type, field) hints |
| `_output_no_type_hint`, `_output_unknown_type_hint` | output type lists with prose per type |
| `_unknown_steptype_hint` (`guesses` dict) | renamed / removed steptype names |
| `_indexed_hint` | Indexed wrapper keys, `parameter_sets`, `id`, `template` |
| `_step_hint` (Sequence refused-keys branch) | Sequence step key refusal |
| `_REMOVED_SEQUENCE_KEYS` | removed sequence keys, for the warning |

## 3. Design — schema side (`recipe/recipe_schema.py`)

### 3.1 Field metadata

Every author-writable field gets `Field(description=...)`; required fields, and optional
fields whose meaning is not obvious from the description, also get `examples=[...]`. Fields
annotated `None` (declared only to be refused — `SequenceStepSchema.step_name/inputs/outputs/id`,
`IndexedStepSchema.id/inputs/outputs`) are excluded: their refusal sentence is their text.

Description wording rules — the text must read well both as a verificator hint and as a
form tooltip:
- one or two plain sentences, addressed to the recipe author, no YAML in the description;
- the example is a **value**, not a YAML line (`examples=[2]`, not `"wait_time: 2"`);
- no reference to the verificator, Pydantic, or Python classes.

### 3.2 Type-level sentence on the tag field

The sentence saying what a step type or output type *is* goes on its `Literal` tag field,
leaving the class docstrings developer-facing:

```python
class WaitStepSchema(_OrdinaryStep):
    steptype: Literal["wait"] = Field(description="Pauses the run for a fixed time.")
    wait_time: Any = Field(description="How long to wait, in seconds.", examples=[2])


class RangeOutput(_RecipeModel):
    type: Literal["range"] = Field(
        description="Passes if the returned value is between 'min' and 'max'."
    )
    min: Any = Field(description="The lowest value that passes.", examples=[4.9])
    max: Any = Field(description="The highest value that passes.", examples=[5.1])
```

A `Literal` field with a `Field(description=...)` and no default stays required and keeps
working as the union discriminator. (To be confirmed by the existing schema tests passing
unchanged; if Pydantic refuses it, stop and re-design — do not fall back silently.)

### 3.3 Common fields

`_StepFields` (`description`, `skip`, `continue_on_error`) and `_OrdinaryStep`
(`step_name`, `id`, `inputs`, `outputs`) are described once and inherited by every step type.

`inputs` has no per-entry model (`InputEntry` is an `AfterValidator`, and validation is not
changed here), so its description explains both forms and its examples show both:

```python
inputs: dict[Any, InputEntry] = Field(
    default_factory=dict,
    description="The method's arguments by name. A value is written as itself; "
                "a mapping with type 'global' reads a run variable instead.",
    examples=[{"voltage": 5, "channel": {"type": "global", "global_name": "channel"}}],
)
```

`ParameterSet.inputs` and `ParameterSet.expect` get descriptions and examples, replacing the
prose of `_indexed_hint("parameter_sets")`.

### 3.4 Format-history constants

Two public constants move into `recipe_schema.py`, beside `INDEXED_STEP_REFUSED_KEYS`:

- `RENAMED_STEP_TYPES: dict[str, str]` — today's `guesses` dict from
  `_unknown_steptype_hint`, keyed by lowercased old name, valued by the new steptype or an
  explanatory note.
- `REMOVED_SEQUENCE_KEYS: dict[str, str]` — today's `_REMOVED_SEQUENCE_KEYS`, unchanged.

### 3.5 What does not change

`description` and `examples` are metadata. Validation results, error messages, `SchemaProblem`,
`recipe_parser` and every step constructor are untouched.

## 4. Design — verificator side (`helper_applications/recipe_creator/verificator.py`)

### 4.1 Dispatch stays

`_hint`, `_step_hint`, `_entry_hint` and `_template_hint` keep choosing *which* field or type
a problem concerns, from `SchemaProblem.path` and `SchemaProblem.kind`. They stop holding text.

### 4.2 New helpers

- `_field_help(model, field) -> str` — the field's description, then `Example:` and its first
  example rendered as YAML (`yaml.safe_dump({field: example}, default_flow_style=None)`,
  stripped), so short values come out inline (`options: [Continue, Abort]`) and nested ones
  as a block (an Indexed `template`). A field without examples gives the description alone.
- `_output_example(model, entry_name) -> str` — an output entry's example assembled from the
  model: its `type` literal plus each other field's first example, keyed by the author's
  entry name (`voltage: {type: range, min: 4.9, max: 5.1}`).
- `_type_list(models, tag) -> str` — each step type or output type with its tag field's
  description, one per line; used by the unknown-steptype and unknown/missing output-type
  hints.

### 4.3 Removed

`_DOCUMENT_FIELD_HINTS`, `_step_field_hint`, `_input_type_hint`, `_output_type_hint`,
`_REMOVED_SEQUENCE_KEYS`, the `guesses` dict, the hand-written type lists in
`_output_no_type_hint` / `_output_unknown_type_hint`, and the refused-key wording for Indexed
and Sequence steps. *As built:* the schema's `INDEXED_STEP_REFUSED_KEYS` /
`SEQUENCE_STEP_REFUSED_KEYS` sentence is already the error's message, so the hint for a
refused key is the list of keys the step does take (`_valid_keys_hint`) rather than the same
sentence twice.

### 4.4 Kept

Text that describes the file, not a format field: the structural pre-check hints in `_run`
(not YAML, empty, not a mapping, not a header, no sequences), `_QUOTE_HINT`, "each step must
be a YAML mapping", the cross-reference hints (duplicate sequence names, `main_sequence`), the
header warnings (empty field, numeric `version`), and the fallback "See recipe_guide.html",
which can now only fire for a problem with no field.

## 5. Tests

- **Completeness** (`tests/unit_tests/test_recipe_schema.py`): walks `HeaderSchema`,
  `SequenceSchema`, every model in `STEP_SCHEMAS`, `PassOutput`, `PassfailOutput`,
  `EqualsOutput`, `RangeOutput`, `GlobalOutput` and `ParameterSet`. Fails, naming model and
  field, when an author-writable field (annotation not `NoneType`) has an empty
  `description`, when a required field has no `examples`, or when a `steptype` / `type` tag
  field has no description.
- **History constants**: every key of `REMOVED_SEQUENCE_KEYS` is absent from
  `SequenceSchema.model_fields`; every key of `RENAMED_STEP_TYPES` is not itself a live
  steptype.
- **Verificator** (`tests/unit_tests/test_verificator.py`): hint-text assertions updated to
  the new wording; new tests that a missing required step field's hint contains the schema's
  description and example, that an output-entry hint uses the author's entry name, and that
  a removed sequence key's warning carries `REMOVED_SEQUENCE_KEYS`' sentence.
- `test_verificator_case_insensitivity.py` must pass unchanged.

## 6. Documentation (same change)

- `helper_applications/recipe_creator/recipe_creator.md` — the sync-rule section becomes: the
  wording lives on the models' fields; the completeness test enforces it; the verificator
  only chooses which field a problem concerns. "What the verificator does", "Files" and
  "What is checked" brought in line.
- `recipe/recipe.md` — field descriptions/examples and the two new constants; how-to-extend
  step 3 (today: "Update the Recipe Creator's verificator hints") becomes "give every new
  field a description, and required ones an example".
- `pypts_implementation_status.html` — a new section for this change; fix the stale
  "Recipe verificator" row (`recipe_verificator/` package, "bulk folder validation").
- Roadmap TODO in `pypts_implementation_status.html`: show schema descriptions as tooltips in
  the Recipe Creator's form.
- `recipe_guide.html` — untouched; the format does not change.

## 7. Out of scope

- Wiring descriptions into the Creator's form (roadmap TODO, §6).
- One rule for cross-document checks (duplicate names / `main_sequence` checked by both the
  verificator and `parse_recipe`).
- The Creator model's own checks in `rc_model._step_problem` (a second copy of some format
  rules).
- The dead `recipe_creator.py`.
- Generating `recipe_guide.html` from the schema.
