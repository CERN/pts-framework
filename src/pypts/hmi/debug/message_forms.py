# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Turning a message dataclass into an editable form, and back into an instance.

The alternative was a hand-written form per message. That would have been dead
the first time somebody added a field: the roadmap has whole phases still to
land, each bringing messages with it. Introspection means a message declared in
`pypts.messages` shows up in the console with no change here at all.

Only the shapes the message layer actually uses are supported - see EDITORS -
and an unsupported field is reported rather than guessed at, so a form is either
correct or visibly refuses to build.
"""

from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints
from uuid import UUID, uuid4

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class UnsupportedField(Exception):
    """No editor exists for a field's type. Carries the text the panel shows."""


# --- Editors ------------------------------------------------------------------
#
# Each wraps one widget and knows how to read a typed value back out of it. They
# are deliberately tiny and dumb; validation is whatever the constructor of the
# message itself does with the value.


class TextEditor:
    """str, and the fallback for int/float via `parse`."""

    def __init__(self, parse=str, initial: str = "") -> None:
        self.widget = QLineEdit(initial)
        self._parse = parse

    def value(self):
        return self._parse(self.widget.text())


class BoolEditor:
    def __init__(self, initial: bool = False) -> None:
        self.widget = QCheckBox()
        self.widget.setChecked(initial)

    def value(self):
        return self.widget.isChecked()


class EnumEditor:
    """A combo box over an Enum's members. Covers ResultType and ErrorSeverity."""

    def __init__(self, enum_type: type[Enum]) -> None:
        self.widget = QComboBox()
        self._members = list(enum_type)
        for member in self._members:
            self.widget.addItem(member.name)

    def value(self):
        return self._members[self.widget.currentIndex()]


class UuidEditor:
    """
    A UUID field, pre-filled with a fresh one.

    Pre-filling matters: every request/response pair in the framework is joined
    by a request_id, so an empty box would make the common case - fire a
    UserPromptRequest and watch it come back - a typing exercise.
    """

    def __init__(self) -> None:
        self.widget = QLineEdit(str(uuid4()))

    def value(self):
        return UUID(self.widget.text().strip())


class StringTupleEditor:
    """tuple[str, ...] as a comma-separated line. Used by UserPromptRequest.options."""

    def __init__(self, initial: str = "") -> None:
        self.widget = QLineEdit(initial)

    def value(self):
        text = self.widget.text().strip()
        if not text:
            return ()
        return tuple(part.strip() for part in text.split(","))


class OptionalEditor:
    """
    An `X | None` field: the editor for X, plus a box that forces None.

    Needed by more of the protocol than it looks - a cancelled UserPromptResponse
    and a declined SerialNumberResponse are both expressed as None, and both are
    cases a frontend gets wrong if it is never made to handle them.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self._none_box = QCheckBox("None")

        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner.widget)
        layout.addWidget(self._none_box)

        self._none_box.toggled.connect(lambda checked: inner.widget.setDisabled(checked))

    def value(self):
        return None if self._none_box.isChecked() else self._inner.value()


class NestedEditor:
    """
    A field whose type is itself a message dataclass.

    Two of them exist today - StepFinished.outcome and ModuleErrorReported.error
    - and both are exactly the messages worth simulating, so nesting is not
    optional. Recursion is unbounded because the message layer is a tree of
    frozen dataclasses with no cycles; a cycle would be a bug in the protocol,
    not something to defend against here.
    """

    def __init__(self, message_type: type) -> None:
        self._form = MessageForm(message_type)
        self.widget = QGroupBox(message_type.__name__)
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._form.widget)

    def value(self):
        return self._form.build()


#: Field types with a direct editor. Anything else is either an Enum, a nested
#: dataclass, an optional, or unsupported.
EDITORS = {
    str: lambda: TextEditor(str),
    int: lambda: TextEditor(int, "0"),
    float: lambda: TextEditor(float, "0.0"),
    bool: BoolEditor,
    UUID: UuidEditor,
}


def editor_for(field_type):
    """
    Build the editor for one annotated type, or raise UnsupportedField.

    Order matters: optionals are unwrapped before anything else, because
    `str | None` is neither `str` nor an Enum nor a dataclass.
    """
    if field_type in EDITORS:
        return EDITORS[field_type]()

    origin = get_origin(field_type)

    # `X | None`, in either spelling. Anything wider than two members is a union
    # of real alternatives and would need a type picker, which nothing needs yet.
    if origin in (Union, UnionType):
        args = [arg for arg in get_args(field_type) if arg is not type(None)]
        if len(args) == 1 and type(None) in get_args(field_type):
            return OptionalEditor(editor_for(args[0]))
        raise UnsupportedField(f"union of {len(args)} types")

    if origin is tuple:
        args = get_args(field_type)
        if args and args[0] is str:
            return StringTupleEditor()
        # tuple[StepOutcome, ...] - RunFinished.outcomes. It defaults to (), and
        # a table-of-forms editor is not worth building for it: a run's outcomes
        # are better simulated by firing the StepFinished events one at a time.
        raise UnsupportedField(f"tuple of {args[0].__name__ if args else '?'}")

    if isinstance(field_type, type) and issubclass(field_type, Enum):
        return EnumEditor(field_type)

    if is_dataclass(field_type):
        return NestedEditor(field_type)

    raise UnsupportedField(getattr(field_type, "__name__", str(field_type)))


# --- The form ------------------------------------------------------------------


class MessageForm:
    """
    An editable form for one message type.

    Attributes:
        widget: the form, to drop into a layout.
        problems: one line per field that could not be given an editor. Empty
            means build() will work; non-empty is shown to the user and the
            Send button is disabled, because a message built from a partial
            form would be a lie about what was sent.
    """

    def __init__(self, message_type: type) -> None:
        self.message_type = message_type
        self.editors: dict[str, object] = {}
        self.problems: list[str] = []

        self.widget = QWidget()
        layout = QFormLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # get_type_hints rather than field.type: the latter is a string whenever
        # the defining module uses postponed annotations, and resolving it is
        # exactly this function's job.
        hints = get_type_hints(message_type)

        for field in fields(message_type):
            try:
                editor = editor_for(hints[field.name])
            except UnsupportedField as exc:
                if field.default is MISSING and field.default_factory is MISSING:
                    self.problems.append(f"{field.name}: no editor for {exc}")
                else:
                    # It has a default, so the message is still constructible.
                    # Say so rather than leaving a silently missing row.
                    placeholder = QLineEdit(f"<default> ({exc})")
                    placeholder.setEnabled(False)
                    layout.addRow(field.name, placeholder)
                continue

            self.editors[field.name] = editor
            layout.addRow(field.name, editor.widget)

    def build(self):
        """Construct the message. Only call when `problems` is empty."""
        return self.message_type(**{name: e.value() for name, e in self.editors.items()})
