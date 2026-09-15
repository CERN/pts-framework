# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import copy
import io
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack, QUndoCommand

from pypts.helper_applications.recipe_verificator import verify_string
from pypts.recipe.rules import (
    STEP_TYPE_REQUIRED,
    STEP_COMMON_DEFAULTS,
    STEP_TYPE_DEFAULTS,
    SEQUENCE_DEFAULTS,
)


_MISSING = object()

#: Keys the tree shows as text. A list or mapping there cannot be shown.
_HEADER_TEXT_KEYS = ("name", "version", "description")
_SEQUENCE_TEXT_KEYS = ("sequence_name", "description")
_STEP_TEXT_KEYS = ("steptype", "step_name", "description")


def _structure_problem(docs: list) -> str:
    """Why the tree cannot show these parsed docs, or "" when it can.

    Only the shape the tree needs is checked. Whether the recipe is right is
    the verificator's job.
    """
    for index, doc in enumerate(docs):
        if not isinstance(doc, dict):
            return f"Document {index + 1} is not a mapping."
    if not docs:
        return ""
    header = docs[0]
    problem = _text_keys_problem(header, _HEADER_TEXT_KEYS, "The header")
    if problem:
        return problem
    if header.get("globals") is not None and not isinstance(header["globals"], dict):
        return "The header's globals must be a mapping."
    for seq_number, sequence in enumerate(docs[1:], start=1):
        where = f"Sequence {seq_number}"
        problem = _text_keys_problem(sequence, _SEQUENCE_TEXT_KEYS, where)
        if problem:
            return problem
        for key in ("steps", "teardown_steps"):
            if key not in sequence:
                continue
            steps = sequence[key]
            if not isinstance(steps, list):
                return f"{where}: {key} must be a list."
            for step_number, step in enumerate(steps, start=1):
                problem = _step_problem(step, f"{where}, {key} entry {step_number}")
                if problem:
                    return problem
    return ""


def _step_problem(step: Any, where: str) -> str:
    if not isinstance(step, dict):
        return f"{where} is not a mapping."
    problem = _text_keys_problem(step, _STEP_TEXT_KEYS, where)
    if problem:
        return problem
    for key in ("inputs", "outputs"):
        if step.get(key) is not None and not isinstance(step[key], dict):
            return f"{where}: {key} must be a mapping."
    wait_time = step.get("wait_time")
    if wait_time is not None and wait_time != "":
        try:
            float(wait_time)
        except (TypeError, ValueError):
            return f"{where}: wait_time must be a number."
    return ""


def _text_keys_problem(mapping: dict, keys: tuple[str, ...], where: str) -> str:
    for key in keys:
        if isinstance(mapping.get(key), (dict, list)):
            return f"{where}: {key} must be text, not a list or mapping."
    return ""


class RecipeModel(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self._docs: list[dict] = []
        # While the recipe text cannot be shown as a tree, _invalid_text holds
        # exactly what the user wrote and _invalid_reason says why. _docs keeps
        # the last recipe that could be shown, untouched. None means valid.
        self._invalid_text: str | None = None
        self._invalid_reason = ""
        self._invalid_line = 0
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self.undo_stack.cleanChanged.connect(lambda _: self.changed.emit())

    # ── Read ──────────────────────────────────────────────────────────────────

    def to_yaml(self) -> str:
        """The recipe text. While invalid, the user's text exactly as written."""
        if self._invalid_text is not None:
            return self._invalid_text
        buf = io.StringIO()
        self._yaml.dump_all(self._docs, buf)
        return buf.getvalue()

    def is_valid(self) -> bool:
        """False while the recipe text cannot be shown as a tree."""
        return self._invalid_text is None

    def invalid_reason(self) -> str:
        return self._invalid_reason

    def invalid_line(self) -> int:
        """1-based line of the problem, or 0 when it has no line."""
        return self._invalid_line

    def header(self) -> dict:
        return self._docs[0] if self._docs else {}

    def sequences(self) -> list[dict]:
        return self._docs[1:] if len(self._docs) > 1 else []

    def sequence(self, idx: int) -> dict:
        return self._docs[idx + 1]

    def steps(self, seq_idx: int, teardown: bool = False) -> list[dict]:
        key = "teardown_steps" if teardown else "steps"
        if seq_idx >= len(self._docs) - 1:
            return []
        return self.sequence(seq_idx).get(key, [])

    def is_modified(self) -> bool:
        return not self.undo_stack.isClean()

    # ── Write — all push a command ────────────────────────────────────────────
    # While the recipe is invalid the tree is grayed out, but a field losing
    # focus can still fire. The tree edits are refused then: they would change
    # a recipe the user can no longer see.

    def set_header_field(self, key: str, value: Any) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(
            _SetDictField(self, self._docs[0], key, value, f"Set header.{key}")
        )

    def set_sequence_field(self, seq_idx: int, key: str, value: Any) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(
            _SetDictField(self, self._docs[seq_idx + 1], key, value, f"Set seq.{key}")
        )

    def set_step_field(self, seq_idx: int, step_idx: int, key: str, value: Any) -> None:
        if not self.is_valid():
            return
        step = self.steps(seq_idx)[step_idx]
        self.undo_stack.push(_SetDictField(self, step, key, value, f"Set step.{key}"))

    def add_step(self, seq_idx: int, steptype: str, position: int) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(_AddStep(self, seq_idx, steptype, position))

    def remove_step(self, seq_idx: int, step_idx: int) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(_RemoveStep(self, seq_idx, step_idx))

    def move_step(self, seq_idx: int, from_idx: int, to_idx: int) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(_MoveStep(self, seq_idx, from_idx, to_idx))

    def add_sequence(self, name: str) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(_AddSequence(self, name))

    def remove_sequence(self, seq_idx: int) -> None:
        if not self.is_valid():
            return
        self.undo_stack.push(_RemoveSequence(self, seq_idx))

    def load_yaml(self, text: str) -> list:
        """Replace the recipe from YAML text. Clears undo stack. Returns ValidationIssues.

        Text that cannot be shown as a tree is still loaded, as invalid, so a
        broken file can be opened and fixed in the editor.
        """
        docs, reason, line = self._parse(text)
        if reason:
            self._docs = []
            self._set_invalid(text, reason, line)
        else:
            self._docs = docs
            self._set_invalid(None, "", 0)
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.changed.emit()
        return verify_string(text)

    def set_from_text(self, text: str) -> None:
        """Replace the recipe from YAML text — undoable, also when the text is invalid."""
        self.undo_stack.push(_SetFromText(self, text))

    def undo_to_last_valid(self) -> None:
        """Undo until the recipe can be shown as a tree again, or nothing is left to undo."""
        while not self.is_valid() and self.undo_stack.canUndo():
            self.undo_stack.undo()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _notify(self) -> None:
        self.changed.emit()

    def _set_invalid(self, text: str | None, reason: str, line: int) -> None:
        self._invalid_text = text
        self._invalid_reason = reason
        self._invalid_line = line

    def _parse(self, text: str) -> tuple[list, str, int]:
        """Return (docs, reason, line). reason is "" when the tree can show the docs."""
        try:
            docs = list(self._yaml.load_all(text))
        except YAMLError as exc:
            line = 0
            mark = getattr(exc, "problem_mark", None)
            if mark is not None:
                line = mark.line + 1
            return [], f"The YAML cannot be parsed: {exc}", line
        reason = _structure_problem(docs)
        return docs, reason, 0

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
    """Replace the recipe with editor text, whether or not the tree can show it.

    Both states are kept as they are, not re-parsed: undo puts back the very
    same docs objects, so older commands on the stack still point at them.
    """

    def __init__(self, model: RecipeModel, text: str) -> None:
        super().__init__("Edit YAML")
        self._model = model
        self._old_docs = model._docs
        self._old_invalid = (model._invalid_text, model._invalid_reason, model._invalid_line)
        docs, reason, line = model._parse(text)
        if reason:
            # Invalid: the tree keeps showing (grayed out) the docs it had.
            self._new_docs = model._docs
            self._new_invalid: tuple[str | None, str, int] = (text, reason, line)
        else:
            self._new_docs = docs
            self._new_invalid = (None, "", 0)

    def redo(self) -> None:
        self._model._docs = self._new_docs
        self._model._set_invalid(*self._new_invalid)
        self._model._notify()

    def undo(self) -> None:
        self._model._docs = self._old_docs
        self._model._set_invalid(*self._old_invalid)
        self._model._notify()
