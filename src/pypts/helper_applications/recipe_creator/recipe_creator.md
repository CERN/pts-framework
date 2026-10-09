# recipe_creator module

The Recipe Creator application, and the verificator it is the only user of.

The verificator lived in a sibling `recipe_verificator/` package until
2026-09-16. Nothing in the framework ever imported it — only this application
did — so it moved in here, and everything the Creator owns is now in one
folder. Its import path is `pypts.helper_applications.recipe_creator`.

## What the verificator does

Validates a recipe YAML file or string and returns **every problem found in one
pass** — no bail-out on first error. The result is a `list[ValidationIssue]`,
each carrying a severity, a location, a short message, a fix hint, and a line
number.

**The verdict is the framework's.** Errors come from the framework's own
validation — `recipe_parser.validate_document()` against `HeaderSchema` /
`SequenceSchema` in `recipe/recipe_schema.py` — worded exactly as the framework
words them. Once those pass, the verificator runs the framework's real load,
`recipe_parser.parse_recipe(content, check_version=False)`, and a `RecipeError`
from it (a `select` that is neither file nor folder, an empty `method_name`, a
call of a sequence that does not exist or of the main sequence) is one more
error. So a recipe verifies without errors exactly when the framework would
load it. `check_version=False` keeps the framework's version check — a log line
for the technician — out of a check that runs on every edit.

What is the verificator's own: the line of every issue (`_LineMap.nearest()` —
a missing field points at the step or document it is missing from), the hint
(`_hint()`, chosen by where the problem is and Pydantic's error type), the
structural pre-checks (not YAML, empty, a document that is not a mapping, a
first document that is not a header), the cross-document checks (duplicate
sequence names, `main_sequence` naming nothing — both also refused by the
load, but named here with a hint and alongside everything else), and the
warnings: what loads but looks wrong.

## Files

| File | Owns |
|---|---|
| `recipe_creator_new.py` | Entry point and main window — what `__main__.py` runs |
| `rc_model.py` | `RecipeModel` and the `QUndoCommand` subclasses |
| `rc_widgets.py` | The custom widgets |
| `customGUIModules.py` | Editor widgets (YAML editor, highlighter) |
| `styles.py` | Light and dark stylesheets |
| `recipe_creator.py` | **Dead code.** `__main__.py` runs `recipe_creator_new.py` |
| `issue.py` | `ValidationIssue` dataclass — the single result type |
| `verificator.py` | Validation pipeline: `verify_file(path)` and `verify_string(content)` |
| `__init__.py` | Public exports: `ValidationIssue`, `verify_file`, `verify_string` |
| `verification_rule_alignment.html` | Why the verificator's rules drifted from the framework's, and what was done about it |

## Case is the framework's business, not ours

The recipe language is **case-insensitive**: `Step_Name:` loads and runs exactly
as `step_name:` does. The verificator does not implement that rule — it calls
`recipe_parser.normalize_header()` and `normalize_sequence()` in `_run`, before
anything is checked, and compares sequence names and `main_sequence`
lowercased, the way `recipe_parser.parse_recipe()` does.

**Do not reimplement normalization here.** A second copy of that rule is exactly
what drifted: the verificator used to read raw keys and reported "missing
required field" for fields that were plainly present. See
`verification_rule_alignment.html` and
`tests/unit_tests/test_verificator_case_insensitivity.py`.

`_LineMap` keeps an exact-case map **and** a lowercased fallback, exact matches
first. Without the fallback a mixed-case recipe would get every verdict right
and lose every line number, emptying the error gutter. Exact-first matters
because `inputs`/`outputs` entry names keep their case while the language's own
keys do not.

## The sync rule — **read this before touching either module**

There is no second copy of the format rules to keep in step: the verificator
validates with the framework's models and loads with the framework's parser.
What still has to follow a format change by hand is **wording**:

- A new step type → a hint in `_step_field_hint` for each required field, and a
  rename entry in `_unknown_steptype_hint` if it replaces an old name. Its valid
  keys come from `recipe_schema.STEP_SCHEMAS` by themselves.
- A new input or output type → a hint branch in `_input_type_hint`, or in
  `_output_type_hint` and `_output_unknown_type_hint`.
- A new header or sequence field → a hint in `_DOCUMENT_FIELD_HINTS`.
- A sequence key removed from the format → an entry in `_REMOVED_SEQUENCE_KEYS`,
  so authors get a targeted warning instead of a generic "unknown key" one.

A missing hint is never a wrong verdict — the fallback hint points at
`recipe_guide.html`.

## Public API

```python
from pypts.helper_applications.recipe_creator import (
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
issue.field     # where: "header", "sequence 'Main', steps[1] 'Pause'", "recipe" (a load
                #   refusal); a warning keeps the dotted form "sequence 'Main'.locals"
issue.message   # what is wrong; for an error, `f"{field}: {message}"` is the framework's sentence
issue.hint      # fix suggestion, with a YAML example where useful
issue.line      # 1-based line number in the YAML source, or None
issue.is_error  # True if severity == "error"
issue.is_warning
str(issue)      # "[ERROR] (line 2) header: version: Field required"
```

## Integration with recipe_creator

`recipe_creator` calls `verify_string(content)` on every edit and `verify_file`
on save. It gets back a `list[ValidationIssue]` and is responsible for rendering
them (e.g., showing `message` in an error list and `hint` in a detail panel).
The verificator never prints to stdout.

## What is checked

**Errors — whatever the framework refuses:** everything `HeaderSchema` and
`SequenceSchema` check (`recipe/recipe.md`, Format rules: required fields, value
types, unknown step keys, the input/output vocabulary, Sequence and Indexed step
shapes), then everything the framework's load refuses. Plus duplicate sequence
names and a `main_sequence` that names nothing, named with a hint.

**Warnings — what loads but looks wrong:** a `version` written as a number, an
empty `name`/`version`, a removed sequence key (`setup_steps`, `parameters`,
`outputs`, `locals`), an unknown sequence key (ignored by the framework).

## Known limitations

- A load refusal (pass 6) has no line: the framework's `RecipeError` names the
  sequence and step in its text, counted after Indexed expansion.
- Load refusals are found one at a time, and only once every validation error
  is fixed — the framework's load stops at its first problem.
- Global variable forward-reference checking (warning when a `{type: global}`
  input names a variable not in `globals`) is not implemented; an earlier step
  may set it dynamically.
- `image_path` existence on disk is not checked.
