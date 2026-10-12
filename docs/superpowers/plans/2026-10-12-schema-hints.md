# Verificator hints from the recipe schema — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the verificator's per-field, per-steptype and per-output-type wording onto the
recipe schema's Pydantic fields, enforced by a completeness test.

**Architecture:** `Field(description=..., examples=[...])` on every author-writable field of
the models in `recipe/recipe_schema.py`; the type-level sentence on each `steptype` / `type`
tag field; two format-history constants beside them. The verificator keeps its dispatch and
reads text through three helpers.

**Tech Stack:** Python 3.11, Pydantic 2 (installed 2.13.5, pinned `>=2.6`), PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-schema-hints-design.md`

## Global Constraints

- Validation behaviour unchanged: verdicts, error messages, `SchemaProblem`, `recipe_parser`.
- `ValidationIssue` API and `field` / `message` / `line` unchanged; only `hint` wording changes.
- No dependency bump. No commits (the user commits).
- Old-school style: `if`/`else`, named locals, `%`-style logging (none added here).
- Gates: `pytest tests`, `ruff check src tests`, `mypy`, documentation check.

## Review Focus

- A missing field on an Indexed step's **template** — the hint must come from the template's
  steptype model, not `IndexedStepSchema`. (Existing test `test_a_missing_template_gets_the_template_hint`
  covers the wrapper; add one for a template field.)
- An output entry whose name is a number (`1: {type: equals}`) — the generated example must
  use `1` as the name. (Covered by asserting in Task 2.)
- A field with an example that is a nested mapping (Indexed `template`) — rendered as a
  readable YAML block, not a one-line Python repr.
- An unknown steptype that is also a known rename (`WaitStep`) — rename note still shown.
- A removed sequence key — warning hint is the schema constant's sentence verbatim.

---

### Task 1: Schema text + completeness test

**Files:**
- Modify: `src/pypts/recipe/recipe_schema.py`
- Test: `tests/unit_tests/test_recipe_schema.py`

**Produces:** every model field described; `RENAMED_STEP_TYPES: dict[str, str]`,
`REMOVED_SEQUENCE_KEYS: dict[str, str]`, `OUTPUT_SCHEMAS: dict[str, type[BaseModel]]`
(keyed as `OUTPUT_TYPES`), all public in `recipe_schema`.

- [ ] Write `test_every_author_field_is_described`, `test_every_required_field_has_an_example`,
      `test_removed_sequence_keys_are_not_live_fields`, `test_renamed_step_types_are_not_live_steptypes`.
- [ ] Run — FAIL (no descriptions, constants missing).
- [ ] Add `Field(description=..., examples=...)` to every field; add the three constants.
- [ ] Run `pytest tests/unit_tests/test_recipe_schema.py tests/unit_tests/test_recipe.py` — PASS.

### Task 2: Verificator reads the schema

**Files:**
- Modify: `src/pypts/helper_applications/recipe_creator/verificator.py`
- Test: `tests/unit_tests/test_verificator.py`

**Consumes:** Task 1's descriptions and constants.
**Produces:** private helpers `_field_help(model, field) -> str`,
`_output_example(model, entry_name) -> str`, `_type_list(models) -> str`.

- [ ] Update "hints stay" tests to the schema's wording; add Review Focus tests.
- [ ] Run — FAIL.
- [ ] Replace the removed tables (spec §4.3) with the helpers.
- [ ] Run verificator tests + case-insensitivity tests — PASS.

### Task 3: Documentation and gates

**Files:** `recipe_creator/recipe_creator.md`, `recipe/recipe.md`,
`pypts_implementation_status.html`, `TODO.txt`.

- [ ] Rewrite the sync-rule section; update recipe.md extend step 3 and constants list.
- [ ] Status: new section, fix stale verificator row, roadmap TODO for Creator tooltips.
- [ ] Mark the TODO.txt item with a note.
- [ ] `pytest tests`, `ruff check src tests`, `mypy` — all pass.
