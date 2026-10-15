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
a missing field points at the step or document it is missing from), the choice
of hint (`_hint()`, by where the problem is and Pydantic's error type — the
words themselves are the schema's, see the sync rule below), the
structural pre-checks (not YAML, empty, a document that is not a mapping, a
first document that is not a header), the cross-document checks (duplicate
sequence names, `main_sequence` naming nothing — both also refused by the
load, but named here with a hint and alongside everything else), and the
warnings: what loads but looks wrong.

## Files

| File | Owns |
|---|---|
| `recipe_creator_new.py` | Entry point and main window — what `__main__.py` runs |
| `rc_logging.py` | The Creator's own log file and its handler for uncaught errors — see Logging below |
| `rc_model.py` | `RecipeModel` and the `QUndoCommand` subclasses |
| `rc_widgets.py` | The custom widgets, and `creator_stylesheet()` — the Creator's own rules on top of pypts' stylesheet |
| `customGUIModules.py` | Editor widgets (YAML editor, highlighter) |
| `recipe_creator.py` | **Dead code.** `__main__.py` runs `recipe_creator_new.py` |
| `issue.py` | `ValidationIssue` dataclass — the single result type |
| `verificator.py` | Validation pipeline: `verify_file(path)` and `verify_string(content)` |
| `__init__.py` | Public exports: `ValidationIssue`, `verify_file`, `verify_string` |
| `verification_rule_alignment.html` | Why the verificator's rules drifted from the framework's, and what was done about it |

## Logging

The Creator is a separate program: no Logger process, no run log. `main()` calls
`rc_logging.start_logging()` first, which writes
`recipe_creator_<YYYYmmdd_HHMMSS>.log` (`get_log_file_path(..., prefix=LOG_FILE_PREFIX)`)
into `paths.reports_dir` — the default reports folder when there is no configuration — at
DEBUG, and to stdout. In it:

- `Recipe Creator started.` / `Recipe Creator stopped.` (INFO), and every line of the
  window's message box (`_log_msg`) at INFO;
- a failed open or save: ERROR, traceback at DEBUG;
- an exception nobody caught: `sys.excepthook` is `_report_uncaught_error`, which logs
  it (ERROR, traceback at DEBUG) and shows a dialog naming the log file. PySide hands an
  exception raised in a slot to `sys.excepthook` and carries on, so the window stays open;
- a hard crash inside Qt: `faulthandler` writes the Python stack of every thread to the
  same file, through a handle kept open for the program's life.

`start_logging(prefix, program_name)` is shared: the Recipe Editor v2 passes
`"recipe_editor"` and `"Recipe Editor v2"`, which name its log file and its error dialog.

Tests: `tests/unit_tests/test_rc_logging.py` (the hard crash runs in a subprocess).

## Shared with the Recipe Editor v2

`helper_applications/recipe_editor/` builds on this package: `RecipeModel`, `YamlEditor`,
`InvalidOverlay`, `creator_stylesheet()`, `verify_string()` and `rc_logging`. For it:

- `RecipeModel.set_path(document, path, value)` sets one value anywhere in the recipe as one
  undo entry (`DELETE` removes the key); `duplicate_step(seq_idx, step_idx)` inserts a copy
  named "… (copy)" after the step.
- `YamlEditor.set_step_lines(first, last)` tints a step's lines (0-based; -1, -1 for none).
- `YamlEditor` commits (`text_committed`) only text that differs from what it last showed or
  committed. Re-colouring the text — a theme switch, the highlighter — also emits
  `textChanged`, and used to commit the same text as an edit: an "Edit YAML" undo entry and a
  modified recipe right after start-up, in both editors.
- `ValidationIssue.document` (0 the header) and `.path` (e.g. `('steps', 1, 'outputs', 'r',
  'max')`) say where a schema problem is, for the editor's field outlines; both are empty
  (`None`, `()`) for a problem with no field. The Creator does not use them.

A change to any of these is a change to both editors.

## The window

- **Layout.** One vertical splitter: the editors on top take all spare height (the header
  strip and step view on the left, the YAML text on the right, 2 : 3); the bottom strip holds
  the problems (`VerificationPanel`) and the message box (a `QPlainTextEdit`, framed by pypts'
  log style) side by side. The problems panel starts open, opens itself when there are
  issues, and shows ❌ only for errors (⚠️ for warnings alone).
- **Theme.** `get_stylesheet(dark)` from `hmi/gui/styles.py` plus `creator_stylesheet(dark)`
  from `rc_widgets.py`: square text buttons (`_small_button()`, objectName `rcSmallButton`,
  no padding — the shared `QPushButton` padding clipped their glyphs) and framed group boxes.
  Kept out of the shared file on purpose.
- **No recipe yet.** At start-up the model is empty (`RecipeModel.is_empty()`): the tree is
  grayed out under an overlay saying File > New / Open or type in the editor, and Save, Add
  Step, Delete and Validate are disabled. `set_header_field()` ignores an edit then. While the
  text is invalid the same overlay says so instead, and *Undo to Last Valid* appears on the
  toolbar (it is always in the Edit menu).
- **Step types.** The form looks a step's own fields up through
  `recipe_parser.steptype_key()`, so `Wait`, `wait` and `WAIT` all show `wait_time`; the Add
  Step menus list `STEP_TYPE_NAMES` (`PythonModule`, `Wait`, …).

**Never delete a form widget on the spot — `deleteLater()` it.** A field commits its edit
from inside its own signal (`editingFinished`, `currentTextChanged`, `valueChanged`); the
model changes, the views rebuild, and an old form deleted right then frees the widget still
emitting: an access violation that kills the process with no Python traceback. So:

- `_replace_form()` swaps a view's form with `takeWidget()` and `_defer_delete()`, never
  `QScrollArea.setWidget()` over the old one;
- `StepFormWidget` builds its type-specific rows only when the steptype changes (`takeRow()`,
  then `_defer_delete()`), and otherwise refills them — the field being typed in keeps its
  focus;
- List and Panels views rebuild the form only when another step is selected
  (`_form_for`); the form refreshes itself on `model.changed`;
- Card view builds a form only for the open card.

Tests: `tests/unit_tests/test_rc_window.py` — the edits that crashed run in a subprocess,
since a regression would take pytest down with it.

## Case is the framework's business, not ours

The recipe language is **case-insensitive**: `Step_Name:` loads and runs exactly
as `step_name:` does. The verificator does not implement that rule — it calls
`recipe_parser.normalize_header()` and `normalize_sequence()` in `_run`, before
anything is checked, and compares sequence names and `main_sequence`
lowercased, the way `recipe_parser.parse_recipe()` does.

The window follows the same rule: it looks steptypes up through
`recipe_parser.steptype_key()`, never with its own `.lower()`.

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

There is no second copy of the format to keep in step. The verificator
validates with the framework's models, loads with the framework's parser, and
**takes its words from the models too**: every field in `recipe/recipe_schema.py`
carries `Field(description=..., examples=[...])`, and each step type's and
output type's own sentence sits on its `steptype` / `type` tag field
(`recipe/recipe.md`, Format rules). The verificator only decides *which* field
a problem is about. So a new step type, input or output form, or header,
sequence or step field needs no edit here —
`tests/unit_tests/test_recipe_schema.py` fails until every field has its
description, and every required one an example.

Read from the schema, by helper:

- `_field_help(model, field)` — the description, then `Example:` and the first
  example as YAML (`yaml.safe_dump`): a scalar or a list of plain values on one
  line (`options: [Continue, Abort]`), a mapping or a list of mappings as an
  indented block.
- `_output_example(model, entry_name)` — one outputs entry built from an
  `OUTPUT_SCHEMAS` model: its `type` plus each field's first example, under the
  author's own entry name (`r: {type: range, min: 4.9, max: 5.1}`).
- `_type_list(title, models, tag)` — every step type (`STEP_SCHEMAS`) or output
  type (`OUTPUT_SCHEMAS`) with its tag field's description, for an unknown or
  missing type.
- `_valid_keys_hint(steptype)` — the keys a step model takes; also the hint for a
  key an Indexed or Sequence step refuses, whose reason is already the message.
- `_document_keys_hint(model)` — the keys the header or a sequence takes, the
  hint for an unknown key there (a removed sequence key's reason is already the
  message: `validate_document()` words it from `REMOVED_SEQUENCE_KEYS`).
- `RENAMED_STEP_TYPES` (the note added to an unknown steptype) is a schema
  constant.

What stays worded here describes the file, not a field: the structural
pre-checks in `_run`, `_QUOTE_HINT`, "each step must be a mapping" and
"every step must name its type" (followed by the generated type list), the
cross-reference hints, the header warnings, and `_FALLBACK_HINT`
("See recipe_guide.html…"), which only a problem with no field reaches.

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
                #   refusal); a warning keeps the dotted form "header.version"
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
types, unknown keys anywhere, the input/output vocabulary, Sequence and Indexed step
shapes), then everything the framework's load refuses. Plus duplicate sequence
names and a `main_sequence` that names nothing, named with a hint.

**Warnings — what loads but looks wrong:** a `version` written as a number, an
empty `name`/`version`. An unknown or removed header/sequence key is an error,
not a warning: the framework refuses it.

## Known limitations

- A load refusal (pass 6) has no line: the framework's `RecipeError` names the
  sequence and step in its text, counted after Indexed expansion.
- Load refusals are found one at a time, and only once every validation error
  is fixed — the framework's load stops at its first problem.
- Global variable forward-reference checking (warning when a `{type: global}`
  input names a variable not in `globals`) is not implemented; an earlier step
  may set it dynamically.
- `image_path` existence on disk is not checked. A missing file never stops a recipe:
  the framework warns when it loads one from a file (`recipe/recipe.md`, load step 8).
