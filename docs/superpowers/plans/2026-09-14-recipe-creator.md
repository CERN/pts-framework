# Recipe Creator Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `recipe_creator.py` (7 targeted patches so it boots) and build `recipe_creator_new.py` + `rc_model.py` + `rc_widgets.py` — a full redesign with interactive step builder, swappable views, live verification, and full undo/redo.

**Architecture:** `RecipeModel` (in `rc_model.py`) is the single source of truth — a `list[dict]` holding header + sequences, all mutations pushed onto a `QUndoStack`. Both the left panel (step views) and right panel (YAML editor) listen to `model.changed` and rebuild from `_docs`. The main window in `recipe_creator_new.py` owns all widgets and wires signals.

**Tech Stack:** PySide6, ruamel.yaml (serialisation), PyYAML (YAML compose for line numbers), `pypts.recipe.rules` (schema constants), `pypts.helper_applications.recipe_verificator` (verify_string/verify_file), `pypts.hmi.gui.palette` (palette tokens), `pypts.hmi.gui.styles` (get_stylesheet).

## Global Constraints

- Python ≥ 3.11, PySide6 only (no PyQt5/PyQt6), Windows + Linux.
- No hex colour literals anywhere in `rc_widgets.py` or `recipe_creator_new.py` — use `palette.get_palette(dark)` tokens.
- `customGUIModules.py` and `styles.py` are **not modified** — reused as-is.
- All imports must be absolute (`pypts.helper_applications.recipe_creator.…`), not relative.
- Test file: `tests/unit_tests/test_rc_model.py`.
- Quality gates: `pytest tests`, `ruff check src tests`, `mypy` must all pass after each task.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/pypts/helper_applications/recipe_creator/recipe_creator.py` | 7 targeted bug fixes only |
| Create | `src/pypts/helper_applications/recipe_creator/rc_model.py` | `RecipeModel` + all `QUndoCommand` subclasses |
| Create | `src/pypts/helper_applications/recipe_creator/rc_widgets.py` | All custom widgets (`YamlEditor`, `VerificationPanel`, `HeaderStrip`, `StepFormWidget`, the three step views, mapping row/YAML widgets) |
| Create | `src/pypts/helper_applications/recipe_creator/recipe_creator_new.py` | Entry point, `QApplication`, main window wiring |
| Create | `tests/unit_tests/test_rc_model.py` | Unit tests for `RecipeModel` (headless, no display required) |

---

### Task 1: Fix `recipe_creator.py` — 7 targeted patches

**Files:**
- Modify: `src/pypts/helper_applications/recipe_creator/recipe_creator.py`

**Interfaces:**
- Consumes: `pypts.helper_applications.recipe_creator.customGUIModules` (ScintillaYamlEditor, WatermarkWidget, HashableTreeItem, RecipeCreatorApp), `pypts.hmi.gui.styles.get_stylesheet`, `pypts.helper_applications.recipe_verificator` (verify_file, verify_string)
- Produces: `recipe_creator.py` that can be imported and run without `ImportError`

- [ ] **Step 1: Fix the broken import block (lines 4–9)**

Replace:
```python
from pypts import (
    ScintillaYamlEditor,
    WatermarkWidget,
    HashableTreeItem,
    RecipeCreatorApp
)
```
With:
```python
from pypts.helper_applications.recipe_creator.customGUIModules import (
    ScintillaYamlEditor,
    WatermarkWidget,
    HashableTreeItem,
    RecipeCreatorApp,
)
```

- [ ] **Step 2: Add missing `import os` and path/style imports**

After the existing `import re` line (line 11), add:
```python
import os
from pathlib import Path
from pypts.hmi.gui.styles import get_stylesheet
from pypts.helper_applications.recipe_verificator import verify_file, verify_string, ValidationIssue
```

- [ ] **Step 3: Replace `light_style` / `dark_style` references**

`light_style` and `dark_style` are referenced at lines 136, 273, and 278 but never defined. Replace each occurrence:

Line 136 — inside `setup_central_widget`:
```python
# before
self.setStyleSheet(light_style)
# after
self.setStyleSheet(get_stylesheet(False))
```

Line 273 — inside `toggle_dark_mode` (enabled branch):
```python
# before
self.setStyleSheet(dark_style)
# after
self.setStyleSheet(get_stylesheet(True))
```

Line 278 — inside `toggle_dark_mode` (disabled branch):
```python
# before
self.setStyleSheet(light_style)
# after
self.setStyleSheet(get_stylesheet(False))
```

- [ ] **Step 4: Replace non-existent validate calls**

Replace the entire `validate_recipe` method (lines 692–704):
```python
def validate_recipe(self):
    try:
        issues = verify_file(self.current_file_path)
        errors = [i for i in issues if i.is_error]
        if not errors:
            self.log("✅ Recipe file validated successfully.")
            self.show_recipe_ok()
        else:
            self.log(f"❌ Recipe file failed validation: {errors[0].message}")
            self.show_recipe_error("Recipe file is invalid!")
            return False
    except Exception as e:
        self.tree.blockSignals(False)
        self.log(f"❌ Exception while validating the recipe: {e}")
        return False
```

Replace the entire `validate_temporary_recipe_contents` method (lines 714–718):
```python
def validate_temporary_recipe_contents(self):
    issues = verify_string(self.temporary_recipe_contents)
    errors = [i for i in issues if i.is_error]
    ok = not errors
    description = "; ".join(f"{i.field}: {i.message}" for i in issues) if issues else ""
    if ok:
        self.last_valid_recipe = self.temporary_recipe_contents
    return ok, description
```

- [ ] **Step 5: Fix `indexOfTopLevelItem` / `takeTopLevelItem` wrong receiver (line 917–918)**

```python
# before
index = self.indexOfTopLevelItem(item)
self.takeTopLevelItem(index)
# after
index = self.tree.indexOfTopLevelItem(item)
self.tree.takeTopLevelItem(index)
```

- [ ] **Step 6: Fix fragile watermark logo path (line 244)**

```python
# before
self.watermark_widget = WatermarkWidget("../Resources/images/CERN_Logo.png")
# after
_logo = str(Path(__file__).parent.parent.parent.parent / "resources" / "images" / "CERN_Logo.png")
self.watermark_widget = WatermarkWidget(_logo)
```

- [ ] **Step 7: Fix template generation — update to current schema**

The template is generated by `RecipeCreatorApp.generate_template_yaml` in `customGUIModules.py` (which we cannot modify). Override the template generator in `recipe_creator.py`'s `on_add_clicked` method (around line 533) by replacing the `yaml_string = generator_pop_up.get_generated_recipe()` block with a call to a new local helper:

Add this function before the class definition (after imports):

```python
def _generate_template(data: dict) -> str:
    """Generate a recipe YAML string conforming to the current schema."""
    import yaml as _yaml

    header = {
        "name": data["name"],
        "version": data["version"],
        "description": data["description"],
        "main_sequence": data["main_sequence"],
        "globals": {},
    }

    steps = []
    for i in range(data["num_steps"]):
        steps.append({
            "steptype": "userinteraction",
            "step_name": f"Step {i + 1}",
            "description": f"Step {i + 1} description",
            "skip": False,
            "continue_on_error": True,
            "message": "Tell the operator what to do",
            "options": [{"yes": ""}, {"no": ""}],
            "outputs": {"output": {"type": "equals", "value": "yes"}},
        })

    sequence = {
        "sequence_name": data["main_sequence"],
        "description": f"{data['main_sequence']} description",
        "steps": steps,
    }

    spdx = "# SPDX-FileCopyrightText: 2025 CERN <home.cern>\n#\n# SPDX-License-Identifier: LGPL-2.1-or-later\n"
    return spdx + _yaml.dump_all([header, sequence], sort_keys=False)
```

Then in `on_add_clicked` (around line 546), replace:
```python
yaml_string = generator_pop_up.get_generated_recipe()
```
With:
```python
data = generator_pop_up.open_creator_dialog(self.dark_mode)  # already called above; get data differently
```

Actually, `open_creator_dialog` already ran and stored in `generator_pop_up.generated_recipe`. Instead, use the RecipeCreatorDialog directly. Replace the `on_add_clicked` method body:

```python
def on_add_clicked(self):
    from pypts.helper_applications.recipe_creator.customGUIModules import RecipeCreatorDialog
    dialog = RecipeCreatorDialog()
    dialog.set_dark_mode(self.dark_mode)
    dialog.resize(500, 300)
    if not dialog.exec():
        return
    data = dialog.get_data()
    yaml_string = _generate_template(data)
    if not yaml_string:
        return
    self.temporary_recipe_contents = yaml_string
    self.update_yaml_viewer()
    self.update_yaml_treeview()
    self.stacked_layout.setCurrentIndex(1)
    self.close_recipe.setEnabled(True)
    self.save_as_action.setEnabled(True)
    self.save_action.setEnabled(True)
    self.action_save.setEnabled(True)
    self.action_save_as.setEnabled(True)
    self.action_restore_recipe.setEnabled(True)
    self.collapse_inside_steps()
    self.log("✅ New recipe created from template.")
```

- [ ] **Step 8: Smoke test — import without error**

```bash
cd C:/Git/pts-framework
python -c "from pypts.helper_applications.recipe_creator.recipe_creator import RecipeEditorMainMenu; print('OK')"
```
Expected: prints `OK`, no `ImportError`.

- [ ] **Step 9: Run quality gates**

```bash
ruff check src/pypts/helper_applications/recipe_creator/recipe_creator.py
```
Expected: no errors (fix any `E501` lines if needed with `# noqa: E501`).

- [ ] **Step 10: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/recipe_creator.py
git commit -m "fix: patch recipe_creator.py — imports, styles, validate calls, schema"
```

---

### Task 2: `rc_model.py` — RecipeModel + QUndoStack

**Files:**
- Create: `src/pypts/helper_applications/recipe_creator/rc_model.py`
- Create: `tests/unit_tests/test_rc_model.py`

**Interfaces:**
- Consumes: `pypts.recipe.rules` (STEP_TYPE_REQUIRED, STEP_COMMON_DEFAULTS, STEP_TYPE_DEFAULTS), `pypts.helper_applications.recipe_verificator.verify_string`, `ruamel.yaml`, `yaml` (PyYAML)
- Produces:
  - `RecipeModel(QObject)` with `changed = Signal()`, `undo_stack: QUndoStack`
  - Read methods: `to_yaml() -> str`, `header() -> dict`, `sequences() -> list[dict]`, `sequence(idx) -> dict`, `steps(seq_idx, teardown=False) -> list[dict]`, `is_modified() -> bool`
  - Write methods: `set_header_field(key, value)`, `set_sequence_field(seq_idx, key, value)`, `set_step_field(seq_idx, step_idx, key, value)`, `add_step(seq_idx, steptype, position)`, `remove_step(seq_idx, step_idx)`, `move_step(seq_idx, from_idx, to_idx)`, `add_sequence(name)`, `remove_sequence(seq_idx)`, `load_yaml(text) -> list`, `set_from_text(text)`
  - Internal: `_notify()`, `_default_step(steptype) -> dict`

- [ ] **Step 1: Write failing tests**

Create `tests/unit_tests/test_rc_model.py`:

```python
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])

_RECIPE = """\
name: Test Recipe
version: "0.1"
---
sequence_name: Main
steps:
  - steptype: wait
    step_name: First wait
    wait_time: 1.0
"""

@pytest.fixture
def model(qapp):
    from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
    m = RecipeModel()
    m.load_yaml(_RECIPE)
    return m


def test_header_read(model):
    assert model.header()["name"] == "Test Recipe"


def test_sequences_read(model):
    seqs = model.sequences()
    assert len(seqs) == 1
    assert seqs[0]["sequence_name"] == "Main"


def test_steps_read(model):
    assert len(model.steps(0)) == 1
    assert model.steps(0)[0]["steptype"] == "wait"


def test_set_header_field_emits_changed(model):
    received = []
    model.changed.connect(lambda: received.append(1))
    model.set_header_field("name", "New Name")
    assert received
    assert model.header()["name"] == "New Name"


def test_set_header_field_is_undoable(model):
    original = model.header()["name"]
    model.set_header_field("name", "Changed")
    assert model.header()["name"] == "Changed"
    model.undo_stack.undo()
    assert model.header()["name"] == original


def test_add_step_inserts_at_position(model):
    count_before = len(model.steps(0))
    model.add_step(0, "wait", 0)
    assert len(model.steps(0)) == count_before + 1
    assert model.steps(0)[0]["steptype"] == "wait"


def test_add_step_is_undoable(model):
    count_before = len(model.steps(0))
    model.add_step(0, "wait", 0)
    model.undo_stack.undo()
    assert len(model.steps(0)) == count_before


def test_remove_step_is_undoable(model):
    step_name = model.steps(0)[0]["step_name"]
    model.remove_step(0, 0)
    assert len(model.steps(0)) == 0
    model.undo_stack.undo()
    assert model.steps(0)[0]["step_name"] == step_name


def test_move_step_changes_order(model):
    model.add_step(0, "userinteraction", 1)
    model.steps(0)[1]["step_name"] = "Second"
    first_name = model.steps(0)[0]["step_name"]
    model.move_step(0, 0, 1)
    assert model.steps(0)[1]["step_name"] == first_name


def test_set_step_field(model):
    model.set_step_field(0, 0, "wait_time", 5.0)
    assert model.steps(0)[0]["wait_time"] == 5.0


def test_add_remove_sequence(model):
    count = len(model.sequences())
    model.add_sequence("New Seq")
    assert len(model.sequences()) == count + 1
    model.remove_sequence(len(model.sequences()) - 1)
    assert len(model.sequences()) == count


def test_load_yaml_clears_undo_stack(model):
    model.set_header_field("name", "Something")
    assert model.undo_stack.canUndo()
    model.load_yaml(_RECIPE)
    assert not model.undo_stack.canUndo()


def test_set_from_text_is_undoable(model):
    original_yaml = model.to_yaml()
    new_yaml = original_yaml.replace("Test Recipe", "Modified")
    model.set_from_text(new_yaml)
    assert model.header()["name"] == "Modified"
    model.undo_stack.undo()
    assert model.header()["name"] == "Test Recipe"


def test_to_yaml_produces_valid_recipe(model):
    from pypts.helper_applications.recipe_verificator import verify_string
    issues = verify_string(model.to_yaml())
    errors = [i for i in issues if i.is_error]
    assert not errors, [str(i) for i in errors]


def test_default_step_has_required_fields(qapp):
    from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
    from pypts.recipe.rules import STEP_TYPE_REQUIRED
    m = RecipeModel()
    for steptype in STEP_TYPE_REQUIRED:
        step = m._default_step(steptype)
        assert step["steptype"] == steptype
        for field in STEP_TYPE_REQUIRED[steptype]:
            assert field in step, f"{steptype} missing {field}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd C:/Git/pts-framework
pytest tests/unit_tests/test_rc_model.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'pypts.helper_applications.recipe_creator.rc_model'`

- [ ] **Step 3: Implement `rc_model.py`**

Create `src/pypts/helper_applications/recipe_creator/rc_model.py`:

```python
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import io
from typing import Any

import yaml as _pyyaml
from ruamel.yaml import YAML
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack, QUndoCommand

from pypts.recipe.rules import (
    STEP_TYPE_REQUIRED,
    STEP_COMMON_DEFAULTS,
    STEP_TYPE_DEFAULTS,
    SEQUENCE_DEFAULTS,
    HEADER_DEFAULTS,
)


class RecipeModel(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self._docs: list[dict] = []
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self.undo_stack.cleanChanged.connect(lambda _: self.changed.emit())

    # ── Read ──────────────────────────────────────────────────────────────────

    def to_yaml(self) -> str:
        buf = io.StringIO()
        self._yaml.dump_all(self._docs, buf)
        return buf.getvalue()

    def header(self) -> dict:
        return self._docs[0] if self._docs else {}

    def sequences(self) -> list[dict]:
        return self._docs[1:] if len(self._docs) > 1 else []

    def sequence(self, idx: int) -> dict:
        return self._docs[idx + 1]

    def steps(self, seq_idx: int, teardown: bool = False) -> list[dict]:
        key = "teardown_steps" if teardown else "steps"
        return self.sequence(seq_idx).get(key, [])

    def is_modified(self) -> bool:
        return not self.undo_stack.isClean()

    # ── Write — all push a command ────────────────────────────────────────────

    def set_header_field(self, key: str, value: Any) -> None:
        self.undo_stack.push(_SetDictField(self, self._docs[0], key, value, f"Set header.{key}"))

    def set_sequence_field(self, seq_idx: int, key: str, value: Any) -> None:
        self.undo_stack.push(_SetDictField(self, self._docs[seq_idx + 1], key, value, f"Set seq.{key}"))

    def set_step_field(self, seq_idx: int, step_idx: int, key: str, value: Any) -> None:
        step = self.steps(seq_idx)[step_idx]
        self.undo_stack.push(_SetDictField(self, step, key, value, f"Set step.{key}"))

    def add_step(self, seq_idx: int, steptype: str, position: int) -> None:
        self.undo_stack.push(_AddStep(self, seq_idx, steptype, position))

    def remove_step(self, seq_idx: int, step_idx: int) -> None:
        self.undo_stack.push(_RemoveStep(self, seq_idx, step_idx))

    def move_step(self, seq_idx: int, from_idx: int, to_idx: int) -> None:
        self.undo_stack.push(_MoveStep(self, seq_idx, from_idx, to_idx))

    def add_sequence(self, name: str) -> None:
        self.undo_stack.push(_AddSequence(self, name))

    def remove_sequence(self, seq_idx: int) -> None:
        self.undo_stack.push(_RemoveSequence(self, seq_idx))

    def load_yaml(self, text: str) -> list:
        """Replace _docs from YAML text. Clears undo stack. Returns ValidationIssues."""
        from pypts.helper_applications.recipe_verificator import verify_string
        docs = list(self._yaml.load_all(text))
        self._docs = docs
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.changed.emit()
        return verify_string(text)

    def set_from_text(self, text: str) -> None:
        """Replace entire _docs from YAML text — undoable."""
        self.undo_stack.push(_SetFromText(self, text))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _notify(self) -> None:
        self.changed.emit()

    def _default_step(self, steptype: str) -> dict:
        step: dict[str, Any] = {"steptype": steptype, "step_name": f"New {steptype} step"}
        step.update(STEP_COMMON_DEFAULTS)
        for field in STEP_TYPE_REQUIRED.get(steptype, ()):
            if field not in step:
                step[field] = ""
        step.update(STEP_TYPE_DEFAULTS.get(steptype, {}))
        return step


# ── Commands ──────────────────────────────────────────────────────────────────


class _SetDictField(QUndoCommand):
    def __init__(self, model: RecipeModel, target: dict, key: str, new: Any, text: str) -> None:
        super().__init__(text)
        self._model = model
        self._target = target
        self._key = key
        self._new = new
        self._old = target.get(key)

    def redo(self) -> None:
        self._target[self._key] = self._new
        self._model._notify()

    def undo(self) -> None:
        if self._old is None:
            self._target.pop(self._key, None)
        else:
            self._target[self._key] = self._old
        self._model._notify()


class _AddStep(QUndoCommand):
    def __init__(self, model: RecipeModel, seq_idx: int, steptype: str, position: int) -> None:
        super().__init__(f"Add {steptype} step")
        self._model = model
        self._seq_idx = seq_idx
        self._position = position
        self._step = model._default_step(steptype)

    def redo(self) -> None:
        self._model.steps(self._seq_idx).insert(self._position, self._step)
        self._model._notify()

    def undo(self) -> None:
        steps = self._model.steps(self._seq_idx)
        if self._position < len(steps) and steps[self._position] is self._step:
            steps.pop(self._position)
        self._model._notify()


class _RemoveStep(QUndoCommand):
    def __init__(self, model: RecipeModel, seq_idx: int, step_idx: int) -> None:
        super().__init__("Remove step")
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._snapshot: dict | None = None

    def redo(self) -> None:
        steps = self._model.steps(self._seq_idx)
        self._snapshot = steps.pop(self._step_idx)
        self._model._notify()

    def undo(self) -> None:
        if self._snapshot is not None:
            self._model.steps(self._seq_idx).insert(self._step_idx, self._snapshot)
        self._model._notify()


class _MoveStep(QUndoCommand):
    def __init__(self, model: RecipeModel, seq_idx: int, from_idx: int, to_idx: int) -> None:
        super().__init__("Move step")
        self._model = model
        self._seq_idx = seq_idx
        self._from = from_idx
        self._to = to_idx

    def _swap(self, a: int, b: int) -> None:
        steps = self._model.steps(self._seq_idx)
        step = steps.pop(a)
        steps.insert(b, step)
        self._model._notify()

    def redo(self) -> None:
        self._swap(self._from, self._to)

    def undo(self) -> None:
        self._swap(self._to, self._from)


class _AddSequence(QUndoCommand):
    def __init__(self, model: RecipeModel, name: str) -> None:
        super().__init__(f"Add sequence '{name}'")
        self._model = model
        self._seq: dict = {"sequence_name": name, "steps": [], **SEQUENCE_DEFAULTS}

    def redo(self) -> None:
        self._model._docs.append(self._seq)
        self._model._notify()

    def undo(self) -> None:
        if self._model._docs and self._model._docs[-1] is self._seq:
            self._model._docs.pop()
        self._model._notify()


class _RemoveSequence(QUndoCommand):
    def __init__(self, model: RecipeModel, seq_idx: int) -> None:
        super().__init__("Remove sequence")
        self._model = model
        self._doc_idx = seq_idx + 1
        self._snapshot: dict | None = None

    def redo(self) -> None:
        self._snapshot = self._model._docs.pop(self._doc_idx)
        self._model._notify()

    def undo(self) -> None:
        if self._snapshot is not None:
            self._model._docs.insert(self._doc_idx, self._snapshot)
        self._model._notify()


class _SetFromText(QUndoCommand):
    def __init__(self, model: RecipeModel, text: str) -> None:
        super().__init__("Edit YAML")
        self._model = model
        self._new_text = text
        buf = io.StringIO()
        model._yaml.dump_all(model._docs, buf)
        self._old_text = buf.getvalue()

    def redo(self) -> None:
        try:
            self._model._docs = list(self._model._yaml.load_all(self._new_text))
        except Exception:
            pass
        self._model._notify()

    def undo(self) -> None:
        try:
            self._model._docs = list(self._model._yaml.load_all(self._old_text))
        except Exception:
            pass
        self._model._notify()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit_tests/test_rc_model.py -v
```
Expected: all tests pass. Common failures and fixes:
- `QUndoStack` not in `PySide6.QtGui` on some builds → use `from PySide6.QtGui import QUndoStack, QUndoCommand` (correct for PySide6 ≥ 6.4; if missing, try `from PySide6.QtWidgets import QUndoStack, QUndoCommand`).
- `ruamel.yaml` dumps multi-doc with `---` separators — ensure `load_yaml` handles the leading SPDX comment lines by stripping them before parsing if needed.

- [ ] **Step 5: Run quality gates**

```bash
ruff check src/pypts/helper_applications/recipe_creator/rc_model.py
```
Fix any issues, then:
```bash
pytest tests/unit_tests/test_rc_model.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/rc_model.py tests/unit_tests/test_rc_model.py
git commit -m "feat: add RecipeModel with QUndoStack and command classes"
```

---

### Task 3: `rc_widgets.py` — YamlEditor + PaletteYamlHighlighter + VerificationPanel

**Files:**
- Create: `src/pypts/helper_applications/recipe_creator/rc_widgets.py` (first section)

**Interfaces:**
- Consumes: `pypts.helper_applications.recipe_creator.customGUIModules.ScintillaYamlEditor`, `pypts.hmi.gui.palette.get_palette`, `pypts.helper_applications.recipe_verificator.ValidationIssue`
- Produces:
  - `PaletteYamlHighlighter(QSyntaxHighlighter)` — palette-aware, `set_dark(dark: bool)`
  - `YamlEditor(ScintillaYamlEditor)` — adds `text_committed = Signal(str)`, `_updating: bool`, `set_content(text)`, `set_error_lines(lines: set[int])`, `set_dark(dark: bool)`, `go_to_line(line_num: int)`
  - `VerificationPanel(QFrame)` — `update_issues(issues: list[ValidationIssue])`, `line_requested = Signal(int)`

- [ ] **Step 1: Write failing import test**

Add to `tests/unit_tests/test_rc_model.py` (or a new `test_rc_widgets_smoke.py`):

```python
def test_rc_widgets_importable(qapp):
    from pypts.helper_applications.recipe_creator.rc_widgets import (
        PaletteYamlHighlighter,
        YamlEditor,
        VerificationPanel,
    )
    assert PaletteYamlHighlighter is not None
    assert YamlEditor is not None
    assert VerificationPanel is not None
```

Run:
```bash
pytest tests/unit_tests/test_rc_model.py::test_rc_widgets_importable -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Implement the first section of `rc_widgets.py`**

Create `src/pypts/helper_applications/recipe_creator/rc_widgets.py`:

```python
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat,
)
from PySide6.QtCore import Qt, QRegularExpression, QTimer, Signal

from pypts.helper_applications.recipe_creator.customGUIModules import ScintillaYamlEditor
from pypts.hmi.gui.palette import get_palette


# ── PaletteYamlHighlighter ────────────────────────────────────────────────────


class PaletteYamlHighlighter(QSyntaxHighlighter):
    """YAML syntax highlighter that reads colours from the palette (no hex literals)."""

    def __init__(self, document, dark: bool = False) -> None:
        super().__init__(document)
        self._rules: list[tuple] = []
        self._build_rules(dark)

    def set_dark(self, dark: bool) -> None:
        self._build_rules(dark)
        self.rehighlight()

    def _build_rules(self, dark: bool) -> None:
        p = get_palette(dark)
        self._rules = []

        def _rule(pattern: str, color: str, bold: bool = False, italic: bool = False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            self._rules.append((QRegularExpression(pattern), fmt))

        _rule(r"^\s*[^:\n]+(?=:)", p.yaml_key, bold=True)
        _rule(r'(?<=:\s)["\'].*["\']', p.yaml_string)
        _rule(r'\b\d+(\.\d+)?\b', p.yaml_number)
        _rule(r'\b(true|false)\b', p.yaml_boolean)
        _rule(r'\b(null|Null|NULL|~)\b', p.yaml_null)
        _rule(r'#.*', p.yaml_comment, italic=True)

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ── YamlEditor ────────────────────────────────────────────────────────────────


class YamlEditor(ScintillaYamlEditor):
    """ScintillaYamlEditor extended with debounced commit signal and error gutter dots."""

    text_committed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self._error_lines: set[int] = set()
        self._highlighter = PaletteYamlHighlighter(self.document(), dark=False)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._on_debounce)

        self.textChanged.connect(self._on_text_changed)

    def set_dark(self, dark: bool) -> None:
        self.set_dark_mode(dark)
        self._highlighter.set_dark(dark)

    def set_content(self, text: str) -> None:
        """Set editor text without triggering the debounce/commit cycle."""
        self._updating = True
        self.setPlainText(text)
        self._updating = False

    def set_error_lines(self, lines: set[int]) -> None:
        self._error_lines = lines
        self.line_number_area.update()

    def go_to_line(self, line_num: int) -> None:
        """Move cursor to 1-based line_num and ensure it is visible."""
        if line_num and line_num > 0:
            self.setCursorPosition(line_num - 1, 0)
            self.ensureLineVisible(line_num - 1)

    def _on_text_changed(self) -> None:
        if not self._updating:
            self._debounce.start()

    def _on_debounce(self) -> None:
        self.text_committed.emit(self.toPlainText())

    def line_number_area_width(self) -> int:
        return super().line_number_area_width() + 14

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        p = get_palette(self.dark_mode)
        bg = QColor(p.panel_background)
        painter.fillRect(event.rect(), bg)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        line_h = self.fontMetrics().height()
        dot_size = min(8, line_h - 2)
        num_width = self.line_number_area_width() - dot_size - 6

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_num = block_number + 1
                painter.setPen(QColor(p.text_muted))
                painter.drawText(
                    0, top, num_width, line_h,
                    Qt.AlignmentFlag.AlignRight,
                    str(line_num),
                )
                if line_num in self._error_lines:
                    painter.setBrush(QColor(p.danger))
                    painter.setPen(Qt.PenStyle.NoPen)
                    x = self.line_number_area_width() - dot_size - 2
                    y = top + (line_h - dot_size) // 2
                    painter.drawEllipse(x, y, dot_size, dot_size)
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1


# ── VerificationPanel ─────────────────────────────────────────────────────────


class VerificationPanel(QFrame):
    """Collapsible panel showing ValidationIssue list. Emits line_requested on double-click."""

    line_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._expanded = False
        self._issues: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        # Summary row
        summary_row = QWidget()
        row_layout = QHBoxLayout(summary_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_label = QLabel("No recipe loaded")
        self._toggle_btn = QLabel("[▶]")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.mousePressEvent = lambda _: self._toggle()
        row_layout.addWidget(self._summary_label)
        row_layout.addStretch()
        row_layout.addWidget(self._toggle_btn)
        outer.addWidget(summary_row)

        # Issue list
        self._list = QListWidget()
        self._list.setFixedHeight(140)
        self._list.setVisible(False)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        outer.addWidget(self._list)

        # Hint label
        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._hint_label.setVisible(False)
        outer.addWidget(self._hint_label)
        self._list.currentItemChanged.connect(self._on_item_selected)

    def update_issues(self, issues: list) -> None:
        self._issues = issues
        self._list.clear()
        errors = [i for i in issues if i.is_error]
        warnings = [i for i in issues if i.is_warning]

        if not issues:
            self._summary_label.setText("✅ Recipe valid")
        else:
            parts = []
            if errors:
                parts.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}")
            if warnings:
                parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
            self._summary_label.setText(f"❌ {' · '.join(parts)}")

        for issue in issues:
            line_info = f" (line {issue.line})" if issue.line else ""
            prefix = "🔴" if issue.is_error else "🟡"
            item = QListWidgetItem(f"{prefix} {issue.field}: {issue.message}{line_info}")
            item.setData(Qt.ItemDataRole.UserRole, issue)
            self._list.addItem(item)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._list.setVisible(self._expanded)
        self._hint_label.setVisible(self._expanded)
        self._toggle_btn.setText("[▼]" if self._expanded else "[▶]")

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue and issue.line:
            self.line_requested.emit(issue.line)

    def _on_item_selected(self, current: QListWidgetItem | None, _) -> None:
        if current:
            issue = current.data(Qt.ItemDataRole.UserRole)
            if issue:
                self._hint_label.setText(issue.hint)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit_tests/test_rc_model.py -v
```
All tests including the smoke import test should pass.

- [ ] **Step 4: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/rc_widgets.py tests/unit_tests/test_rc_model.py
git commit -m "feat: add YamlEditor, PaletteYamlHighlighter, VerificationPanel"
```

---

### Task 4: `rc_widgets.py` — HeaderStrip + GlobalsEditorDialog

**Files:**
- Modify: `src/pypts/helper_applications/recipe_creator/rc_widgets.py` (append)

**Interfaces:**
- Consumes: `RecipeModel` from `rc_model.py`
- Produces:
  - `GlobalsEditorDialog(QDialog)` — `__init__(model, parent)`, emits no signals, pushes `set_header_field("globals", ...)` on OK
  - `HeaderStrip(QFrame)` — `__init__(model, parent)`, `rebuild()`, `sequence_changed = Signal(int)` (emits current seq index when combo changes)

- [ ] **Step 1: Append `GlobalsEditorDialog` and `HeaderStrip` to `rc_widgets.py`**

Append after the `VerificationPanel` class:

```python
# ── GlobalsEditorDialog ───────────────────────────────────────────────────────


class GlobalsEditorDialog(QDialog):
    """Modal dialog for editing the `globals` header dict."""

    def __init__(self, model, parent=None) -> None:
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QPushButton, QTableWidget, QTableWidgetItem,
        )
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Edit Globals")
        self.resize(420, 300)
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Name", "Initial value"])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_row)
        remove_btn = QPushButton("- Remove")
        remove_btn.clicked.connect(self._remove_row)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate(model.header().get("globals") or {})

    def _populate(self, globals_dict: dict) -> None:
        from PySide6.QtWidgets import QTableWidgetItem
        self._table.setRowCount(0)
        for name, value in globals_dict.items():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(name)))
            self._table.setItem(row, 1, QTableWidgetItem(str(value) if value is not None else ""))

    def _add_row(self) -> None:
        from PySide6.QtWidgets import QTableWidgetItem
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(""))
        self._table.setItem(row, 1, QTableWidgetItem(""))

    def _remove_row(self) -> None:
        for item in self._table.selectedItems():
            self._table.removeRow(item.row())

    def _on_ok(self) -> None:
        result = {}
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 0)
            val_item = self._table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            value = val_item.text().strip() if val_item else ""
            if name:
                result[name] = value
        self._model.set_header_field("globals", result)
        self.accept()


# ── HeaderStrip ───────────────────────────────────────────────────────────────


class HeaderStrip(QFrame):
    """Collapsible strip showing recipe header fields and sequence selector."""

    sequence_changed = Signal(int)

    def __init__(self, model, parent=None) -> None:
        from PySide6.QtWidgets import (
            QCheckBox, QComboBox, QFormLayout, QLineEdit, QPushButton,
        )
        super().__init__(parent)
        self._model = model
        self._expanded = True
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        # Collapse bar
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        self._title_label = QLabel("Recipe header")
        self._collapse_btn = QLabel("[▼]")
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.mousePressEvent = lambda _: self._toggle()
        bar_layout.addWidget(self._title_label)
        bar_layout.addStretch()
        bar_layout.addWidget(self._collapse_btn)
        outer.addWidget(bar)

        # Form
        self._form_widget = QWidget()
        form = QFormLayout(self._form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self._name_edit = QLineEdit()
        self._version_edit = QLineEdit()
        self._desc_edit = QLineEdit()
        self._globals_btn = QPushButton("Edit globals…")
        self._globals_btn.clicked.connect(self._open_globals)
        self._metadata_edit = QLineEdit()

        form.addRow("Name *", self._name_edit)
        form.addRow("Version *", self._version_edit)
        form.addRow("Description", self._desc_edit)
        form.addRow("Globals", self._globals_btn)
        form.addRow("Report metadata", self._metadata_edit)

        # Sequence row
        seq_row = QWidget()
        seq_layout = QHBoxLayout(seq_row)
        seq_layout.setContentsMargins(0, 0, 0, 0)
        self._seq_combo = QComboBox()
        self._seq_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_seq_btn = QPushButton("+")
        add_seq_btn.setFixedWidth(28)
        add_seq_btn.clicked.connect(self._add_sequence)
        remove_seq_btn = QPushButton("−")
        remove_seq_btn.setFixedWidth(28)
        remove_seq_btn.clicked.connect(self._remove_sequence)
        seq_layout.addWidget(self._seq_combo)
        seq_layout.addWidget(add_seq_btn)
        seq_layout.addWidget(remove_seq_btn)
        form.addRow("Sequence", seq_row)

        outer.addWidget(self._form_widget)

        # Wire field changes to model
        self._name_edit.editingFinished.connect(
            lambda: model.set_header_field("name", self._name_edit.text())
        )
        self._version_edit.editingFinished.connect(
            lambda: model.set_header_field("version", self._version_edit.text())
        )
        self._desc_edit.editingFinished.connect(
            lambda: model.set_header_field("description", self._desc_edit.text())
        )
        self._metadata_edit.editingFinished.connect(
            lambda: model.set_header_field(
                "report_metadata",
                [s.strip() for s in self._metadata_edit.text().split(",") if s.strip()],
            )
        )
        self._seq_combo.currentIndexChanged.connect(self._on_seq_changed)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        h = self._model.header()
        self._title_label.setText(h.get("name") or "Recipe header")
        self._name_edit.blockSignals(True)
        self._version_edit.blockSignals(True)
        self._desc_edit.blockSignals(True)
        self._metadata_edit.blockSignals(True)
        self._seq_combo.blockSignals(True)

        self._name_edit.setText(str(h.get("name") or ""))
        self._version_edit.setText(str(h.get("version") or ""))
        self._desc_edit.setText(str(h.get("description") or ""))
        meta = h.get("report_metadata") or []
        self._metadata_edit.setText(", ".join(meta) if isinstance(meta, list) else str(meta))

        prev_idx = self._seq_combo.currentIndex()
        self._seq_combo.clear()
        for seq in self._model.sequences():
            self._seq_combo.addItem(seq.get("sequence_name", ""))
        if prev_idx >= 0 and prev_idx < self._seq_combo.count():
            self._seq_combo.setCurrentIndex(prev_idx)

        self._name_edit.blockSignals(False)
        self._version_edit.blockSignals(False)
        self._desc_edit.blockSignals(False)
        self._metadata_edit.blockSignals(False)
        self._seq_combo.blockSignals(False)

    def current_seq_idx(self) -> int:
        return max(0, self._seq_combo.currentIndex())

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._form_widget.setVisible(self._expanded)
        self._collapse_btn.setText("[▼]" if self._expanded else "[▶]")

    def _open_globals(self) -> None:
        dlg = GlobalsEditorDialog(self._model, self)
        dlg.exec()

    def _on_seq_changed(self, idx: int) -> None:
        self.sequence_changed.emit(idx)

    def _add_sequence(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Add sequence", "Sequence name:")
        if ok and name.strip():
            self._model.add_sequence(name.strip())

    def _remove_sequence(self) -> None:
        idx = self._seq_combo.currentIndex()
        if idx >= 0:
            self._model.remove_sequence(idx)
```

Also add the missing `QDialog` import at the top of the file (edit the existing imports block):
```python
from PySide6.QtWidgets import (
    QDialog,  # add this
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from PySide6.QtWidgets import QApplication; app = QApplication([])
from pypts.helper_applications.recipe_creator.rc_widgets import HeaderStrip, GlobalsEditorDialog
from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
m = RecipeModel()
m.load_yaml('name: T\nversion: \"0.1\"\n---\nsequence_name: Main\nsteps:\n  - steptype: wait\n    step_name: W\n    wait_time: 1.0\n')
h = HeaderStrip(m)
print('HeaderStrip OK')
"
```
Expected: prints `HeaderStrip OK`.

- [ ] **Step 3: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/rc_widgets.py
git commit -m "feat: add HeaderStrip and GlobalsEditorDialog"
```

---

### Task 5: `rc_widgets.py` — StepFormWidget + MappingRowsWidget + MappingYamlWidget

**Files:**
- Modify: `src/pypts/helper_applications/recipe_creator/rc_widgets.py` (append)

**Interfaces:**
- Consumes: `RecipeModel`, `PaletteYamlHighlighter`, `pypts.recipe.rules` (INPUT_TYPES, OUTPUT_TYPES), `pypts.helper_applications.recipe_verificator.verify_string`
- Produces:
  - `MappingRowsWidget(QWidget)` — `__init__(model, seq_idx, step_idx, mapping_key, parent)`, `rebuild()`
  - `MappingYamlWidget(QWidget)` — `__init__(model, seq_idx, step_idx, mapping_key, dark, parent)`, `rebuild()`, `set_dark(dark)`
  - `StepFormWidget(QWidget)` — `__init__(model, seq_idx, step_idx, dark, parent)`, `rebuild()`

- [ ] **Step 1: Append `MappingRowsWidget`, `MappingYamlWidget`, `StepFormWidget` to `rc_widgets.py`**

```python
# ── MappingRowsWidget ─────────────────────────────────────────────────────────


class MappingRowsWidget(QWidget):
    """Editable rows for a step's `inputs` or `outputs` dict."""

    def __init__(self, model, seq_idx: int, step_idx: int, mapping_key: str, parent=None) -> None:
        from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton, QScrollArea
        super().__init__(parent)
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._key = mapping_key  # "inputs" or "outputs"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._rows_widget = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        outer.addWidget(self._rows_widget)

        add_btn = QPushButton(f"+ Add {mapping_key[:-1]}")  # "Add input" / "Add output"
        add_btn.clicked.connect(self._add_row)
        outer.addWidget(add_btn)
        outer.addStretch()

        self.rebuild()

    def rebuild(self) -> None:
        # Clear rows
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        step = self._model.steps(self._seq_idx)[self._step_idx]
        mapping = step.get(self._key) or {}
        for name, spec in mapping.items():
            self._rows_layout.addWidget(self._build_row(name, spec))

    def _build_row(self, name: str, spec) -> QWidget:
        from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton
        from pypts.recipe.rules import INPUT_TYPES, OUTPUT_TYPES

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        name_edit = QLineEdit(name)
        name_edit.setFixedWidth(110)
        rl.addWidget(name_edit)

        if self._key == "inputs":
            types = ["literal"] + list(INPUT_TYPES.keys())
        else:
            types = list(OUTPUT_TYPES.keys())

        type_combo = QComboBox()
        type_combo.addItems(types)
        if isinstance(spec, dict):
            current_type = spec.get("type", types[0])
        else:
            current_type = "literal"
        if current_type in types:
            type_combo.setCurrentText(current_type)
        type_combo.setFixedWidth(90)
        rl.addWidget(type_combo)

        # Value widget placeholder — replaced when type changes
        value_holder = QWidget()
        value_holder_layout = QHBoxLayout(value_holder)
        value_holder_layout.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(value_holder)

        def refresh_value(t: str):
            while value_holder_layout.count():
                item = value_holder_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._add_value_widgets(value_holder_layout, t, spec)

        type_combo.currentTextChanged.connect(refresh_value)
        refresh_value(current_type)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedWidth(28)
        remove_btn.clicked.connect(lambda: self._remove_row(name))
        rl.addWidget(remove_btn)

        return row

    def _add_value_widgets(self, layout, type_name: str, spec) -> None:
        from PySide6.QtWidgets import QComboBox, QLineEdit
        from pypts.recipe.rules import OUTPUT_TYPES

        if type_name == "literal":
            val = spec if not isinstance(spec, dict) else spec.get("value", "")
            edit = QLineEdit(str(val) if val is not None else "")
            layout.addWidget(edit)
        elif type_name == "global":
            val = spec.get("global_name", "") if isinstance(spec, dict) else ""
            edit = QLineEdit(str(val))
            edit.setPlaceholderText("global_name")
            layout.addWidget(edit)
        elif type_name == "equals":
            val = spec.get("value", "") if isinstance(spec, dict) else ""
            edit = QLineEdit(str(val))
            edit.setPlaceholderText("value")
            layout.addWidget(edit)
        elif type_name == "range":
            mn = spec.get("min", "") if isinstance(spec, dict) else ""
            mx = spec.get("max", "") if isinstance(spec, dict) else ""
            from PySide6.QtWidgets import QLineEdit
            min_edit = QLineEdit(str(mn))
            min_edit.setPlaceholderText("min")
            max_edit = QLineEdit(str(mx))
            max_edit.setPlaceholderText("max")
            layout.addWidget(min_edit)
            layout.addWidget(QLabel("…"))
            layout.addWidget(max_edit)
        # passfail / pass: no extra fields

    def _add_row(self) -> None:
        step = self._model.steps(self._seq_idx)[self._step_idx]
        mapping = dict(step.get(self._key) or {})
        new_name = f"new_{self._key[:-1]}_{len(mapping) + 1}"
        if self._key == "inputs":
            mapping[new_name] = ""
        else:
            mapping[new_name] = {"type": "pass"}
        self._model.set_step_field(self._seq_idx, self._step_idx, self._key, mapping)

    def _remove_row(self, name: str) -> None:
        step = self._model.steps(self._seq_idx)[self._step_idx]
        mapping = dict(step.get(self._key) or {})
        mapping.pop(name, None)
        self._model.set_step_field(self._seq_idx, self._step_idx, self._key, mapping)


# ── MappingYamlWidget ─────────────────────────────────────────────────────────


class MappingYamlWidget(QWidget):
    """Small YAML editor for a step's `inputs` or `outputs` block."""

    def __init__(self, model, seq_idx: int, step_idx: int, mapping_key: str, dark: bool = False, parent=None) -> None:
        from PySide6.QtWidgets import QTextEdit
        super().__init__(parent)
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._key = mapping_key
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._editor = QTextEdit()
        self._editor.setFixedHeight(130)
        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(font)
        layout.addWidget(self._editor)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        p = get_palette(dark)
        self._error_label.setStyleSheet(f"color: {p.danger};")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        self._highlighter = PaletteYamlHighlighter(self._editor.document(), dark)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._on_debounce)
        self._editor.textChanged.connect(lambda: self._debounce.start())

        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._highlighter.set_dark(dark)
        p = get_palette(dark)
        self._error_label.setStyleSheet(f"color: {p.danger};")

    def rebuild(self) -> None:
        import yaml as _y
        step = self._model.steps(self._seq_idx)[self._step_idx]
        mapping = step.get(self._key)
        text = _y.dump(mapping, default_flow_style=False) if mapping else ""
        self._updating = True
        self._editor.setPlainText(text.rstrip())
        self._updating = False

    def _on_debounce(self) -> None:
        import yaml as _y
        text = self._editor.toPlainText().strip()
        if not text:
            self._model.set_step_field(self._seq_idx, self._step_idx, self._key, {})
            self._error_label.setVisible(False)
            return
        try:
            parsed = _y.safe_load(text)
            if not isinstance(parsed, dict):
                raise ValueError("Expected a YAML mapping")
            self._model.set_step_field(self._seq_idx, self._step_idx, self._key, parsed)
            self._error_label.setVisible(False)
        except Exception as exc:
            self._error_label.setText(str(exc))
            self._error_label.setVisible(True)


# ── StepFormWidget ────────────────────────────────────────────────────────────


class StepFormWidget(QWidget):
    """Form for editing all fields of a single step."""

    def __init__(self, model, seq_idx: int, step_idx: int, dark: bool = False, parent=None) -> None:
        from PySide6.QtWidgets import (
            QCheckBox, QDoubleSpinBox, QGroupBox, QLineEdit,
            QPushButton, QScrollArea, QStackedWidget,
        )
        super().__init__(parent)
        self._model = model
        self._seq_idx = seq_idx
        self._step_idx = step_idx
        self._dark = dark

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(6)

        # Step type label
        self._type_label = QLabel()
        outer.addWidget(self._type_label)

        # Common fields
        from PySide6.QtWidgets import QFormLayout
        common_group = QGroupBox("Common")
        common_form = QFormLayout(common_group)
        self._name_edit = QLineEdit()
        self._desc_edit = QLineEdit()
        self._skip_check = QCheckBox()
        self._coe_check = QCheckBox()
        common_form.addRow("Name", self._name_edit)
        common_form.addRow("Description", self._desc_edit)
        common_form.addRow("Skip", self._skip_check)
        common_form.addRow("Continue on error", self._coe_check)
        outer.addWidget(common_group)

        self._name_edit.editingFinished.connect(
            lambda: model.set_step_field(seq_idx, step_idx, "step_name", self._name_edit.text())
        )
        self._desc_edit.editingFinished.connect(
            lambda: model.set_step_field(seq_idx, step_idx, "description", self._desc_edit.text())
        )
        self._skip_check.toggled.connect(
            lambda v: model.set_step_field(seq_idx, step_idx, "skip", v)
        )
        self._coe_check.toggled.connect(
            lambda v: model.set_step_field(seq_idx, step_idx, "continue_on_error", v)
        )

        # Type-specific fields area
        self._specific_widget = QWidget()
        self._specific_layout = QFormLayout(self._specific_widget)
        self._specific_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._specific_widget)

        # Inputs section
        inputs_group = QGroupBox("Inputs")
        inputs_vlayout = QVBoxLayout(inputs_group)
        self._inputs_stack = QStackedWidget()
        self._inputs_rows = MappingRowsWidget(model, seq_idx, step_idx, "inputs")
        self._inputs_yaml = MappingYamlWidget(model, seq_idx, step_idx, "inputs", dark)
        self._inputs_stack.addWidget(self._inputs_rows)
        self._inputs_stack.addWidget(self._inputs_yaml)
        toggle_inputs = QPushButton("Rows | YAML")
        toggle_inputs.setCheckable(False)
        toggle_inputs.clicked.connect(
            lambda: self._inputs_stack.setCurrentIndex(1 - self._inputs_stack.currentIndex())
        )
        inputs_vlayout.addWidget(toggle_inputs)
        inputs_vlayout.addWidget(self._inputs_stack)
        outer.addWidget(inputs_group)

        # Outputs section
        outputs_group = QGroupBox("Outputs")
        outputs_vlayout = QVBoxLayout(outputs_group)
        self._outputs_stack = QStackedWidget()
        self._outputs_rows = MappingRowsWidget(model, seq_idx, step_idx, "outputs")
        self._outputs_yaml = MappingYamlWidget(model, seq_idx, step_idx, "outputs", dark)
        self._outputs_stack.addWidget(self._outputs_rows)
        self._outputs_stack.addWidget(self._outputs_yaml)
        toggle_outputs = QPushButton("Rows | YAML")
        toggle_outputs.setCheckable(False)
        toggle_outputs.clicked.connect(
            lambda: self._outputs_stack.setCurrentIndex(1 - self._outputs_stack.currentIndex())
        )
        outputs_vlayout.addWidget(toggle_outputs)
        outputs_vlayout.addWidget(self._outputs_stack)
        outer.addWidget(outputs_group)

        outer.addStretch()
        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._inputs_yaml.set_dark(dark)
        self._outputs_yaml.set_dark(dark)

    def rebuild(self) -> None:
        from pypts.recipe.rules import STEP_TYPE_REQUIRED, STEP_COMMON_DEFAULTS
        from PySide6.QtWidgets import QDoubleSpinBox, QLineEdit

        steps = self._model.steps(self._seq_idx)
        if self._step_idx >= len(steps):
            return
        step = steps[self._step_idx]

        self._type_label.setText(f"Type: {step.get('steptype', '—')}")

        for widget in [self._name_edit, self._desc_edit, self._skip_check, self._coe_check]:
            widget.blockSignals(True)
        self._name_edit.setText(str(step.get("step_name") or ""))
        self._desc_edit.setText(str(step.get("description") or ""))
        self._skip_check.setChecked(bool(step.get("skip", False)))
        self._coe_check.setChecked(bool(step.get("continue_on_error", True)))
        for widget in [self._name_edit, self._desc_edit, self._skip_check, self._coe_check]:
            widget.blockSignals(False)

        # Rebuild type-specific fields
        while self._specific_layout.rowCount():
            self._specific_layout.removeRow(0)
        steptype = step.get("steptype", "")
        for field in STEP_TYPE_REQUIRED.get(steptype, ()):
            if field in ("inputs", "outputs"):
                continue
            if field == "wait_time":
                spin = QDoubleSpinBox()
                spin.setRange(0, 99999)
                spin.setValue(float(step.get(field) or 0))
                spin.valueChanged.connect(
                    lambda v, f=field: self._model.set_step_field(self._seq_idx, self._step_idx, f, v)
                )
                self._specific_layout.addRow(field, spin)
            else:
                edit = QLineEdit(str(step.get(field) or ""))
                edit.editingFinished.connect(
                    lambda f=field, e=edit: self._model.set_step_field(self._seq_idx, self._step_idx, f, e.text())
                )
                self._specific_layout.addRow(field, edit)

        self._inputs_rows.rebuild()
        self._outputs_rows.rebuild()
        self._inputs_yaml.rebuild()
        self._outputs_yaml.rebuild()
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from PySide6.QtWidgets import QApplication; app = QApplication([])
from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_creator.rc_widgets import StepFormWidget
m = RecipeModel()
m.load_yaml('name: T\nversion: \"0.1\"\n---\nsequence_name: Main\nsteps:\n  - steptype: wait\n    step_name: W\n    wait_time: 1.0\n')
w = StepFormWidget(m, 0, 0)
print('StepFormWidget OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/rc_widgets.py
git commit -m "feat: add StepFormWidget, MappingRowsWidget, MappingYamlWidget"
```

---

### Task 6: `rc_widgets.py` — ListStepView + CardStepView + PanelsStepView

**Files:**
- Modify: `src/pypts/helper_applications/recipe_creator/rc_widgets.py` (append)

**Interfaces:**
- Consumes: `RecipeModel`, `StepFormWidget`
- Produces:
  - `ListStepView(QSplitter)` — `__init__(model, parent)`, `rebuild()`, `set_seq_idx(idx)`, `set_dark(dark)`, `step_selected = Signal(int, int)`
  - `CardStepView(QScrollArea)` — same interface
  - `PanelsStepView(QSplitter)` — same interface

All three emit `step_selected = Signal(int, int)` where args are `(seq_idx, step_idx)`.

- [ ] **Step 1: Append the three step views to `rc_widgets.py`**

Add to the imports at the top of the file (edit existing `from PySide6.QtWidgets import ...` block):
```python
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)
```
Also add `from PySide6.QtCore import Qt, QRegularExpression, QTimer, Signal` (already there).

Then append:

```python
# ── ListStepView ──────────────────────────────────────────────────────────────


class ListStepView(QSplitter):
    """Vertical splitter: step list on top, StepFormWidget below."""

    step_selected = Signal(int, int)

    def __init__(self, model, parent=None) -> None:
        from PySide6.QtWidgets import QPushButton
        super().__init__(Qt.Orientation.Vertical, parent)
        self._model = model
        self._seq_idx = 0
        self._dark = False
        self._form: StepFormWidget | None = None

        # Top: list
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        top_layout.addWidget(self._list)
        self.addWidget(top)

        # Bottom: form placeholder
        self._form_container = QScrollArea()
        self._form_container.setWidgetResizable(True)
        self.addWidget(self._form_container)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_seq_idx(self, idx: int) -> None:
        self._seq_idx = idx
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        if self._form:
            self._form.set_dark(dark)

    def rebuild(self) -> None:
        self._list.blockSignals(True)
        prev = self._list.currentRow()
        self._list.clear()
        for step in self._model.steps(self._seq_idx):
            steptype = step.get("steptype", "?")
            name = step.get("step_name", "")
            skip = " [skip]" if step.get("skip") else ""
            self._list.addItem(f"[{steptype}] {name}{skip}")
        self._list.blockSignals(False)
        if prev >= 0 and prev < self._list.count():
            self._list.setCurrentRow(prev)
        self._show_form(self._list.currentRow())

    def _on_row_changed(self, row: int) -> None:
        self._show_form(row)
        if row >= 0:
            self.step_selected.emit(self._seq_idx, row)

    def _on_rows_moved(self, _parent, src, _srcEnd, _dst, dst) -> None:
        to = dst if dst > src else dst
        self._model.move_step(self._seq_idx, src, to)

    def _show_form(self, row: int) -> None:
        if row < 0 or row >= len(self._model.steps(self._seq_idx)):
            self._form_container.setWidget(QWidget())
            self._form = None
            return
        self._form = StepFormWidget(self._model, self._seq_idx, row, self._dark)
        self._form_container.setWidget(self._form)


# ── CardStepView ──────────────────────────────────────────────────────────────


class CardStepView(QScrollArea):
    """Accordion of StepCard widgets, one card per step."""

    step_selected = Signal(int, int)

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._seq_idx = 0
        self._dark = False
        self._expanded_idx: int = -1

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        self.setWidget(self._content)
        self.setWidgetResizable(True)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_seq_idx(self, idx: int) -> None:
        self._seq_idx = idx
        self._expanded_idx = -1
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.rebuild()

    def rebuild(self) -> None:
        # Remove all except the trailing stretch
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, step in enumerate(self._model.steps(self._seq_idx)):
            card = self._make_card(idx, step)
            self._layout.insertWidget(idx, card)

    def _make_card(self, step_idx: int, step: dict) -> QFrame:
        from PySide6.QtWidgets import QPushButton
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(2)

        # Header row
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        steptype = step.get("steptype", "?")
        name = step.get("step_name", "")
        title = QLabel(f"[{steptype}] {name}")
        expand_btn = QPushButton("▼" if step_idx == self._expanded_idx else "▶")
        expand_btn.setFixedWidth(28)
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(expand_btn)
        card_layout.addWidget(header)

        # Body (form)
        form = StepFormWidget(self._model, self._seq_idx, step_idx, self._dark)
        form.setVisible(step_idx == self._expanded_idx)
        card_layout.addWidget(form)

        def toggle():
            if self._expanded_idx == step_idx:
                self._expanded_idx = -1
            else:
                self._expanded_idx = step_idx
            self.rebuild()
            self.step_selected.emit(self._seq_idx, step_idx)

        expand_btn.clicked.connect(toggle)
        title.mousePressEvent = lambda _: toggle()
        return card


# ── PanelsStepView ────────────────────────────────────────────────────────────


class PanelsStepView(QSplitter):
    """Horizontal splitter: slim type+name list on left, StepFormWidget on right."""

    step_selected = Signal(int, int)

    def __init__(self, model, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._model = model
        self._seq_idx = 0
        self._dark = False
        self._form: StepFormWidget | None = None

        # Left: slim list
        self._list = QListWidget()
        self._list.setFixedWidth(180)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self.addWidget(self._list)

        # Right: form in scroll area
        self._form_container = QScrollArea()
        self._form_container.setWidgetResizable(True)
        self.addWidget(self._form_container)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)

        model.changed.connect(self.rebuild)
        self.rebuild()

    def set_seq_idx(self, idx: int) -> None:
        self._seq_idx = idx
        self.rebuild()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        if self._form:
            self._form.set_dark(dark)

    def rebuild(self) -> None:
        self._list.blockSignals(True)
        prev = self._list.currentRow()
        self._list.clear()
        for step in self._model.steps(self._seq_idx):
            steptype = step.get("steptype", "?")
            name = step.get("step_name", "")
            self._list.addItem(f"[{steptype}]\n{name}")
        self._list.blockSignals(False)
        if prev >= 0 and prev < self._list.count():
            self._list.setCurrentRow(prev)
        self._show_form(self._list.currentRow())

    def _on_row_changed(self, row: int) -> None:
        self._show_form(row)
        if row >= 0:
            self.step_selected.emit(self._seq_idx, row)

    def _show_form(self, row: int) -> None:
        if row < 0 or row >= len(self._model.steps(self._seq_idx)):
            self._form_container.setWidget(QWidget())
            self._form = None
            return
        self._form = StepFormWidget(self._model, self._seq_idx, row, self._dark)
        self._form_container.setWidget(self._form)
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from PySide6.QtWidgets import QApplication; app = QApplication([])
from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_creator.rc_widgets import ListStepView, CardStepView, PanelsStepView
m = RecipeModel()
m.load_yaml('name: T\nversion: \"0.1\"\n---\nsequence_name: Main\nsteps:\n  - steptype: wait\n    step_name: W\n    wait_time: 1.0\n')
for cls in [ListStepView, CardStepView, PanelsStepView]:
    w = cls(m)
    print(cls.__name__, 'OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/rc_widgets.py
git commit -m "feat: add ListStepView, CardStepView, PanelsStepView"
```

---

### Task 7: `recipe_creator_new.py` — Main window

**Files:**
- Create: `src/pypts/helper_applications/recipe_creator/recipe_creator_new.py`

**Interfaces:**
- Consumes: All widgets from `rc_widgets.py`, `RecipeModel` from `rc_model.py`, `get_stylesheet` from `pypts.hmi.gui.styles`, `verify_string` from `pypts.helper_applications.recipe_verificator`
- Produces: `RecipeCreatorNewWindow(QMainWindow)` + `if __name__ == "__main__"` entry point

- [ ] **Step 1: Implement `recipe_creator_new.py`**

Create `src/pypts/helper_applications/recipe_creator/recipe_creator_new.py`:

```python
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_creator.rc_widgets import (
    CardStepView,
    HeaderStrip,
    ListStepView,
    PanelsStepView,
    VerificationPanel,
    YamlEditor,
)
from pypts.hmi.gui.styles import get_stylesheet


class RecipeCreatorNewWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._dark = self._detect_dark()
        self._file_path: str = ""
        self._model = RecipeModel()
        self._current_seq_idx = 0
        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.setInterval(200)
        self._verify_timer.timeout.connect(self._run_verification)

        self.setWindowTitle("Recipe Creator")
        self.setGeometry(200, 100, 1600, 1000)
        self.setMinimumWidth(900)

        self._build_menus()
        self._build_toolbar()
        self._build_central()

        self.setStyleSheet(get_stylesheet(self._dark))

        self._model.changed.connect(self._on_model_changed)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        self._act_new = QAction("New", self, shortcut=QKeySequence.StandardKey.New)
        self._act_open = QAction("Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction("Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction("Save As…", self)
        self._act_exit = QAction("Exit", self)
        file_menu.addAction(self._act_new)
        file_menu.addAction(self._act_open)
        file_menu.addSeparator()
        file_menu.addAction(self._act_save)
        file_menu.addAction(self._act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self._act_exit)
        self._act_new.triggered.connect(self._on_new)
        self._act_open.triggered.connect(self._on_open)
        self._act_save.triggered.connect(self._on_save)
        self._act_save_as.triggered.connect(self._on_save_as)
        self._act_exit.triggered.connect(self.close)

        # Edit
        edit_menu = mb.addMenu("Edit")
        self._act_undo = QAction("Undo", self, shortcut=QKeySequence.StandardKey.Undo)
        self._act_redo = QAction("Redo", self, shortcut=QKeySequence.StandardKey.Redo)
        edit_menu.addAction(self._act_undo)
        edit_menu.addAction(self._act_redo)
        edit_menu.addSeparator()
        add_step_menu = edit_menu.addMenu("Add Step")
        from pypts.recipe.rules import STEP_TYPE_REQUIRED
        for steptype in STEP_TYPE_REQUIRED:
            act = QAction(steptype, self)
            act.triggered.connect(lambda checked, t=steptype: self._add_step(t))
            add_step_menu.addAction(act)
        self._act_del_step = QAction("Delete Step", self)
        edit_menu.addAction(self._act_del_step)
        self._act_del_step.triggered.connect(self._delete_selected_step)
        self._act_undo.triggered.connect(self._model.undo_stack.undo)
        self._act_redo.triggered.connect(self._model.undo_stack.redo)
        self._model.undo_stack.canUndoChanged.connect(self._act_undo.setEnabled)
        self._model.undo_stack.canRedoChanged.connect(self._act_redo.setEnabled)
        self._act_undo.setEnabled(False)
        self._act_redo.setEnabled(False)

        # View
        view_menu = mb.addMenu("View")
        self._act_dark = QAction("Toggle Dark Mode", self, checkable=True, checked=self._dark)
        self._act_dark.triggered.connect(self._toggle_dark)
        view_menu.addAction(self._act_dark)
        view_menu.addSeparator()
        self._act_list_view = QAction("List View", self, checkable=True, checked=True)
        self._act_card_view = QAction("Card View", self, checkable=True)
        self._act_panels_view = QAction("Panels View", self, checkable=True)
        for act in [self._act_list_view, self._act_card_view, self._act_panels_view]:
            view_menu.addAction(act)
        self._act_list_view.triggered.connect(lambda: self._switch_view(0))
        self._act_card_view.triggered.connect(lambda: self._switch_view(1))
        self._act_panels_view.triggered.connect(lambda: self._switch_view(2))

        # About
        about_menu = mb.addMenu("About")
        act_gitlab = QAction("GitLab", self)
        act_wiki = QAction("Wiki", self)
        about_menu.addAction(act_gitlab)
        about_menu.addAction(act_wiki)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        for act in [self._act_new, self._act_open, self._act_save, self._act_save_as]:
            tb.addAction(act)
        tb.addSeparator()
        tb.addAction(self._act_undo)
        tb.addAction(self._act_redo)
        tb.addSeparator()

        validate_btn = QAction("Validate", self)
        validate_btn.triggered.connect(self._run_verification)
        tb.addAction(validate_btn)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer_action = QWidgetAction(self)
        spacer_action.setDefaultWidget(spacer)
        tb.addAction(spacer_action)

        logo_path = Path(__file__).parent.parent.parent.parent / "resources" / "images" / "CERN_Logo.png"
        if logo_path.exists():
            from PySide6.QtGui import QPixmap
            logo = QLabel()
            logo.setPixmap(QPixmap(str(logo_path)).scaledToHeight(28, Qt.TransformationMode.SmoothTransformation))
            logo_action = QWidgetAction(self)
            logo_action.setDefaultWidget(logo)
            tb.addAction(logo_action)

    def _build_central(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        # Main horizontal splitter: left panel | YAML editor
        self._hsplit = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        left = QWidget()
        left.setMinimumWidth(340)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._header_strip = HeaderStrip(self._model)
        self._header_strip.sequence_changed.connect(self._on_seq_changed)
        left_layout.addWidget(self._header_strip)

        # Step view stack
        self._view_stack = QStackedWidget()
        self._list_view = ListStepView(self._model)
        self._card_view = CardStepView(self._model)
        self._panels_view = PanelsStepView(self._model)
        self._view_stack.addWidget(self._list_view)
        self._view_stack.addWidget(self._card_view)
        self._view_stack.addWidget(self._panels_view)
        left_layout.addWidget(self._view_stack)

        # Step toolbar
        step_bar = QWidget()
        step_bar_layout = QVBoxLayout(step_bar)
        step_bar_layout.setContentsMargins(4, 4, 4, 4)
        add_btn = QPushButton("+ Add Step ▼")
        add_btn.clicked.connect(lambda: self._add_step("wait"))
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_selected_step)
        from PySide6.QtWidgets import QHBoxLayout
        btn_row = QHBoxLayout()
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        step_bar_layout.addLayout(btn_row)
        left_layout.addWidget(step_bar)

        self._hsplit.addWidget(left)

        # Right panel: YAML editor
        self._yaml_editor = YamlEditor()
        self._yaml_editor.set_dark(self._dark)
        self._yaml_editor.text_committed.connect(self._on_yaml_committed)
        self._hsplit.addWidget(self._yaml_editor)
        self._hsplit.setStretchFactor(0, 0)
        self._hsplit.setStretchFactor(1, 1)

        root_layout.addWidget(self._hsplit)

        # Verification panel
        self._verification = VerificationPanel()
        self._verification.line_requested.connect(self._yaml_editor.go_to_line)
        root_layout.addWidget(self._verification)

        # Log console
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        root_layout.addWidget(self._log)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_model_changed(self) -> None:
        self._sync_yaml_from_model()
        self._verify_timer.start()
        self._update_title()

    def _sync_yaml_from_model(self) -> None:
        self._yaml_editor.set_content(self._model.to_yaml())

    def _on_yaml_committed(self, text: str) -> None:
        self._model.set_from_text(text)

    def _on_seq_changed(self, idx: int) -> None:
        self._current_seq_idx = idx
        for view in [self._list_view, self._card_view, self._panels_view]:
            view.set_seq_idx(idx)

    def _switch_view(self, idx: int) -> None:
        self._view_stack.setCurrentIndex(idx)
        for i, act in enumerate([self._act_list_view, self._act_card_view, self._act_panels_view]):
            act.setChecked(i == idx)

    def _toggle_dark(self, dark: bool) -> None:
        self._dark = dark
        self.setStyleSheet(get_stylesheet(dark))
        self._yaml_editor.set_dark(dark)
        for view in [self._list_view, self._card_view, self._panels_view]:
            view.set_dark(dark)

    def _run_verification(self) -> None:
        from pypts.helper_applications.recipe_verificator import verify_string
        issues = verify_string(self._model.to_yaml())
        self._verification.update_issues(issues)
        error_lines: set[int] = {i.line for i in issues if i.line and i.is_error}
        self._yaml_editor.set_error_lines(error_lines)

    def _add_step(self, steptype: str) -> None:
        steps = self._model.steps(self._current_seq_idx)
        self._model.add_step(self._current_seq_idx, steptype, len(steps))

    def _delete_selected_step(self) -> None:
        view = self._view_stack.currentWidget()
        if hasattr(view, "_list"):
            row = view._list.currentRow()
            if row >= 0:
                self._model.remove_step(self._current_seq_idx, row)

    def _update_title(self) -> None:
        name = self._file_path or "Unsaved"
        mod = " *" if self._model.is_modified() else ""
        self.setWindowTitle(f"Recipe Creator — {name}{mod}")

    def _on_new(self) -> None:
        if self._model.is_modified():
            if not self._ask_discard():
                return
        self._model.load_yaml(
            "name: New Recipe\nversion: \"0.1\"\n---\nsequence_name: Main\nsteps: []\n"
        )
        self._file_path = ""
        self._update_title()
        self._log_msg("New recipe created.")

    def _on_open(self) -> None:
        if self._model.is_modified():
            if not self._ask_discard():
                return
        path, _ = QFileDialog.getOpenFileName(self, "Open recipe", "", "YAML Files (*.yml *.yaml)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            issues = self._model.load_yaml(text)
            self._file_path = path
            self._update_title()
            self._log_msg(f"Opened: {path}")
            self._verification.update_issues(issues)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def _on_save(self) -> None:
        if not self._file_path:
            self._on_save_as()
            return
        self._save_to(self._file_path)

    def _on_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save As", self._file_path or "", "YAML Files (*.yml *.yaml)")
        if path:
            self._file_path = path
            self._save_to(path)

    def _save_to(self, path: str) -> None:
        try:
            Path(path).write_text(self._model.to_yaml(), encoding="utf-8")
            self._model.undo_stack.setClean()
            self._update_title()
            self._log_msg(f"Saved: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _ask_discard(self) -> bool:
        result = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Discard

    def _log_msg(self, msg: str) -> None:
        self._log.append(msg)

    @staticmethod
    def _detect_dark() -> bool:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        from PySide6.QtCore import Qt
        return scheme == Qt.ColorScheme.Dark


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> int:
    app = QApplication(sys.argv)
    win = RecipeCreatorNewWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke test — window opens**

```bash
cd C:/Git/pts-framework
python -m pypts.helper_applications.recipe_creator.recipe_creator_new
```
Expected: window opens showing the header strip, left panel with empty step list, YAML editor on the right. No tracebacks in the terminal. Test:
1. File → New → header strip shows "New Recipe"
2. Edit → Add Step → userinteraction → step appears in left list
3. Undo (Ctrl+Z) → step disappears
4. Redo (Ctrl+Y) → step reappears
5. YAML editor reflects all changes
6. View → Card View → layout switches to accordion cards
7. View → Panels View → layout switches to list+form panels
8. View → List View → back to original
9. View → Toggle Dark Mode → colours change
10. File → Save As → saves to a .yml file

- [ ] **Step 3: Run quality gates**

```bash
ruff check src/pypts/helper_applications/recipe_creator/
pytest tests/unit_tests/test_rc_model.py -v
```
Fix any ruff errors (mainly E501 long lines — add `# noqa: E501` for UI string lines).

- [ ] **Step 4: Commit**

```bash
git add src/pypts/helper_applications/recipe_creator/recipe_creator_new.py
git commit -m "feat: add recipe_creator_new.py main window — full redesign"
```

---

## Spec coverage check

| Spec section | Covered by task |
|---|---|
| §2 Fix list (7 patches) | Task 1 |
| §3 File structure | All tasks |
| §4 RecipeModel + commands | Task 2 |
| §5 Main window layout + menus + toolbar | Task 7 |
| §6 HeaderStrip + GlobalsEditorDialog | Task 4 |
| §7 Three step views (List/Card/Panels) | Task 6 |
| §8 StepFormWidget + MappingRowsWidget + MappingYamlWidget | Task 5 |
| §9 YAML editor with error gutter + debounce + sync lock | Tasks 3, 7 |
| §10 VerificationPanel | Task 3 |
| §11 Dark/light theming via palette.py | Tasks 3, 7 |
| §12 Sync invariant (model.to_yaml == editor text) | Task 7 `_on_model_changed` + `_on_yaml_committed` |
| §13 Out of scope | Not implemented (correct) |
