# Recipe Creator Redesign — Spec

**Date:** 2026-09-14  
**Branch:** architecture_refactor  
**Deliverables:** `recipe_creator.py` (fixed), `recipe_creator_new.py` + `rc_model.py` + `rc_widgets.py`

---

## 1. Scope

Two independent deliverables in the same commit:

1. **Fix `recipe_creator.py`** — seven targeted import/logic patches, no restructuring.
2. **`recipe_creator_new.py`** — complete redesign: interactive step builder, swappable views, live verification, full undo/redo, YAML editor, dark/light theme.

---

## 2. Fix list for `recipe_creator.py`

| # | Location | Problem | Fix |
|---|---|---|---|
| 1 | Line 4–9 | `from pypts import ScintillaYamlEditor…` — symbols live in `customGUIModules.py` | Change to `from pypts.helper_applications.recipe_creator.customGUIModules import …` |
| 2 | Top | Missing `import os` | Add `import os` |
| 3 | Line 136, 273 | `light_style`, `dark_style` referenced but not imported | Import from `pypts.hmi.gui.styles` |
| 4 | Lines 694, 715 | Calls non-existent `validate_recipe_filepath` / `validate_recipe_string_variable` | Replace with `verify_file` / `verify_string` from `pypts.helper_applications.recipe_verificator` |
| 5 | Line 917 | `self.indexOfTopLevelItem(item)` — `self` is not the tree widget | Change to `self.tree.indexOfTopLevelItem(item)` |
| 6 | Line 244 | Fragile relative path for watermark logo | Replace with `Path(__file__).parent.parent.parent.parent / "resources" / "images" / "CERN_Logo.png"` |
| 7 | Template generation | Uses `input_mapping`, `output_mapping`, `locals`, `UserInteractionStep`, `continue_on_error: 'true'` | Update to current schema: `inputs`, `outputs`, `userinteraction`, `continue_on_error: true` (bool), remove `locals`/`parameters` |

---

## 3. New file structure

```
helper_applications/recipe_creator/
  recipe_creator.py          (patched in-place)
  recipe_creator_new.py      (new entry point + main window)
  rc_model.py                (RecipeModel + all QUndoCommand subclasses)
  rc_widgets.py              (all custom widgets)
  customGUIModules.py        (existing — reused, not modified)
  styles.py                  (existing — reused, not modified)
```

---

## 4. Data model (`rc_model.py`)

### `RecipeModel`

Single source of truth. Holds `_docs: list[dict]` (header dict + sequence dicts as plain Python). Every mutation is a `QUndoCommand` pushed onto an internal `QUndoStack`. Emits `changed: Signal()` after every push/undo/redo.

```python
class RecipeModel(QObject):
    changed = Signal()                          # both panels listen to this
    undo_stack: QUndoStack

    # Read
    def to_yaml(self) -> str                    # serialise _docs via ruamel.yaml
    def header(self) -> dict
    def sequences(self) -> list[dict]
    def sequence(self, idx: int) -> dict
    def steps(self, seq_idx: int, teardown=False) -> list[dict]
    def is_modified(self) -> bool

    # Write (all push a command and return)
    def set_header_field(self, key, value)
    def set_sequence_field(self, seq_idx, key, value)
    def add_step(self, seq_idx, steptype, position)    # inserts default step
    def remove_step(self, seq_idx, step_idx)
    def move_step(self, seq_idx, from_idx, to_idx)
    def set_step_field(self, seq_idx, step_idx, key, value)
    def add_sequence(self, name)
    def remove_sequence(self, seq_idx)
    def load_yaml(self, text) -> list[ValidationIssue]  # replaces _docs, clears stack
    def set_from_text(self, text)                        # SetFromTextCommand (undoable)

    # Default step factory (uses rules.py)
    def _default_step(self, steptype) -> dict
```

### Commands

All subclass `QUndoCommand`. Pattern: store old and new values, `redo()` applies new, `undo()` restores old, both call `model._notify()`.

| Command | Undo/redo target |
|---|---|
| `SetFieldCommand` | Any single field anywhere (path-addressed) |
| `AddStepCommand` | Insert step at position |
| `RemoveStepCommand` | Delete step (stores snapshot for undo) |
| `MoveStepCommand` | Swap positions |
| `AddSequenceCommand` | Append sequence |
| `RemoveSequenceCommand` | Delete sequence (stores snapshot) |
| `SetFromTextCommand` | Replace entire `_docs` from YAML text |

---

## 5. Main window (`recipe_creator_new.py`)

### Layout

```
MenuBar  ─────────────────────────────────────────────────────────
Toolbar  ─────────────────────────────────────────────────────────
┌── Left panel (QWidget, fixed min-width 340px) ──┬── YAML editor ──┐
│  HeaderStrip (collapsible, QFrame)              │  Syntax-hl'd    │
│  ─────────────────────────────────────────────  │  Line numbers   │
│  Step view (swappable via QStackedWidget)       │  Error gutter   │
│    slot 0: ListStepView                         │  markers        │
│    slot 1: CardStepView                         │                 │
│    slot 2: PanelsStepView                       │                 │
│  ─────────────────────────────────────────────  │                 │
│  [＋ Add Step ▼]  [Move ↑][↓]  [Delete]        │                 │
└─────────────────────────────────────────────────┴─────────────────┘
VerificationPanel (collapsible, QFrame) ──────────────────────────
LogConsole (fixed 150px QTextEdit) ───────────────────────────────
```

Main splitter is horizontal (left panel + YAML editor), resizable.

### Menus

**File:** New · Open · ─ · Save · Save As · ─ · Exit  
**Edit:** Undo · Redo · ─ · Add Step (submenu by type) · Delete Step  
**View:** Toggle Dark Mode · ─ · List View · Card View · Panels View (radio group) · ─ · Toggle Header · Toggle Log  
**About:** GitLab · Wiki

### Toolbar

`[New] [Open] [Save] [Save As]  |  [Undo] [Redo]  |  [Validate]  …  [Logo]`

Undo/redo buttons are connected to `model.undo_stack` and show greyed when empty.

---

## 6. Header strip (`HeaderStrip` in `rc_widgets.py`)

A collapsible `QFrame` above the step view. Collapsed: single line showing recipe name. Expanded: form with:

- `name` — `QLineEdit`, required
- `version` — `QLineEdit`, required
- `description` — `QLineEdit`, optional
- `globals` — `[Edit globals…]` button → opens `GlobalsEditorDialog` (key-value table)
- `report_metadata` — `QLineEdit` (comma-separated), optional
- Sequences: `QComboBox` showing sequence names + `[+]` add + `[-]` remove buttons

Every field edit pushes a `SetFieldCommand` via the model. No direct dict mutation.

`GlobalsEditorDialog`: modal `QDialog` with a two-column `QTableWidget` (name, initial value). Add/remove row buttons. OK pushes one `SetFieldCommand` per changed row.

---

## 7. Three step views (`rc_widgets.py`)

All three receive the same `RecipeModel` reference and listen to `model.changed`. All three emit `step_selected(seq_idx, step_idx)` and `step_action_requested(action, seq_idx, step_idx)` signals — the main window owns the actions (calls model methods).

### `ListStepView`

Vertical `QSplitter`. Top: `QListWidget` — one row per step: `[⠿ drag] [TYPE badge] step_name  [skip ✓]  [✕]`. Drag-to-reorder via `QListWidget` internal move. Bottom: `StepFormWidget` for the selected step (hidden when nothing selected).

### `CardStepView`

`QScrollArea` containing a `QVBoxLayout` of `StepCard` widgets. Each `StepCard` is a `QFrame` with a header row (same as list row) and a collapsible body containing `StepFormWidget`. Only one card is expanded at a time (accordion). Drag-to-reorder via mouse press/move/release tracking on the header row.

### `PanelsStepView`

Horizontal `QSplitter`. Left: slim `QListWidget` (type badge + name only, no buttons, fixed 180px). Right: `StepFormWidget` for the selected step in a `QScrollArea`.

---

## 8. Step form (`StepFormWidget` in `rc_widgets.py`)

Receives `(model, seq_idx, step_idx)`. Rebuilds on `model.changed` if it is the currently displayed step.

Layout (top to bottom):

1. **Step type** — read-only label (type cannot change; delete and re-add instead)
2. **Common fields** — `step_name` (QLineEdit), `description` (QLineEdit), `skip` (QCheckBox), `continue_on_error` (QCheckBox)
3. **Type-specific required fields** — one widget per field (QLineEdit for text, QDoubleSpinBox for `wait_time`)
4. **Inputs section** — `QGroupBox("Inputs")` + toggle button `[Rows | YAML]`
5. **Outputs section** — `QGroupBox("Outputs")` + toggle button `[Rows | YAML]`

Each section holds a `QStackedWidget` with slot 0 = rows mode, slot 1 = YAML mode. The toggle button flips the slot. State (rows vs YAML) is per-section, not per-step.

### Inputs rows mode (`MappingRowsWidget`)

`QVBoxLayout` of `InputRowWidget` + `[+ Add input]` button.

`InputRowWidget`: `[name QLineEdit] [type QComboBox: literal|global] [value widgets] [✕]`

- **literal**: shows `[value QLineEdit]`
- **global**: shows `[global_name QComboBox]` populated from `model.header().get("globals", {})`

### Outputs rows mode

Same pattern. `OutputRowWidget`: `[name QLineEdit] [type QComboBox] [value widgets] [✕]`

Type-specific value widgets:
- **equals**: `[value QLineEdit]`
- **range**: `[min QLineEdit] … [max QLineEdit]`
- **passfail**: *(no extra fields)*
- **pass**: *(no extra fields)*
- **global**: `[global_name QLineEdit]`

### Inputs/outputs YAML mode (`MappingYamlWidget`)

Small `QTextEdit` (5–8 lines tall) with `YamlHighlighter` attached. Shows the section as YAML. On text change (debounced 300ms): parses the block, validates with `verify_string`, shows inline error label if invalid, otherwise pushes `SetFieldCommand`.

---

## 9. YAML editor (right panel)

Reuses `ScintillaYamlEditor` from `customGUIModules.py` with these additions:

- **Error gutter** — red dot in the line number area for lines that have a `ValidationIssue`. Computed from `line` field of each issue. Repainted on every verification pass.
- **Debounce** — text changes trigger a 400ms `QTimer` before calling `model.set_from_text()`. This prevents a full left-panel rebuild on every keystroke.
- **Sync lock** — a boolean flag `_updating` prevents echo: when the model drives the editor (via `model.changed`), the editor's `textChanged` signal is blocked.

---

## 10. Verification panel (`VerificationPanel` in `rc_widgets.py`)

Collapsible `QFrame` at the bottom of the window, above the log console.

**Collapsed:** single `QLabel` — `✅ Recipe valid` or `❌ 3 errors · 1 warning  [▼]`.

**Expanded:** 
- `QListWidget` — one item per `ValidationIssue`: `[icon] field_path: message (line N)`
  - Errors shown with red icon, warnings with yellow
- `QLabel` hint area below the list — shows `issue.hint` for the selected item
- Double-click on item: moves YAML editor cursor to `issue.line`; highlights matching step in left panel

Verification runs via `verify_string(model.to_yaml())` on each `model.changed` signal, debounced 200ms.

---

## 11. Theming

`recipe_creator_new.py` is a standalone `QApplication`. At startup:
- Detects system dark mode via `QGuiApplication.styleHints().colorScheme()`
- Applies `get_stylesheet(dark)` from `pypts.hmi.gui.styles`
- Stores `dark: bool` on the main window

View → Toggle Dark Mode: flips `dark`, reapplies stylesheet, calls `set_dark(dark)` on `ScintillaYamlEditor`, `YamlHighlighter`, and any widget with a `set_dark` method.

No hex literals anywhere outside palette.py (existing rule).

---

## 12. Sync invariant

At all times: `model.to_yaml()` equals the YAML editor text (modulo the 400ms debounce window).

Left panel always reflects `model._docs` exactly. After `model.changed`, all three views call `rebuild()` — this is a full rebuild, acceptable for recipe sizes up to ~100 steps.

---

## 13. Out of scope for this iteration

- Drag-to-reorder between sequences
- Export / print
- Recipe diff view
- Auto-complete for `global_name` references in inputs/outputs rows
- CLI entry point (`__main__` block runs the GUI; no headless mode needed)
