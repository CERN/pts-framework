# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import copy
import io
from typing import Any

from ruamel.yaml import YAML
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack, QUndoCommand

from pypts.recipe.rules import (
    STEP_TYPE_REQUIRED,
    STEP_COMMON_DEFAULTS,
    STEP_TYPE_DEFAULTS,
    SEQUENCE_DEFAULTS,
)


_MISSING = object()


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
        self.undo_stack.push(
            _SetDictField(self, self._docs[0], key, value, f"Set header.{key}")
        )

    def set_sequence_field(self, seq_idx: int, key: str, value: Any) -> None:
        self.undo_stack.push(
            _SetDictField(self, self._docs[seq_idx + 1], key, value, f"Set seq.{key}")
        )

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
        step.update(copy.deepcopy(STEP_TYPE_DEFAULTS.get(steptype, {})))
        return step


# ── Commands ──────────────────────────────────────────────────────────────────


class _SetDictField(QUndoCommand):
    def __init__(
        self, model: RecipeModel, target: dict, key: str, new: Any, text: str
    ) -> None:
        super().__init__(text)
        self._model = model
        self._target = target
        self._key = key
        self._new = new
        self._old = target.get(key, _MISSING)

    def redo(self) -> None:
        self._target[self._key] = self._new
        self._model._notify()

    def undo(self) -> None:
        if self._old is _MISSING:
            self._target.pop(self._key, None)
        else:
            self._target[self._key] = self._old
        self._model._notify()


class _AddStep(QUndoCommand):
    def __init__(
        self, model: RecipeModel, seq_idx: int, steptype: str, position: int
    ) -> None:
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
    def __init__(
        self, model: RecipeModel, seq_idx: int, from_idx: int, to_idx: int
    ) -> None:
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
        self._seq: dict = {
            "sequence_name": name,
            "description": SEQUENCE_DEFAULTS.get("description", ""),
            "steps": [],
            "teardown_steps": [],
        }

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
        except Exception:  # noqa: BLE001
            pass
        self._model._notify()

    def undo(self) -> None:
        try:
            self._model._docs = list(self._model._yaml.load_all(self._old_text))
        except Exception:  # noqa: BLE001
            pass
        self._model._notify()
