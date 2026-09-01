# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Remove Cache dialog: what will go, then what went.

Two pages in a `QStackedWidget` rather than two popups. A confirm-then-report
action that throws a second message box at the operator is the thing everybody
dismisses without reading; this asks and answers in the same small window, and
the window only closes when they close it.

It is **pure presentation**. It is handed the survey and a callable that does
the removal, so a test can drive the whole dialog without deleting anything.
It never calls `data_removal.remove()` by name.

The styling lives in `styles.py` with everything else (object names
`cacheDialog*`), so the dialog follows the light/dark theme like every other
widget rather than carrying its own colours.
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pypts.utilities.data_removal import RemovableItem, RemovalOutcome, remove, total_bytes

#: Ticked when the dialog opens. The recents list and config.ini are pypts'
#: own housekeeping; reports and run logs are test records, so removing them
#: stays a deliberate extra click rather than the default.
DEFAULT_SELECTION = ("state", "config")

#: Left margin that lines a row's detail text up with its checkbox's label.
_CHECKBOX_INDENT = 22


def count_of(number: int, noun: str) -> str:
    """"1 item" / "71 items". A dialog nobody wants to read twice says it once."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def format_size(byte_count: int) -> str:
    """"1.4 MB". Sizes are read at a glance, so one decimal is plenty."""
    if byte_count <= 0:
        return "empty"
    size = float(byte_count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class RemoveCacheDialog(QDialog):
    """Ask, remove, report - in one window."""

    def __init__(
        self,
        items: Sequence[RemovableItem],
        remover: Callable[[Sequence[RemovableItem]], RemovalOutcome] = remove,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._remover = remover
        self.outcome: RemovalOutcome | None = None
        #: What was ticked when the operator confirmed - the result page reads
        #: this rather than the full survey, so it only reports on what went.
        self.removed_items: list[RemovableItem] = []
        #: One checkbox per category, by key. The dialog's whole state.
        self.checkboxes: dict[str, QCheckBox] = {}

        self.setWindowTitle("Remove Cache")
        self.setObjectName("cacheDialog")
        self.setModal(True)
        self.setMinimumWidth(460)

        #: "confirm" until the operator says yes, "result" afterwards.
        self.showing = "confirm"
        self.confirm_page = self._build_confirm_page()
        self.result_page: QWidget | None = None

        # Not a QStackedWidget: its sizeHint is the tallest page whatever the
        # size policies say, so the short result page would be shown inside the
        # confirm page's height with a lake of empty space under it. Swapping
        # the widget lets the window shrink to what it is actually showing.
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.confirm_page)

    # --- Page 1: what will go --------------------------------------------------

    def _build_confirm_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(0)

        title = QLabel("Remove Cache")
        title.setObjectName("cacheDialogTitle")
        column.addWidget(title)

        subtitle = QLabel("Choose what to delete from this machine.")
        subtitle.setObjectName("cacheDialogSubtitle")
        subtitle.setWordWrap(True)
        column.addWidget(subtitle)
        column.addSpacing(14)

        for index, item in enumerate(self._items):
            if index > 0:
                column.addWidget(self._separator())
            column.addWidget(self._item_row(item))

        column.addSpacing(12)
        column.addWidget(self._total_row())

        column.addSpacing(16)
        column.addLayout(self._confirm_buttons())

        # Only now: every box exists, and so do the two widgets the handler
        # touches. One call settles the total and the button.
        for box in self.checkboxes.values():
            box.toggled.connect(self._selection_changed)
        self._selection_changed()
        return page

    def _item_row(self, item: RemovableItem) -> QWidget:
        row = QWidget()
        row.setObjectName("cacheDialogRow")
        if item.location:
            row.setToolTip(item.location)

        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setSpacing(2)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)

        box = QCheckBox(item.label)
        box.setObjectName("cacheDialogCheck")
        # An empty category cannot be chosen: there would be nothing to do.
        box.setEnabled(item.item_count > 0)
        box.setChecked(item.item_count > 0 and item.key in DEFAULT_SELECTION)
        self.checkboxes[item.key] = box
        heading.addWidget(box)
        heading.addStretch()

        size = QLabel(self._size_text(item))
        size.setObjectName("cacheDialogSize")
        size.setProperty("empty", item.item_count == 0)
        heading.addWidget(size)
        outer.addLayout(heading)

        # Indented to the checkbox's text, not its box.
        under = QVBoxLayout()
        under.setContentsMargins(_CHECKBOX_INDENT, 0, 0, 0)
        under.setSpacing(2)

        detail = QLabel(item.detail)
        detail.setObjectName("cacheDialogDetail")
        detail.setWordWrap(True)
        under.addWidget(detail)

        if item.kept_note:
            note = QLabel(item.kept_note)
            note.setObjectName("cacheDialogNote")
            note.setWordWrap(True)
            under.addWidget(note)
        outer.addLayout(under)
        return row

    @staticmethod
    def _size_text(item: RemovableItem) -> str:
        if item.item_count == 0:
            return "nothing to remove"
        if item.item_count == 1:
            return format_size(item.size_bytes)
        return f"{count_of(item.item_count, 'item')} · {format_size(item.size_bytes)}"

    def _total_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("Total")
        label.setObjectName("cacheDialogTotalLabel")
        layout.addWidget(label)
        layout.addStretch()

        self.total_label = QLabel(format_size(total_bytes(self.selected_items())))
        self.total_label.setObjectName("cacheDialogTotal")
        layout.addWidget(self.total_label)
        return row

    # --- Selection ---------------------------------------------------------------

    def selected_items(self) -> list[RemovableItem]:
        """The ticked categories, and only those. What removal acts on."""
        return [
            item
            for item in self._items
            if self.checkboxes[item.key].isChecked() and item.item_count > 0
        ]

    def _selection_changed(self) -> None:
        """Keep the total and the confirm button honest as boxes are ticked."""
        selected = self.selected_items()
        self.total_label.setText(format_size(total_bytes(selected)))
        self.remove_button.setEnabled(bool(selected))
        if any(item.item_count for item in self._items):
            self.remove_button.setText("Remove selected")
        else:
            self.remove_button.setText("Nothing to remove")

    def _confirm_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setDefault(True)  # the safe button is the default one
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

        # Text and enabled state are settled by _selection_changed().
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.setObjectName("cacheDialogRemoveBtn")
        self.remove_button.clicked.connect(self._do_remove)
        layout.addWidget(self.remove_button)
        return layout

    # --- Page 2: what went -----------------------------------------------------

    def _do_remove(self) -> None:
        self.removed_items = self.selected_items()
        self.outcome = self._remover(self.removed_items)

        # Hidden and taken out of the layout, not deleted: the caller may still
        # hold a reference to a button on it.
        self.body.removeWidget(self.confirm_page)
        self.confirm_page.hide()

        self.result_page = self._build_result_page(self.outcome)
        self.body.addWidget(self.result_page)
        self.showing = "result"
        self.adjustSize()

    def _build_result_page(self, outcome: RemovalOutcome) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(0)

        title = QLabel("Removed" if not outcome.failures else "Partly removed")
        title.setObjectName("cacheDialogTitle")
        column.addWidget(title)

        if outcome.removed_count == 0:
            summary = "There was nothing to remove."
        else:
            summary = (
                f"{count_of(outcome.removed_count, 'item')} deleted, "
                f"{format_size(outcome.removed_bytes)} freed."
            )
        summary_label = QLabel(summary)
        summary_label.setObjectName("cacheDialogSubtitle")
        summary_label.setWordWrap(True)
        column.addWidget(summary_label)

        kept = [item.kept_note for item in self.removed_items if item.kept_note]
        for note in kept:
            note_label = QLabel(note)
            note_label.setObjectName("cacheDialogNote")
            note_label.setWordWrap(True)
            column.addSpacing(8)
            column.addWidget(note_label)

        if outcome.failures:
            column.addSpacing(10)
            failed = QLabel("Could not be removed:\n" + "\n".join(outcome.failures))
            failed.setObjectName("cacheDialogFailure")
            failed.setWordWrap(True)
            column.addWidget(failed)

        if any(item.key == "config" for item in self.removed_items):
            column.addSpacing(10)
            restart = QLabel(
                "config.ini is recreated from the template the next time pypts starts."
            )
            restart.setObjectName("cacheDialogDetail")
            restart.setWordWrap(True)
            column.addWidget(restart)

        column.addStretch()
        column.addSpacing(16)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("primaryBtn")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        column.addLayout(buttons)
        return page

    # --- Bits ------------------------------------------------------------------

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setObjectName("cacheDialogSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line


def show_remove_cache_dialog(
    items: Sequence[RemovableItem],
    remover: Callable[[Sequence[RemovableItem]], RemovalOutcome] = remove,
    parent: QWidget | None = None,
) -> RemovalOutcome | None:
    """Open it modally; the outcome, or None if the operator cancelled."""
    dialog = RemoveCacheDialog(items, remover, parent)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.exec()
    return dialog.outcome
