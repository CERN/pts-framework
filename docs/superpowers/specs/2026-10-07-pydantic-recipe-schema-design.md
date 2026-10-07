# Pydantic Recipe Schema — Design Spec

**Date:** 2026-10-07
**Branch:** architecture_refactor

---

## Goal

Replace the hand-written `validator.py` and `rules.py` in the recipe module with a
Pydantic-based schema. Pydantic stays internal to the recipe loading pipeline; `Recipe`,
`Sequence`, and `Step` remain plain classes so the rest of the framework (CORE, Sequencer,
HMI) gains no Pydantic dependency.

---

## File Changes

| File | Change |
|---|---|
| `src/pypts/recipe/recipe_schema.py` | **New** — Pydantic models + all constants |
| `src/pypts/recipe/rules.py` | **Deleted** |
| `src/pypts/recipe/validator.py` | **Deleted** |
| `src/pypts/recipe/recipe_parser.py` | **Modified** — uses schema |
| `src/pypts/recipe/step_source.py` | **Modified** — import from schema |
| `src/pypts/helper_applications/recipe_creator/rc_model.py` | **Modified** |
| `src/pypts/helper_applications/recipe_creator/rc_widgets.py` | **Modified** |
| `src/pypts/helper_applications/recipe_creator/recipe_creator_new.py` | **Modified** |
| `src/pypts/helper_applications/recipe_creator/verificator.py` | **Modified** |
| `tests/unit_tests/test_step.py` | **Modified** |
| `tests/unit_tests/test_rc_model.py` | **Modified** |
| `pyproject.toml` | **Modified** — add `pydantic` to `dependencies` |

`recipe.py`, `step/`, `core/`, `sequencer/`, `hmi/` are **untouched**.

---

## `recipe_schema.py` — Structure

### 1. Constants (re-exported, replacing `rules.py`)

All constants currently in `rules.py` are moved here verbatim and keep the same names:

```
HEADER_REQUIRED, HEADER_SINGLE_VALUE, REPORT_METADATA_DEFAULT, HEADER_DEFAULTS
SEQUENCE_REQUIRED, SEQUENCE_DEFAULTS
STEP_REQUIRED, UNNAMED_STEP_TYPES, EXPANDED_STEP_TYPES
STEP_TYPE_REQUIRED, STEP_TYPE_DEFAULTS, STEP_COMMON_DEFAULTS
INPUT_TYPES, OUTPUT_TYPES
```

These remain plain Python dicts/tuples so that all consumers (recipe_creator,
step_source, tests) can import them without depending on Pydantic at runtime.

### 2. Output entry models (discriminated union on `type`)

```python
class PassOutputEntry(BaseModel):   type: Literal["pass"]
class PassfailOutputEntry(BaseModel): type: Literal["passfail"]
class EqualsOutputEntry(BaseModel): type: Literal["equals"];  value: Any
class RangeOutputEntry(BaseModel):  type: Literal["range"];   min: Any; max: Any
class GlobalOutputEntry(BaseModel): type: Literal["global"];  global_name: str

OutputEntry = Annotated[Union[Pass..., Passfail..., Equals..., Range..., Global...],
                        Field(discriminator="type")]
```

### 3. Step models (discriminated union on `steptype`)

All step models inherit `CommonStepFields`:

```python
class CommonStepFields(BaseModel):
    description: str = ""
    skip: bool = False
    continue_on_error: bool = True
```

Per-steptype models:

| Model | `steptype` literal | Required fields | Notes |
|---|---|---|---|
| `PythonModuleStepSchema` | `"pythonmodule"` | `step_name`, `module`, `method_name` | `inputs: dict[str, Any]`, `outputs: dict[str, OutputEntry]` |
| `UserInteractionStepSchema` | `"userinteraction"` | `step_name`, `message`, `options` | `image_path: str \| None`, `outputs` |
| `UserWriteStepSchema` | `"userwrite"` | `step_name`, `message` | `image_path`, `outputs` |
| `UserLoadingStepSchema` | `"userloading"` | `step_name`, `message` | `select: str = "file"`, `image_path`, `outputs` |
| `WaitStepSchema` | `"wait"` | `step_name`, `wait_time` | |
| `SequenceStepSchema` | `"sequence"` | `sequence_name` | No `step_name`. `@model_validator(mode="before")` raises on `step_name`, `inputs`, `outputs`, `id` — same messages as `sequence_step.REFUSED_KEYS`. |
| `IndexedStepSchema` | `"indexed"` | `step_name`, `template`, `parameter_sets` | `template: AnyStepSchema` (forward ref). `@field_validator("template")` rejects a `SequenceStepSchema` or `IndexedStepSchema` template. No `inputs`/`outputs`/`id` — `@model_validator(mode="before")` raises on those, preserving `check_indexed_step`'s messages. |

```python
AnyStepSchema = Annotated[
    Union[PythonModuleStepSchema, UserInteractionStepSchema, UserWriteStepSchema,
          UserLoadingStepSchema, WaitStepSchema, SequenceStepSchema, IndexedStepSchema],
    Field(discriminator="steptype")
]
IndexedStepSchema.model_rebuild()  # resolve forward reference
```

**Input validation:** `inputs: dict[str, Any]` with a `@field_validator` that rejects
a mapping entry that has no `type`, an unknown `type`, or a missing `global_name`
(mirrors `validator._check_mappings`). Non-mapping values are literal — accepted as-is.

**Output validation:** `outputs: dict[str, OutputEntry]` — the discriminated union
handles it; unknown types produce a clear Pydantic error.

### 4. Sequence and Header models

```python
class SequenceSchema(BaseModel):
    sequence_name: str
    description: str = ""
    steps: list[AnyStepSchema]          # @field_validator: must be non-empty
    teardown_steps: list[AnyStepSchema] = []

class HeaderSchema(BaseModel):
    name: str
    version: str
    description: str = ""
    main_sequence: str = ""
    globals: dict[str, Any] = {}
    report_metadata: list[str] = ["serial_number"]
    # @field_validator: each entry must be a non-empty string
```

`model_config = ConfigDict(extra="ignore")` on all models — unknown YAML keys pass
through (same as today). **Exception:** `SequenceStepSchema` and `IndexedStepSchema`
use explicit `@model_validator(mode="before")` to raise on specific refused keys
(`step_name`, `inputs`, `outputs`, `id`) rather than silently dropping them.
This preserves the existing error messages from `sequence_step.check_sequence_step`
and `indexed_step.check_indexed_step`.

---

## Pipeline Changes (`recipe_parser.py`)

### Normalization extended

`_normalize_step` is widened to also lowercase the `steptype` **value**:

```python
if isinstance(step_data.get("steptype"), str):
    step_data["steptype"] = step_data["steptype"].lower()
```

This is required for Pydantic's `Literal["pythonmodule"]` discriminator to match
`steptype: PythonModule` from the YAML. Keys were already lowercased; this brings
values into line.

### Validation (replaces `validator.py` call)

```python
def _validate_schema(
    raw: dict, schema_cls: type[BaseModel], context: str
) -> tuple[list[str], BaseModel | None]:
    """Try model_validate; return (problems, None) on failure or ([], schema) on success."""
    try:
        return [], schema_cls.model_validate(raw)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            problems.append(f"{context}: {loc}: {err['msg']}")
        return problems, None
```

Called for the header and for each sequence document independently. All problems
are collected; a non-empty list raises one `RecipeError` naming them all.

### `apply_defaults` removed

Pydantic field defaults replace this function. After successful validation, the
schema object already has defaults filled in. `model_dump()` is called to obtain
a plain dict for the existing expand + build pipeline.

### Unchanged pipeline stages

Version check, indexed step expansion (`indexed_step.expand_indexed_step`), and
all of `_build_sequence` / `_build_step_or_refuse` / `_called_sequence` are
**untouched**. They receive the same `dict[str, Any]` shape as today.

---

## Error Format

Pydantic errors are formatted as:

```
<context>: <loc path>: <Pydantic msg>
```

Example for a missing `wait_time` on the first step of sequence `"Main"`:
```
sequence 'Main': steps -> 0 -> wait_time: Field required
```

All problems across all documents are still raised in a single `RecipeError`.

---

## Consumer Updates

All files currently importing from `pypts.recipe.rules` switch to
`pypts.recipe.recipe_schema`. Constant names are identical, so every import
becomes a one-line change:

```python
# before
from pypts.recipe.rules import STEP_TYPE_REQUIRED, INPUT_TYPES, OUTPUT_TYPES

# after
from pypts.recipe.recipe_schema import STEP_TYPE_REQUIRED, INPUT_TYPES, OUTPUT_TYPES
```

Affected: `step_source.py`, `rc_model.py`, `rc_widgets.py`, `recipe_creator_new.py`,
`verificator.py`, `test_step.py`, `test_rc_model.py`.

---

## Dependency

Add to `pyproject.toml` `[project] dependencies`:

```toml
"pydantic>=2.0",
```

---

## Quality Gates

Before the task is done:

1. `pytest tests` — all existing recipe tests pass
2. `ruff check src tests` — no new violations
3. `mypy` — no new errors
4. `recipe.md` updated to reference `recipe_schema.py` and note deletion of
   `rules.py` and `validator.py`
