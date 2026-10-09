# Pydantic Recipe Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `rules.py` + `validator.py` in the recipe module with a Pydantic schema that validates YAML recipe dicts; `Recipe`, `Sequence`, and `Step` remain plain classes unchanged.

**Architecture:** A new `recipe_schema.py` holds all constants (moved from `rules.py`) and Pydantic models (`HeaderSchema`, `SequenceSchema`, discriminated-union step schemas). `recipe_parser.py` calls `model_validate()` on each normalized document and collects all `ValidationError`s into one `RecipeError`. After successful validation, `model_dump()` produces defaulted plain dicts that feed unchanged into the existing expand-and-build pipeline.

**Tech Stack:** Pydantic ≥ 2.0, Python 3.11+, PyYAML (unchanged), pytest

## Status & Resume

- **Design spec (approved):** `docs/superpowers/specs/2026-10-07-pydantic-recipe-schema-design.md` (commit `4b5f896`). The spec is the authority on the design; this plan implements it.
- **Branch:** `architecture_refactor`.
- **Execution state: implemented 2026-10-08, uncommitted** (the user commits). Every step is ticked except the `Commit` steps. The code deviates from this plan's listings on the user's decisions of 2026-10-08: steps refuse unknown keys and accept `id`; an Indexed template may omit `step_name`; numbers are read as text in text fields while mapping keys and global names stay as written; sequences are handed on as `model_dump(exclude_unset=True)`; errors are Pydantic's messages with a readable location (`recipe_parser._describe_problem`). `recipe/recipe.md` describes the result, and the status file has it as §1.52.
- **To resume on any machine:** open this file and run the superpowers:subagent-driven-development skill (or superpowers:executing-plans) on it, starting at the first task with unchecked steps. Tasks must run in order — each builds on the previous one.
- The SDD scratch workspace (`.superpowers/sdd/…`) is git-ignored and machine-local; it is recreated automatically and holds nothing that is not also recoverable from this file and `git log`.

## Global Constraints

- Python ≥ 3.11 required
- Pydantic V2 API only (`model_validate`, `model_dump`, `@field_validator`, `@model_validator`, `ConfigDict`)
- `ruff check src tests` must pass — line length 100, `G004` forbids f-strings in logging
- `mypy` must pass — scope in `[tool.mypy]` in `pyproject.toml`
- `pytest tests` must pass after every task
- `Recipe`, `Sequence`, `Step`, and all of `step/`, `core/`, `sequencer/`, `hmi/` are untouched
- All new tests go in `tests/unit_tests/`
- Bare YAML keys produce `None` — all optional Pydantic fields need `@model_validator(mode="before")` to convert `None` to their default
- `model_config = ConfigDict(extra="ignore")` on all models (unknown YAML keys pass through)
- Exception: `SequenceStepSchema` and `IndexedStepSchema` must explicitly reject certain keys via `@model_validator(mode="before")` (see Task 3)
- Constant names in `recipe_schema.py` are **identical** to those in `rules.py` — no renames

---

### Task 1: Add pydantic to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `pydantic` importable in all subsequent tasks

- [x] **Step 1: Add pydantic to dependencies**

In `pyproject.toml`, in the `[project] dependencies` list (currently ends with `"paramiko"`), add:

```toml
dependencies = [
  "hightime==0.2.2",
  "matplotlib",
  "nidmm==1.4.8",
  "nptdms==1.10.0",
  "numpy",
  "platformdirs",
  "PySide6==6.9.1",
  "pydantic>=2.0",
  "PyYAML==6.0.2",
  "ruamel.yaml",
  "pyserial",
  "paramiko"
]
```

- [x] **Step 2: Install and verify**

```bash
pip install -e ".[dev]"
python -c "import pydantic; print(pydantic.VERSION)"
```

Expected: Pydantic 2.x version printed.

- [x] **Step 3: Run tests to confirm baseline is green**

```bash
pytest tests -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add pydantic>=2.0"
```

---

### Task 2: Create recipe_schema.py — constants only

**Files:**
- Create: `src/pypts/recipe/recipe_schema.py`

**Interfaces:**
- Produces: All constants from `rules.py` available as `from pypts.recipe.recipe_schema import <NAME>`
- `rules.py` is **not touched** in this task — it stays as-is

- [x] **Step 1: Create recipe_schema.py with the constants block**

Create `src/pypts/recipe/recipe_schema.py` with exactly this content (constants copied verbatim from `rules.py`, Pydantic models to follow in later tasks):

```python
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Recipe schema: the format constants and Pydantic models for validating raw
recipe YAML dicts.

Constants keep the same names as the old rules.py so that consumer imports
are a one-line change.  Models are used only by recipe_parser.py; nothing
outside the recipe module depends on Pydantic.
"""

from typing import Any

################################ CONSTANTS ################################
# (moved verbatim from rules.py)

HEADER_REQUIRED: tuple[str, ...] = ("name", "version")

HEADER_SINGLE_VALUE: tuple[str, ...] = ("name", "version", "description", "main_sequence")

REPORT_METADATA_DEFAULT: tuple[str, ...] = ("serial_number",)

HEADER_DEFAULTS: dict[str, Any] = {
    "description": "",
    "main_sequence": "",
    "globals": {},
    "report_metadata": REPORT_METADATA_DEFAULT,
}

SEQUENCE_REQUIRED: tuple[str, ...] = ("sequence_name", "steps")

SEQUENCE_DEFAULTS: dict[str, Any] = {
    "description": "",
    "teardown_steps": [],
}

STEP_REQUIRED: tuple[str, ...] = ("steptype", "step_name")

UNNAMED_STEP_TYPES: tuple[str, ...] = ("sequence",)

EXPANDED_STEP_TYPES: tuple[str, ...] = ("indexed",)

STEP_TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "pythonmodule": ("module", "method_name"),
    "userinteraction": ("message", "options"),
    "userwrite": ("message",),
    "userloading": ("message",),
    "wait": ("wait_time",),
    "sequence": ("sequence_name",),
    "indexed": ("template", "parameter_sets"),
}

INPUT_TYPES: dict[str, tuple[str, ...]] = {
    "global": ("global_name",),
}

OUTPUT_TYPES: dict[str, tuple[str, ...]] = {
    "pass": (),
    "passfail": (),
    "equals": ("value",),
    "range": ("min", "max"),
    "global": ("global_name",),
}

STEP_COMMON_DEFAULTS: dict[str, Any] = {
    "description": "",
    "skip": False,
    "continue_on_error": True,
}

STEP_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "pythonmodule": {"inputs": {}, "outputs": {}},
    "userinteraction": {"image_path": None, "outputs": {}},
    "userwrite": {"image_path": None, "outputs": {}},
    "userloading": {"select": "file", "image_path": None, "outputs": {}},
    "wait": {},
    "sequence": {},
    "indexed": {},
}
```

- [x] **Step 2: Verify the constants are importable**

```bash
python -c "from pypts.recipe.recipe_schema import STEP_TYPE_REQUIRED; print(list(STEP_TYPE_REQUIRED))"
```

Expected: prints the list of steptypes.

- [x] **Step 3: Run tests**

```bash
pytest tests -q
```

Expected: all pass (rules.py is still intact; this is additive).

- [ ] **Step 4: Commit**

```bash
git add src/pypts/recipe/recipe_schema.py
git commit -m "feat(recipe): add recipe_schema.py with constants"
```

---

### Task 3: Add Pydantic models to recipe_schema.py

**Files:**
- Modify: `src/pypts/recipe/recipe_schema.py`
- Create: `tests/unit_tests/test_recipe_schema.py`

**Interfaces:**
- Produces:
  - `HeaderSchema` — `model_validate(dict) -> HeaderSchema`
  - `SequenceSchema` — `model_validate(dict) -> SequenceSchema`
  - `AnyStepSchema` — type alias for the discriminated step union
  - All schema classes have `.model_dump() -> dict[str, Any]`

- [x] **Step 1: Write failing tests for HeaderSchema**

Create `tests/unit_tests/test_recipe_schema.py`:

```python
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Unit tests for recipe_schema.py Pydantic models."""

import pytest
from pydantic import ValidationError

from pypts.recipe.recipe_schema import (
    HeaderSchema,
    SequenceSchema,
)


# ── HeaderSchema ──────────────────────────────────────────────────────────────

def test_header_valid_minimal():
    h = HeaderSchema.model_validate({"name": "Demo", "version": "0.2"})
    assert h.name == "Demo"
    assert h.version == "0.2"
    assert h.description == ""
    assert h.main_sequence == ""
    assert h.globals == {}
    assert list(h.report_metadata) == ["serial_number"]


def test_header_missing_name_raises():
    with pytest.raises(ValidationError) as exc_info:
        HeaderSchema.model_validate({"version": "0.2"})
    assert "name" in str(exc_info.value)


def test_header_missing_version_raises():
    with pytest.raises(ValidationError) as exc_info:
        HeaderSchema.model_validate({"name": "Demo"})
    assert "version" in str(exc_info.value)


def test_header_bare_description_becomes_empty_string():
    # bare YAML key -> None -> should default to ""
    h = HeaderSchema.model_validate({"name": "X", "version": "0.2", "description": None})
    assert h.description == ""


def test_header_bare_globals_becomes_empty_dict():
    h = HeaderSchema.model_validate({"name": "X", "version": "0.2", "globals": None})
    assert h.globals == {}


def test_header_bare_report_metadata_becomes_default():
    h = HeaderSchema.model_validate({"name": "X", "version": "0.2", "report_metadata": None})
    assert list(h.report_metadata) == ["serial_number"]


def test_header_globals_must_be_a_dict():
    with pytest.raises(ValidationError):
        HeaderSchema.model_validate({"name": "X", "version": "0.2", "globals": 5})


def test_header_report_metadata_entries_must_be_nonempty_strings():
    with pytest.raises(ValidationError):
        HeaderSchema.model_validate(
            {"name": "X", "version": "0.2", "report_metadata": [""]}
        )


def test_header_unknown_keys_are_ignored():
    h = HeaderSchema.model_validate({"name": "X", "version": "0.2", "bogus_key": "hello"})
    assert h.name == "X"


# ── SequenceSchema ────────────────────────────────────────────────────────────

def _wait_step_dict(name: str = "w") -> dict:
    return {"steptype": "wait", "step_name": name, "wait_time": "1"}


def test_sequence_valid_minimal():
    s = SequenceSchema.model_validate(
        {"sequence_name": "Main", "steps": [_wait_step_dict()]}
    )
    assert s.sequence_name == "Main"
    assert s.description == ""
    assert s.teardown_steps == []
    assert len(s.steps) == 1


def test_sequence_empty_steps_raises():
    with pytest.raises(ValidationError) as exc_info:
        SequenceSchema.model_validate({"sequence_name": "Main", "steps": []})
    assert "steps" in str(exc_info.value)


def test_sequence_missing_sequence_name_raises():
    with pytest.raises(ValidationError):
        SequenceSchema.model_validate({"steps": [_wait_step_dict()]})


def test_sequence_bare_teardown_steps_becomes_empty_list():
    s = SequenceSchema.model_validate(
        {"sequence_name": "Main", "steps": [_wait_step_dict()], "teardown_steps": None}
    )
    assert s.teardown_steps == []
```

- [x] **Step 2: Run tests — confirm they fail (HeaderSchema, SequenceSchema not yet defined)**

```bash
pytest tests/unit_tests/test_recipe_schema.py -q
```

Expected: ImportError or NameError — `HeaderSchema` / `SequenceSchema` not found.

- [x] **Step 3: Add output entry models and step models to recipe_schema.py**

Append the following to the bottom of `src/pypts/recipe/recipe_schema.py`, after the constants block:

```python
################################ PYDANTIC MODELS ################################

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

__all__ = [
    # constants
    "HEADER_REQUIRED", "HEADER_SINGLE_VALUE", "REPORT_METADATA_DEFAULT",
    "HEADER_DEFAULTS", "SEQUENCE_REQUIRED", "SEQUENCE_DEFAULTS",
    "STEP_REQUIRED", "UNNAMED_STEP_TYPES", "EXPANDED_STEP_TYPES",
    "STEP_TYPE_REQUIRED", "STEP_TYPE_DEFAULTS", "STEP_COMMON_DEFAULTS",
    "INPUT_TYPES", "OUTPUT_TYPES",
    # models
    "HeaderSchema", "SequenceSchema", "AnyStepSchema",
    "PythonModuleStepSchema", "UserInteractionStepSchema", "UserWriteStepSchema",
    "UserLoadingStepSchema", "WaitStepSchema", "SequenceStepSchema", "IndexedStepSchema",
    "ValidationError",
]

_COMMON_CONFIG = ConfigDict(extra="ignore")


# ── Output entry models ───────────────────────────────────────────────────────

class PassOutputEntry(BaseModel):
    model_config = _COMMON_CONFIG
    type: Literal["pass"]


class PassfailOutputEntry(BaseModel):
    model_config = _COMMON_CONFIG
    type: Literal["passfail"]


class EqualsOutputEntry(BaseModel):
    model_config = _COMMON_CONFIG
    type: Literal["equals"]
    value: Any


class RangeOutputEntry(BaseModel):
    model_config = _COMMON_CONFIG
    type: Literal["range"]
    min: Any
    max: Any


class GlobalOutputEntry(BaseModel):
    model_config = _COMMON_CONFIG
    type: Literal["global"]
    global_name: str


OutputEntry = Annotated[
    Union[
        PassOutputEntry,
        PassfailOutputEntry,
        EqualsOutputEntry,
        RangeOutputEntry,
        GlobalOutputEntry,
    ],
    Field(discriminator="type"),
]


# ── Input validation helper ───────────────────────────────────────────────────

def _validate_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate inputs entries: literal values pass; mappings must have a known type."""
    known = ", ".join(sorted(INPUT_TYPES))
    for entry_name, config in inputs.items():
        if not isinstance(config, dict):
            continue  # literal value - accepted as-is
        declared = config.get("type")
        if declared is None:
            raise ValueError(
                f"inputs '{entry_name}': a mapping names a 'type' ({known}). "
                f"A literal value is written as itself: `{entry_name}: <the value>`."
            )
        required = INPUT_TYPES.get(str(declared).lower())
        if required is None:
            raise ValueError(
                f"inputs '{entry_name}': unknown type '{declared}'. Available: {known}"
            )
        for key in required:
            if config.get(key) is None:
                raise ValueError(
                    f"inputs '{entry_name}': a '{declared}' entry needs '{key}'"
                )
    return inputs


# ── Common step fields ────────────────────────────────────────────────────────

class CommonStepFields(BaseModel):
    model_config = _COMMON_CONFIG
    description: str = ""
    skip: bool = False
    continue_on_error: bool = True

    @model_validator(mode="before")
    @classmethod
    def _none_to_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        if result.get("description") is None:
            result["description"] = ""
        if "inputs" in result and result["inputs"] is None:
            result["inputs"] = {}
        if "outputs" in result and result["outputs"] is None:
            result["outputs"] = {}
        return result


# ── Per-steptype models ───────────────────────────────────────────────────────

class PythonModuleStepSchema(CommonStepFields):
    steptype: Literal["pythonmodule"]
    step_name: str
    module: str
    method_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, OutputEntry] = Field(default_factory=dict)

    @field_validator("inputs", mode="before")
    @classmethod
    def _check_inputs(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            raise ValueError("'inputs' must be a mapping of names to values")
        return _validate_inputs(v)


class UserInteractionStepSchema(CommonStepFields):
    steptype: Literal["userinteraction"]
    step_name: str
    message: str
    options: Any
    image_path: str | None = None
    outputs: dict[str, OutputEntry] = Field(default_factory=dict)


class UserWriteStepSchema(CommonStepFields):
    steptype: Literal["userwrite"]
    step_name: str
    message: str
    image_path: str | None = None
    outputs: dict[str, OutputEntry] = Field(default_factory=dict)


class UserLoadingStepSchema(CommonStepFields):
    steptype: Literal["userloading"]
    step_name: str
    message: str
    select: str = "file"
    image_path: str | None = None
    outputs: dict[str, OutputEntry] = Field(default_factory=dict)


class WaitStepSchema(CommonStepFields):
    steptype: Literal["wait"]
    step_name: str
    wait_time: Any


class SequenceStepSchema(CommonStepFields):
    steptype: Literal["sequence"]
    sequence_name: str

    @model_validator(mode="before")
    @classmethod
    def _refuse_forbidden_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        _REFUSED = {
            "step_name": (
                "a Sequence step is named after the sequence it calls "
                "and cannot carry 'step_name'"
            ),
            "inputs": (
                "a Sequence step cannot carry 'inputs': "
                "a called sequence shares the run's globals"
            ),
            "outputs": (
                "a Sequence step cannot carry 'outputs': "
                "its verdict is the verdict of its steps"
            ),
            "id": (
                "a Sequence step cannot carry an 'id': "
                "every call gets ids of its own"
            ),
        }
        errors = [msg for key, msg in _REFUSED.items() if data.get(key) is not None]
        if errors:
            raise ValueError("; ".join(errors))
        return data


class IndexedStepSchema(CommonStepFields):
    steptype: Literal["indexed"]
    step_name: str
    template: "AnyStepSchema"  # forward reference resolved by model_rebuild() below
    parameter_sets: list[dict[str, Any]]

    @model_validator(mode="before")
    @classmethod
    def _refuse_forbidden_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        errors = []
        if data.get("id") is not None:
            errors.append(
                "an indexed step becomes several steps and cannot carry an 'id'"
            )
        for key in ("inputs", "outputs"):
            if data.get(key) is not None:
                errors.append(
                    f"'{key}' belongs on the 'template', not on the indexed step itself"
                )
        if errors:
            raise ValueError("; ".join(errors))
        return data

    @field_validator("template", mode="after")
    @classmethod
    def _refuse_sequence_or_indexed_template(cls, v: Any) -> Any:
        if isinstance(v, SequenceStepSchema):
            raise ValueError(
                "a Sequence step cannot be the 'template': a sequence is a group "
                "of steps and indexed parametrizes a single step"
            )
        if isinstance(v, IndexedStepSchema):
            raise ValueError("an indexed step cannot be the 'template'")
        return v


AnyStepSchema = Annotated[
    Union[
        PythonModuleStepSchema,
        UserInteractionStepSchema,
        UserWriteStepSchema,
        UserLoadingStepSchema,
        WaitStepSchema,
        SequenceStepSchema,
        IndexedStepSchema,
    ],
    Field(discriminator="steptype"),
]

IndexedStepSchema.model_rebuild()


# ── SequenceSchema and HeaderSchema ───────────────────────────────────────────

class SequenceSchema(BaseModel):
    model_config = _COMMON_CONFIG
    sequence_name: str
    description: str = ""
    steps: list[AnyStepSchema]
    teardown_steps: list[AnyStepSchema] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _none_to_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        if result.get("description") is None:
            result["description"] = ""
        if "teardown_steps" in result and result["teardown_steps"] is None:
            result["teardown_steps"] = []
        return result

    @field_validator("steps")
    @classmethod
    def _steps_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("'steps' must contain at least one step")
        return v


class HeaderSchema(BaseModel):
    model_config = _COMMON_CONFIG
    name: str
    version: str
    description: str = ""
    main_sequence: str = ""
    globals: dict[str, Any] = Field(default_factory=dict)
    report_metadata: list[str] = Field(
        default_factory=lambda: list(REPORT_METADATA_DEFAULT)
    )

    @model_validator(mode="before")
    @classmethod
    def _none_to_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for key, default in (
            ("description", ""),
            ("main_sequence", ""),
        ):
            if result.get(key) is None:
                result[key] = default
        if result.get("globals") is None:
            result["globals"] = {}
        if "report_metadata" in result and result["report_metadata"] is None:
            result["report_metadata"] = list(REPORT_METADATA_DEFAULT)
        return result

    @field_validator("report_metadata")
    @classmethod
    def _validate_report_metadata(cls, v: list[str]) -> list[str]:
        for name in v:
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    f"report_metadata entry {name!r} is not a non-empty global name"
                )
        return v
```

- [x] **Step 4: Run the failing tests — confirm they pass now**

```bash
pytest tests/unit_tests/test_recipe_schema.py -q
```

Expected: all pass.

- [x] **Step 5: Extend test_recipe_schema.py with step model tests**

Append to `tests/unit_tests/test_recipe_schema.py`:

```python
from pypts.recipe.recipe_schema import (
    AnyStepSchema,
    IndexedStepSchema,
    PythonModuleStepSchema,
    SequenceStepSchema,
    WaitStepSchema,
)

# ── Step model — discriminated union ─────────────────────────────────────────

def test_wait_step_parses_correctly():
    raw = {"steptype": "wait", "step_name": "Pause", "wait_time": "2.5"}
    s = SequenceSchema.model_validate({"sequence_name": "M", "steps": [raw]})
    step = s.steps[0]
    assert isinstance(step, WaitStepSchema)
    assert step.step_name == "Pause"
    assert step.wait_time == "2.5"


def test_python_module_step_requires_module_and_method():
    with pytest.raises(ValidationError):
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{"steptype": "pythonmodule", "step_name": "x"}],
        })


def test_unknown_steptype_raises():
    with pytest.raises(ValidationError):
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{"steptype": "bogus", "step_name": "x"}],
        })


def test_sequence_step_refused_keys_step_name():
    with pytest.raises(ValidationError) as exc_info:
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{"steptype": "sequence", "sequence_name": "Other", "step_name": "bad"}],
        })
    assert "step_name" in str(exc_info.value)


def test_sequence_step_refused_keys_inputs():
    with pytest.raises(ValidationError) as exc_info:
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{"steptype": "sequence", "sequence_name": "Other", "inputs": {"x": 1}}],
        })
    assert "inputs" in str(exc_info.value)


def test_indexed_step_refused_inputs():
    with pytest.raises(ValidationError) as exc_info:
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{
                "steptype": "indexed",
                "step_name": "Loop",
                "inputs": {"x": 1},
                "template": {"steptype": "wait", "step_name": "t", "wait_time": "1"},
                "parameter_sets": [{}],
            }],
        })
    assert "inputs" in str(exc_info.value)


def test_indexed_step_refuses_sequence_template():
    with pytest.raises(ValidationError) as exc_info:
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{
                "steptype": "indexed",
                "step_name": "Loop",
                "template": {"steptype": "sequence", "sequence_name": "Other"},
                "parameter_sets": [{}],
            }],
        })
    assert "sequence" in str(exc_info.value).lower()


def test_outputs_unknown_type_raises():
    with pytest.raises(ValidationError):
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{
                "steptype": "pythonmodule",
                "step_name": "x",
                "module": "m",
                "method_name": "f",
                "outputs": {"result": {"type": "bogus_type"}},
            }],
        })


def test_inputs_global_entry_requires_global_name():
    with pytest.raises(ValidationError):
        SequenceSchema.model_validate({
            "sequence_name": "M",
            "steps": [{
                "steptype": "pythonmodule",
                "step_name": "x",
                "module": "m",
                "method_name": "f",
                "inputs": {"val": {"type": "global"}},  # missing global_name
            }],
        })


def test_inputs_literal_value_is_accepted():
    s = SequenceSchema.model_validate({
        "sequence_name": "M",
        "steps": [{
            "steptype": "pythonmodule",
            "step_name": "x",
            "module": "m",
            "method_name": "f",
            "inputs": {"limit": 42},
        }],
    })
    assert s.steps[0].inputs["limit"] == 42


def test_model_dump_produces_plain_dicts():
    s = SequenceSchema.model_validate({
        "sequence_name": "Main",
        "steps": [{"steptype": "wait", "step_name": "w", "wait_time": "1"}],
    })
    dumped = s.model_dump()
    assert isinstance(dumped, dict)
    assert isinstance(dumped["steps"][0], dict)
    assert dumped["steps"][0]["steptype"] == "wait"
    assert dumped["steps"][0]["description"] == ""
    assert dumped["teardown_steps"] == []
```

- [x] **Step 6: Run all new tests**

```bash
pytest tests/unit_tests/test_recipe_schema.py -v
```

Expected: all pass.

- [x] **Step 7: Run the full test suite**

```bash
pytest tests -q
```

Expected: all pass (rules.py and validator.py untouched).

- [x] **Step 8: Ruff and mypy**

```bash
ruff check src/pypts/recipe/recipe_schema.py tests/unit_tests/test_recipe_schema.py
mypy
```

Expected: no errors. Fix any that appear.

- [ ] **Step 9: Commit**

```bash
git add src/pypts/recipe/recipe_schema.py tests/unit_tests/test_recipe_schema.py
git commit -m "feat(recipe): add Pydantic models to recipe_schema.py"
```

---

### Task 4: Wire recipe_parser.py to use Pydantic; delete validator.py

**Files:**
- Modify: `src/pypts/recipe/recipe_parser.py`
- Delete: `src/pypts/recipe/validator.py`

**Interfaces:**
- Consumes: `HeaderSchema`, `SequenceSchema`, `ValidationError` from `recipe_schema`
- Produces: same `Recipe` object as before — no external interface change

The key changes to `parse_recipe`:
1. `_normalize_step` — also lowercase the `steptype` **value** (currently only keys are lowercased)
2. Add `_validate_schema(raw, cls, context)` helper
3. Replace `validator.validate_header` / `validator.validate_sequence` with `_validate_schema` calls
4. After a clean validation, replace `header = apply_defaults(header, HEADER_DEFAULTS)` with `header = header_schema.model_dump()`; replace each sequence doc with `seq_schema.model_dump()`
5. Remove the `_report_metadata` call (inline it as `tuple(header["report_metadata"])`)
6. Remove the import of `validator`

- [x] **Step 1: Write a failing test that proves the new validation path runs**

Add to `tests/unit_tests/test_recipe.py` (find the section with validation tests, e.g., around `test_recipe_is_rejected_when_...`):

```python
def test_steptype_value_is_case_insensitive_PascalCase():
    """PythonModule (Pascal case) must parse the same as pythonmodule (lowercase)."""
    text = f"""\
name: Demo
version: {CURRENT_VERSION}
---
sequence_name: Main
steps:
  - steptype: PythonModule
    step_name: Mod
    module: example_tests.py
    method_name: add
"""
    recipe = Recipe.from_yaml_text(text)
    assert recipe.sequences["Main"].steps[0].name == "Mod"
```

Run:

```bash
pytest tests/unit_tests/test_recipe.py::test_steptype_value_is_case_insensitive_PascalCase -v
```

Expected: PASS (it already passes, because the registry already does `step_type.lower()` in `build_step`). This test pins the behavior we must keep.

- [x] **Step 2: Extend _normalize_step to lowercase the steptype value**

In `src/pypts/recipe/recipe_parser.py`, find `_normalize_step`:

```python
def _normalize_step(step_data: Any) -> Any:
    """One step mapping; anything malformed is left for the validator to name."""
    if not isinstance(step_data, dict):
        return step_data
    step_data = _lowercase_keys(step_data)
    for mapping_name in ("inputs", "outputs"):
        ...
```

Add the steptype value lowercasing **right after** `_lowercase_keys`:

```python
def _normalize_step(step_data: Any) -> Any:
    """One step mapping; anything malformed is left for the validator to name."""
    if not isinstance(step_data, dict):
        return step_data
    step_data = _lowercase_keys(step_data)
    if isinstance(step_data.get("steptype"), str):
        step_data["steptype"] = step_data["steptype"].lower()
    for mapping_name in ("inputs", "outputs"):
        ...
```

- [x] **Step 3: Add the _validate_schema helper to recipe_parser.py**

In `recipe_parser.py`, add this function (place it near the top of the module, after imports):

```python
from pydantic import ValidationError

from pypts.recipe.recipe_schema import HeaderSchema, SequenceSchema

def _validate_schema(
    raw: dict,
    schema_cls: type,
    context: str,
) -> tuple[list[str], object]:
    """
    Try model_validate; return ([], schema) on success or (problems, None) on failure.

    All ValidationError detail lines are formatted as:
        '<context>: <loc path>: <pydantic msg>'
    """
    try:
        return [], schema_cls.model_validate(raw)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = " -> ".join(str(part) for part in err["loc"])
            problems.append(f"{context}: {loc}: {err['msg']}")
        return problems, None
```

- [x] **Step 4: Replace the validator calls in parse_recipe**

Find the current validation block in `parse_recipe` (around lines 76-87):

```python
# Every mandatory-field problem in the whole file, reported at once.
problems = validator.validate_header(header)
sequence_documents = []
for number, document in enumerate(documents[1:], start=2):
    if not isinstance(document, dict):
        problems.append(f"document {number} is not a mapping")
    else:
        document = normalize_sequence(document)
        sequence_documents.append(document)
        problems.extend(validator.validate_sequence(document))
if problems:
    listed = "; ".join(problems)
    raise RecipeError(f"Recipe '{file_name}' is invalid: {listed}")
```

Replace it with:

```python
# Validate every document with Pydantic; collect all problems before raising.
all_problems: list[str] = []
header_schema: HeaderSchema | None
header_probs, header_schema = _validate_schema(header, HeaderSchema, "header")
all_problems.extend(header_probs)

sequence_documents: list[dict] = []
sequence_schemas: list[SequenceSchema | None] = []
for number, document in enumerate(documents[1:], start=2):
    if not isinstance(document, dict):
        all_problems.append(f"document {number} is not a mapping")
        sequence_schemas.append(None)
        continue
    document = normalize_sequence(document)
    seq_name = document.get("sequence_name", f"document {number}")
    seq_probs, seq_schema = _validate_schema(
        document, SequenceSchema, f"sequence '{seq_name}'"
    )
    all_problems.extend(seq_probs)
    sequence_documents.append(document)
    sequence_schemas.append(seq_schema)

if all_problems:
    listed = "; ".join(all_problems)
    raise RecipeError(f"Recipe '{file_name}' is invalid: {listed}")

# Validation passed — replace raw dicts with fully-defaulted model_dump() dicts.
assert header_schema is not None
header = header_schema.model_dump()
sequence_documents = [
    schema.model_dump() for schema in sequence_schemas if schema is not None
]
```

- [x] **Step 5: Remove the apply_defaults(header, ...) call and simplify _report_metadata**

Find and remove this line that comes after the version check:

```python
header = apply_defaults(header, HEADER_DEFAULTS)
```

(It is no longer needed — `header_schema.model_dump()` already applied defaults above.)

Find `_report_metadata(header, file_name)` in `parse_recipe` and replace with:

```python
report_metadata=tuple(header["report_metadata"]),
```

The `_report_metadata` function can now be deleted from `recipe_parser.py` (it is superseded by `HeaderSchema._validate_report_metadata`).

- [x] **Step 6: Remove the import of validator**

Find:

```python
from pypts.recipe import validator
```

Delete this line.

- [x] **Step 7: Run the full test suite**

```bash
pytest tests -q
```

Expected: all pass. If any test references `validator` directly, it will be caught here.

- [x] **Step 8: Delete validator.py**

```bash
git rm src/pypts/recipe/validator.py
```

- [x] **Step 9: Run the full test suite again**

```bash
pytest tests -q
ruff check src tests
mypy
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/pypts/recipe/recipe_parser.py
git commit -m "feat(recipe): wire recipe_parser to Pydantic schema; delete validator.py"
```

---

### Task 5: Migrate all consumer imports from rules.py → recipe_schema.py; delete rules.py

**Files:**
- Modify: `src/pypts/recipe/step_source.py`
- Modify: `src/pypts/helper_applications/recipe_creator/rc_model.py`
- Modify: `src/pypts/helper_applications/recipe_creator/rc_widgets.py`
- Modify: `src/pypts/helper_applications/recipe_creator/recipe_creator_new.py`
- Modify: `src/pypts/helper_applications/recipe_creator/verificator.py`
- Modify: `tests/unit_tests/test_step.py`
- Modify: `tests/unit_tests/test_rc_model.py`
- Delete: `src/pypts/recipe/rules.py`

**Interfaces:**
- Consumes: constants in `recipe_schema.py` (same names as before)

All changes in this task are mechanical one-line import substitutions. The constant names are identical.

- [x] **Step 1: Update step_source.py**

Find:
```python
from pypts.recipe.rules import SEQUENCE_DEFAULTS
```
Replace with:
```python
from pypts.recipe.recipe_schema import SEQUENCE_DEFAULTS
```

- [x] **Step 2: Update rc_model.py**

Find:
```python
from pypts.recipe.rules import (
    STEP_TYPE_REQUIRED,
    STEP_COMMON_DEFAULTS,
    STEP_TYPE_DEFAULTS,
    SEQUENCE_DEFAULTS,
)
```
Replace with:
```python
from pypts.recipe.recipe_schema import (
    STEP_TYPE_REQUIRED,
    STEP_COMMON_DEFAULTS,
    STEP_TYPE_DEFAULTS,
    SEQUENCE_DEFAULTS,
)
```

- [x] **Step 3: Update rc_widgets.py**

Find:
```python
from pypts.recipe.rules import INPUT_TYPES, OUTPUT_TYPES, STEP_TYPE_REQUIRED
```
Replace with:
```python
from pypts.recipe.recipe_schema import INPUT_TYPES, OUTPUT_TYPES, STEP_TYPE_REQUIRED
```

- [x] **Step 4: Update recipe_creator_new.py**

Find:
```python
from pypts.recipe.rules import STEP_TYPE_REQUIRED
```
Replace with:
```python
from pypts.recipe.recipe_schema import STEP_TYPE_REQUIRED
```

- [x] **Step 5: Update verificator.py**

Find:
```python
from pypts.recipe import recipe_parser, rules
```
Replace with:
```python
from pypts.recipe import recipe_parser
from pypts.recipe import recipe_schema as rules
```

This keeps all `rules.SEQUENCE_REQUIRED`, `rules.STEP_TYPE_REQUIRED`, etc. references inside `verificator.py` unchanged — they now read from `recipe_schema` transparently.

- [x] **Step 6: Update test_step.py (two import lines)**

Find (at line ~141):
```python
from pypts.recipe.rules import EXPANDED_STEP_TYPES, STEP_TYPE_REQUIRED
```
And at line ~149:
```python
from pypts.recipe.rules import EXPANDED_STEP_TYPES
```
Replace both with `recipe_schema` imports:
```python
from pypts.recipe.recipe_schema import EXPANDED_STEP_TYPES, STEP_TYPE_REQUIRED
```
```python
from pypts.recipe.recipe_schema import EXPANDED_STEP_TYPES
```

- [x] **Step 7: Update test_rc_model.py**

Find (at line ~231):
```python
from pypts.recipe.rules import STEP_TYPE_REQUIRED
```
Replace with:
```python
from pypts.recipe.recipe_schema import STEP_TYPE_REQUIRED
```

- [x] **Step 8: Run full test suite before deleting rules.py**

```bash
pytest tests -q
ruff check src tests
```

Expected: all pass.

- [x] **Step 9: Delete rules.py**

```bash
git rm src/pypts/recipe/rules.py
```

- [x] **Step 10: Run full test suite after deletion**

```bash
pytest tests -q
ruff check src tests
mypy
```

Expected: all pass. Any remaining `rules` import anywhere will surface as an ImportError.

- [ ] **Step 11: Commit**

```bash
git add -u
git commit -m "refactor(recipe): migrate all rules.py imports to recipe_schema; delete rules.py"
```

---

### Task 6: Update recipe.md documentation

**Files:**
- Modify: `src/pypts/recipe/recipe.md`

- [x] **Step 1: Update the Files table in recipe.md**

In the `## Files` table, replace the `rules.py` and `validator.py` rows:

| Old row | New row |
|---|---|
| `rules.py` — The format rules as data… | Remove entirely |
| `validator.py` — Mandatory-field and shape checks… | Remove entirely |

Add a row for `recipe_schema.py`:
```
| `recipe_schema.py` | The recipe format constants (same names as the old `rules.py`) and Pydantic models (`HeaderSchema`, `SequenceSchema`, `AnyStepSchema` and per-steptype models) used by `recipe_parser.py` for validation. Not imported outside the `recipe/` package except by `recipe_creator/` for the constants. |
```

- [x] **Step 2: Update the load pipeline description**

In `## The load pipeline (recipe_parser.py)`, step 4 currently reads:

> **Validate** (`validator.py`) — header, every sequence, every step. **All problems are collected and raised as one `RecipeError`**…

Replace with:

> **Validate** (`recipe_schema.py`) — `HeaderSchema.model_validate()` on the header, `SequenceSchema.model_validate()` on every sequence document. Each call is wrapped in a try/except; all `ValidationError` detail lines are collected and raised as one `RecipeError`, so the author fixes the file in one round. Defaults are applied as part of validation; `model_dump()` replaces `apply_defaults()`.

- [x] **Step 3: Update the Format rules section**

The section `## Format rules (rules.py)` — change its heading to `## Format rules (recipe_schema.py)` and update the first sentence from "live in `rules.py`" to "live in `recipe_schema.py`".

- [x] **Step 4: Run tests one final time**

```bash
pytest tests -q
ruff check src tests
mypy
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/recipe/recipe.md
git commit -m "docs(recipe): update recipe.md for Pydantic schema migration"
```
