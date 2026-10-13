<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# recipe_editor module — Recipe Editor v2

A second recipe editor, **laid out like the pypts operator window**, so an author sees the
recipe the way an operator will once it is loaded. It sits beside the Recipe Creator
(`helper_applications/recipe_creator/`), which is unchanged, so the two can be compared;
pypts' Edit menu starts either one. Design: `docs/superpowers/specs/2026-10-13-recipe-editor-v2-design.md`.

Started by `python -m pypts.helper_applications.recipe_editor [recipe.yml]`,
`run_recipe_editor.py` / `.bat`, or pypts' **Edit → Recipe Editor v2** (on the loaded recipe).

## Files

| File | Owns |
|---|---|
| `editor_window.py` | `RecipeEditorWindow` and `main()`: layout, toolbar, menus, the wiring below; `editor_stylesheet()` |
| `schema_form.py` | `SchemaForm`: the right-hand form, generated from `recipe_schema`; `field_kind()` |
| `row_map.py` | `StepRef` and the row ↔ authored-step mapping; no Qt |
| `problems_panel.py` | `ProblemsPanel`: PROBLEMS, styled as pypts' LOG OUTPUT |
| `__main__.py`, `__init__.py` | `python -m` entry; package |

Reused, not copied:

- from pypts' GUI (`hmi/gui/`): `StepTableContent`, `get_stylesheet`, `palette`,
  `gui_theme` (the same `[gui] theme` setting), `top_bar.svg_icon`;
- from the Recipe Creator: `RecipeModel`, `YamlEditor`, `InvalidOverlay`,
  `creator_stylesheet`, `verify_string`, `rc_logging`.

## The window

```
 [open][save] [undo][redo] [+ v][delete][up][down][duplicate]  Sequence: [Main v]
 Editing <recipe name> / <file>
 STEP TABLE (pypts')  | RECIPE YAML         | EDIT (the form)
 PROBLEMS             |                     |
 Status: 1 warning                                              pypts x.y
```

Undo is Ctrl+Z; Redo is Ctrl+Y **and** Ctrl+Shift+Z (set explicitly - an action built from
`QKeySequence.StandardKey.Redo` gets only its first binding). With the focus in the YAML
editor or a text field, that widget's own undo and redo of the typing come first.

Three columns in a splitter (4 : 3 : 3); the left one is the step table over PROBLEMS
(3 : 1). The table's Result column is hidden (`set_result_column_visible(False)`): before a
run every result is "Pending", nothing an author needs. The toolbar has pypts' objectName (`PtsToolBar`) and 16 px icon-only buttons; the
icons are SVG, drawn in the palette's toolbutton colour, with a disabled variant. Status bar:
`Status: …` and the faint pypts version, as pypts shows them.

## One source of truth: the text in `RecipeModel`

The YAML editor commits with `set_from_text()`; the form with `set_path()`; the toolbar with
`add_step` / `remove_step` / `move_step` / `duplicate_step` / `add_sequence`. So there is one
undo history for all three, and ruamel keeps the file's comments through a form edit. On
`model.changed` the window rewrites the YAML text if it differs, refreshes the form, and
starts a 250 ms timer for `_refresh_view()`:

1. **Verify** — `verify_string(text)` → PROBLEMS, the gutter's error dots, the status bar,
   the form's field outlines.
2. **Parse as pypts does** — `recipe_parser.parse_recipe(text, file, check_version=False)`;
   the chosen sequence's `to_summary()` goes to `StepTableContent.show_sequence()`, the very
   call pypts makes on `RecipeLoaded`. The groups the author had unfolded stay unfolded
   (matched by name and the names of the groups above).
3. **Map the rows** — `step_sources_from_text(text, base_dir)` gives each row's
   `StepSource.origin`; `row_map.refs_for_rows()` makes them `StepRef`s, `all_refs()` lists
   every authored step for the cursor direction.

If the text cannot be shown as a tree (`RecipeModel` invalid), or parses but pypts would refuse
it (a load error), the table keeps its last rows and is disabled; PROBLEMS says why. With no
recipe at all (start-up), the table is grayed under "No recipe open: …" and Save is disabled;
New, Open and closing ask nothing then — there is nothing to lose (`_may_discard()`).
File → New starts from a recipe with one Wait step, so it loads from the first moment.

## Selection

- **A row click** (`StepTableContent.row_clicked`, the click panel switched off) selects the
  authored step the row comes from: an expanded Indexed row its Indexed step, a call row its
  Sequence step, a row inside a called sequence that sequence's step. The row is highlighted
  as pypts highlights a clicked row, the step's lines are tinted in the YAML
  (`YamlEditor.set_step_lines`) with the cursor put on its first line, and the form shows it.
- **The YAML cursor** (150 ms after it stops) selects the step around it (`ref_at_line`); a
  step of a sequence the table is not showing switches the Sequence chooser to it. Outside
  every step, nothing is selected and the form shows the header and the current sequence.
- **A PROBLEMS click** jumps to its line, which then selects its step.
- The table's right-click menu keeps pypts' entries and adds *Add step after*, *Delete*,
  *Move up/down*, *Duplicate*.

Structure edits act on `steps` only; a teardown step is selected and edited in the form, but
added, moved and deleted in the YAML. After an add, move or duplicate the step is selected again
once the table is rebuilt (`_select_after_refresh`).

## The form (`schema_form.py`)

Nothing in it names a step type. It walks the selected step's model
(`STEP_SCHEMAS[steptype_key(...)]`), or `HeaderSchema` and `SequenceSchema` with nothing
selected, and `field_kind()` picks each field's widget from its annotation:

| Field | Widget |
|---|---|
| `bool` | checkbox |
| `str`, `str \| None` | text field; emptied, an optional key is removed (`DELETE`) |
| `Any` | value field — the text read as YAML (`2` a number, `[A, B]` a list) |
| typed `None` (a refused key), a `Literal` tag, `SequenceSchema.steps` / `teardown_steps` | not shown |
| `inputs` | rows: name · value / global · value or global_name |
| `outputs` | rows: name · type (`OUTPUT_SCHEMAS`) · that type's own fields |
| Indexed `template` | the same form, nested, for the template's type |
| Indexed `parameter_sets` | a table: the template's inputs and outputs (and any key a set uses) as columns |
| `dict` (header `globals`) | name · initial value rows |
| `list` of names (`report_metadata`) | one comma-separated field |
| anything else | a small YAML box — `test_recipe_editor_form.py` fails if a recipe model's field ever lands here |

The heading is `STEP_TYPE_NAMES[...]` and the `steptype` tag's description. Required fields
come first, marked `*`; `description`, `image_path`, `id`, `skip`, `continue_on_error` sit under
**More**, open when one of them is set. Every label has an ⓘ: its tooltip, and the field's, is
the schema description; the placeholder is the first example. A problem whose
`ValidationIssue.document` / `.path` falls under a field outlines it (`problem` property,
`editor_stylesheet()`) with the message beneath.

**Rebuild or refill.** The form is rebuilt only when its *shape* changes — another step, the
type, the inputs' and outputs' names and kinds, the parameter sets' keys, the template's
shape (`_step_shape()`); otherwise every field is refilled from the model, and a field is only
rewritten when the model's text differs and it does not have the focus. Replaced content is
deleted later (`takeWidget()` + `deleteLater()`): a field commits from inside its own signal,
the Creator's rule (`recipe_creator.md`, The window). **A widget is put into the form before it
is shown or hidden:** `setVisible(True)` on one with no parent yet makes it a window of its own —
the "More" box did that, flashing up on every row click.

## Logging

`main()` calls `rc_logging.start_logging(prefix="recipe_editor", program_name="Recipe Editor v2")`:
`recipe_editor_<YYYYmmdd_HHMMSS>.log` in `paths.reports_dir`, the same excepthook dialog and
`faulthandler` as the Creator (`recipe_creator.md`, Logging). Opened, saved, and failures to
open or save are logged.

## Tests

- `test_recipe_editor_form.py` — `field_kind()` for every field of every recipe model;
  descriptions as tooltips; values, checkboxes, outputs, inputs, template, parameter sets,
  header; one undo entry per edit; a refill keeps the editor; a problem outlines its field.
- `test_recipe_editor_window.py` — `step_sources_from_text` equals the file version; every
  showcase row maps to an authored step; Indexed and call rows; the cursor direction; the table
  equals `to_summary()`; click → selection, tint, form; grayed rows for unreadable and refused
  text; the empty start; New; folding kept across edits; add, move, duplicate, delete; the
  Sequence chooser; five edits that commit inside their own signal, each in a subprocess.
- `test_hmi_gui.py` — the click panel switched off, the right-click extender, and both Edit
  menu entries starting their module on the loaded recipe.

## Known gaps

- A step's type cannot be changed in the form; that is done in the YAML.
- No drag-and-drop in the table; Move up / Move down instead.
- Teardown steps cannot be added, moved or deleted from the toolbar.
- A form field shows the value, not where a global comes from; global names are not checked
  against `globals` (the verificator does not either).
