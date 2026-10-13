# Recipe Editor v2 — Design

**Date:** 2026-10-13
**Status:** built 2026-10-13, on request straight from this spec (no plan document); awaiting the user's review of the running application. As built: `set_path(document, path, value)` instead of `set_step_path` (it also serves the header and the sequence); `ValidationIssue` gained `document` beside `path`; no recipe-file preview button (the YAML is already on screen); PROBLEMS writes ERROR / WARNING as LOG OUTPUT does.
**Modules:** new `helper_applications/recipe_editor/`; small additions to `hmi/gui/`
(`step_table.py`, `top_bar.py`, `gui.py`), `recipe/step_source.py`,
`helper_applications/recipe_creator/` (`issue.py`, `verificator.py`, `rc_logging.py`)

## 1. Goal

A second recipe editing application that **looks like the pypts operator window**, so an
author sees the recipe the way an operator will once it is loaded, and finds the same
controls in the same places. It sits beside the Recipe Creator — which stays untouched — so
the two can be compared; pypts' Edit menu gets **"Recipe Editor v2"** next to "Edit Recipe".

### What the user asked (2026-10-13)

- Restructure the editing GUI to look almost exactly like the standard GUI.
- Left: the step table, as shown when a recipe is loaded in the main application.
- Middle: the text editor. Right: a new column with the interactive editor (three columns).
- A separate application, opened from the main application under Edit → "Recipe Editor v2".

### Decided in conversation

| Question | Decision |
|---|---|
| What the table shows | **As loaded**: exactly the main window's table, from the parsed recipe — Indexed steps expanded, called sequences as foldable groups |
| What the form is built from | **The schema**: widgets generated from `recipe_schema`'s models, descriptions as help, examples as placeholders |
| Layout | PROBLEMS panel under the table (where the main window has LOG OUTPUT under the picture); YAML middle; form right |
| Approach | **A**: a new package composed from the main window's widgets and the Creator's `RecipeModel` (not a subclass of the main window, not a fourth Creator view) |

### Success criteria

- Opened on a recipe, the table is row for row what pypts' Run tab shows for the same file
  and sequence (names, descriptions, depth, groups, folding, "Pending").
- Every author-writable field of every step type, output type, the header and the sequence
  is editable in the form, with its schema description reachable from the field; a new
  field or step type in `recipe_schema.py` appears in the form without an edit here (a test
  enforces it).
- Text, form and toolbar edits all go through `RecipeModel`: one undo history, comments in
  the YAML preserved, invalid text kept as typed.
- No edit can crash the process (§6); an unexpected error is logged and shown, as in the
  Creator.
- `pytest tests`, `ruff check src tests`, `mypy` pass; the documents in §9 describe the code.

## 2. Window

```
 File  Edit  View  About
 [open][save][undo][redo] [add step v][delete][up][down]  Sequence: [Main v]      [preview]
 +--------------------------+-------------------------+-----------------------+
 | Step name | Desc | Result| 1  name: ...            | Wait - Pauses the run |
 | > Wait steps      Pending| 2  version: "1.0"       | Step name * [Settle ] |
 | v Indexed steps   Pending| 3  ---                  | Wait time * [2      ]i|
 |     add [1, 2]    Pending| ...                     | > More                |
 +--------------------------+                         | > Inputs (0)          |
 | PROBLEMS                 |                         | > Outputs (0)         |
 | ! header.version ...     |                         |                       |
 +--------------------------+-------------------------+-----------------------+
 Status: 1 warning                                                     pypts x.y
```

- `QMainWindow`, pypts' stylesheet (`hmi/gui/styles.get_stylesheet`) and palette, the same
  `[gui] theme` setting (`gui_theme.configured_theme`, system theme sync), View → dark mode.
- A horizontal splitter with three columns, initially 4 : 3 : 3. The left column is a
  vertical splitter: the table over the PROBLEMS panel (about 3 : 1).
- Toolbar built like `TopBarContent`: 16 px SVG icon buttons with tooltips, then the
  "Sequence:" chooser (every sequence of the recipe), the recipe-file preview at the right.
  Icons through `top_bar.svg_icon()` (today's private `_svg_icon`, made public).
- Status bar: the problem count ("2 errors · 1 warning", "Recipe valid", "Recipe text
  cannot be loaded") and the pypts version, as the main window shows it.
- Menus — File: New, Open, Save, Save As, Exit. Edit: Undo, Redo, Add Step (submenu of
  `STEP_TYPE_NAMES`), Delete Step, Move Up, Move Down, Duplicate Step, Add Sequence.
  View: Toggle Dark Mode. About: GitLab, Wiki (as the Creator).
- Started with a path (`python -m pypts.helper_applications.recipe_editor [recipe.yml]`) it
  opens it; without one it starts empty, grayed out as the fixed Creator does
  ("No recipe open: File > New or File > Open, or type one in the editor").

## 3. Data flow

**One source of truth: the recipe text, held by `RecipeModel`**
(`helper_applications/recipe_creator/rc_model.py`, reused as is). It round-trips through
ruamel (comments and quotes kept), owns the `QUndoStack`, and holds invalid text exactly as
typed. The YAML editor commits through `set_from_text()`; the form and toolbar through the
existing commands (`set_header_field`, `set_sequence_field`, `set_step_field`, `add_step`,
`remove_step`, `move_step`, `add_sequence`). Two commands are added there, both undoable:
`duplicate_step(seq_idx, step_idx)` and `set_step_path(seq_idx, step_idx, path, value)` —
the latter writes a value nested inside a step (an Indexed template's field, one output's
`min`), so a nested edit is one undo entry.

**The table — what an operator will see.** On `model.changed` (debounced 300 ms, like the
YAML commit) the editor parses `model.to_yaml()` with
`recipe_parser.parse_recipe(text, file_name, check_version=False)` and shows the chosen
sequence's `Sequence.to_summary()` with `StepTableContent.show_sequence()` — the main
window's own path (measured: 40 ms for the 72-row full showcase). If the text does not
load, the table keeps the last rows that did, disabled, and PROBLEMS says why. Parsing never
needs the step modules: a missing `module:` file does not stop it.

**Rows ↔ authored steps.** `recipe/step_source.py` already gives each row the lines of the
step it came from (the click panel's `StepSource`). It reads a file today; it gains
`step_sources_from_text(text, base_dir)`, which `step_sources_by_sequence(path)` then calls,
so both answer identically. The editor's `row_map.py` turns a row's `StepSource` into the
authored step it came from — `(sequence index, list name, step index)` in the model —
by matching the source's sequence document and first line against the model's documents.
Then:

- **click a row** → the row is highlighted, the YAML scrolls to and highlights the step's
  lines, the form shows that authored step. An expanded Indexed row selects its Indexed
  step; a row inside a called sequence selects that sequence's step; a Sequence step's row
  selects the Sequence step itself.
- **move the YAML cursor** into a step's lines → its first row is highlighted and the form
  follows.
- **nothing selected** (no row, cursor outside every step) → the form shows the header and
  the current sequence (§4.4).

**Validation.** Unchanged verificator: `verify_string(model.to_yaml())` after each change
(debounced), feeding PROBLEMS, the YAML gutter's error dots, the status bar and the form's
field outlines (§4.3).

## 4. The form (`schema_form.py`)

### 4.1 Generated from the schema

For the selected step, the model is `STEP_SCHEMAS[steptype_key(steptype)]`; the form walks
its `model_fields`. The heading is the step type's author name (`STEP_TYPE_NAMES`) and the
description of its `steptype` tag field ("Wait — Pauses the run for a fixed time."). The
type is not editable in the form (it would drop fields); it is changed in the YAML.

| Field annotation | Widget | Written as |
|---|---|---|
| `bool` | checkbox | `True` / `False` |
| `str`, `str \| None` | text field | the text; an emptied optional field is removed from the step |
| `Any` (wait_time, options, equals value, min/max, global_name) | **value field** | the text read as YAML (`yaml.safe_load`): `2` a number, `[Continue, Abort]` a list, `hello` text; text YAML cannot read is kept as text |
| `NoneType` (a refused key) | not shown | — |
| `Literal` tag (`steptype`, `type`) | the heading / the output type dropdown | — |
| `inputs` | rows: name · kind (value / global) · value or `global_name` | the mapping, entry names in the author's case |
| `outputs` | rows: name · type dropdown (`OUTPUT_SCHEMAS`) · that type's fields, generated from its model | one mapping per entry |
| Indexed `template` | the same form, nested, for the template's step type | via `set_step_path` |
| Indexed `parameter_sets` | a table: one row per set; columns = the template's input names, then its output names (`expect`); add / remove set | the list of sets |
| header `globals` | rows: name · initial value (value field) | the mapping |
| header `report_metadata` (list of names) | one comma-separated text field | the list |
| anything else | a small YAML box for that one field | parsed; a parse error is shown under it and not written |

The fallback row makes the form complete by construction; a test (§8) fails if any field of
any model falls through to it unexpectedly, naming the model and field, so a new kind of
field gets a proper widget on purpose.

### 4.2 Order and help

- Required fields first, marked `*`, in the model's order.
- The optional fields every step shares (`description`, `image_path`, `id`, `skip`,
  `continue_on_error` — `_StepFields` and `_OrdinaryStep`) in a **More** section, collapsed
  unless one of them is set to something other than its default.
- Each label has an ⓘ: its tooltip, and the field's, is the field's `description`. The
  placeholder of an empty field is its first example. Inputs and outputs are collapsible
  groups titled with their count ("Inputs (2)").

### 4.3 Problems on fields

`ValidationIssue` gains `path: tuple[int | str, ...] = ()` — the problem's location inside
its document (the schema problem's path, e.g. `("steps", 1, "outputs", "r", "max")`), empty
where there is none (structural, cross-document, warnings without a field). Additive: every
existing use of the type is unchanged; the Creator ignores it. The form outlines the field
whose path matches, in the palette's danger colour, with the issue's message under it.

### 4.4 Header and sequence

With nothing selected: **Recipe** — name, version, description, main sequence (dropdown of
the sequence names, empty = first), globals, report metadata; **Sequence** — the current
sequence's name, description, picture. Generated the same way from `HeaderSchema` and
`SequenceSchema` (their `steps` / `teardown_steps` are the table, not form fields).

### 4.5 Committing

Text and value fields commit on Enter or focus loss (`editingFinished`), checkboxes and
dropdowns at once. A field shows its text from the start and is only rewritten when the
model's value differs, so it keeps its focus and cursor while typed in. The form is rebuilt
only when another step is selected or the step's type changes; otherwise refilled.

## 5. The step table in the editor

`StepTableContent` is reused, not copied: same columns ("Step name", "Description",
"Result" — every result "Pending"), the same folding (groups start folded, ▸/▾,
Expand all / Collapse all), the same theme repaint. Two **public** additions, both inert for
pypts' own window:

- `set_click_panel_enabled(enabled: bool)` — the editor turns the YAML click panel off (the
  YAML is on screen beside it); pypts never calls it, so its panel is unchanged.
- `row_clicked = Signal(int)` and `highlight_row(row)` / `clear_highlight()` — public faces
  of the existing per-cell highlight, so the editor can show the selected row the way the
  panel's row is shown.

Its context menu keeps "Expand all / Collapse all"; the editor adds Add step after, Delete,
Move up/down, Duplicate (the step-editing items act on the authored step the row maps to).
"Open recipe in text editor" and "Open Python file" stay.

## 6. Errors and robustness

- **No on-the-spot deletion.** The Creator's rule applies (`recipe_creator.md`, The
  window): a widget is never deleted while it may be emitting — `takeWidget()` /
  `takeRow()` + `deleteLater()`.
- **Text that does not load:** last good rows, grayed; PROBLEMS lists why; Undo or fixing
  the text recovers. Structure edits (add, delete, move) are disabled meanwhile, as the
  Creator does.
- **Uncaught errors and hard crashes:** `rc_logging.start_logging(prefix)` gains a `prefix`
  argument (`"recipe_creator"` stays the Creator's default); the editor logs to
  `recipe_editor_<YYYYmmdd_HHMMSS>.log` in `paths.reports_dir`, with the same excepthook
  dialog and `faulthandler`.

## 7. Files

| Path | Owns |
|---|---|
| `helper_applications/recipe_editor/__init__.py`, `__main__.py` | package; `python -m` entry |
| `helper_applications/recipe_editor/editor_window.py` | `RecipeEditorWindow`, `main()`: layout, toolbar, menus, wiring |
| `helper_applications/recipe_editor/schema_form.py` | `SchemaForm`: the generated form (§4) |
| `helper_applications/recipe_editor/row_map.py` | rows ↔ authored steps (§3), no Qt |
| `helper_applications/recipe_editor/problems_panel.py` | PROBLEMS, styled as LOG OUTPUT |
| `helper_applications/recipe_editor/recipe_editor.md` | the context file |
| `run_recipe_editor.py`, `run_recipe_editor.bat` (root) | start it from a checkout, as the Creator's |
| `hmi/gui/gui.py` | Edit → "Recipe Editor v2": `open_recipe_editor()`, a process like `open_recipe_creator()` |

Reused, not copied: `StepTableContent`, `styles`, `palette`, `gui_theme`, `top_bar.svg_icon`,
the Creator's `RecipeModel`, `YamlEditor` (`rc_widgets.py`), `verify_string`, `rc_logging`.

## 8. Tests

- `test_recipe_editor_form.py` — every model in `STEP_SCHEMAS`, `OUTPUT_SCHEMAS`,
  `HeaderSchema`, `SequenceSchema`, `ParameterSet`: each author-writable field gets a widget
  other than the fallback, carries its description as tooltip; a value field writes `2` as a
  number and `[a, b]` as a list; a field edit is one undo entry.
- `test_recipe_editor_rows.py` — `row_map` on the full showcase: every row maps to an
  authored step; expanded Indexed rows map to their Indexed step; nested sequences; the
  YAML-cursor direction.
- `test_recipe_editor_window.py` — the table equals `Recipe.to_summary()` of the same text;
  click → YAML highlight and form; invalid text keeps the last rows grayed; the empty start;
  edits that commit from inside their own signal run in a subprocess (as
  `test_rc_window.py`).
- `test_recipe.py` — `step_sources_from_text` equals `step_sources_by_sequence` for the same
  file. `test_verificator.py` — `ValidationIssue.path` for a field problem.
- `test_hmi_gui.py` — the Edit menu entry starts the editor's module with the loaded recipe;
  `set_click_panel_enabled(False)` stops the panel; pypts' own table behaviour unchanged.

## 9. Documentation (same change)

New `recipe_editor/recipe_editor.md`; `CLAUDE.md` module table (the new context file);
`hmi/gui/gui.md` (Edit menu entry, the table's public additions, `svg_icon`);
`recipe/recipe.md` (`step_sources_from_text`); `recipe_creator.md` (`ValidationIssue.path`,
`rc_logging` prefix, `RecipeModel`'s two new commands and its second user);
`usage_manual.html` §11 (the editor, how to open it); `pypts_implementation_status.html`
(a new section; TODO: decide between Creator and Editor v2 after comparing).

## 10. Out of scope

- Changing a step's type in the form.
- Drag-and-drop reordering in the table (Move up/down instead).
- Running or dry-running the recipe from the editor.
- Removing either the Creator or this editor — a decision for after the comparison.
- Teardown steps get rows (they are in `to_summary()`), but the toolbar's Add step adds to
  `steps`; adding to `teardown_steps` is done in the YAML.
