# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Settings -> Storage: remove what pypts has stored on this machine - the recent
recipes list, reports and run logs.

Two views in one panel rather than two popups. A confirm-then-report action that
throws a second message box at the operator is the thing everybody dismisses
without reading; this asks and answers in the same place.

The configuration is not offered here. `config.ini` belongs to Settings ->
Advanced -> Restore default settings, which puts it back from the template and
restarts pypts; nothing removed on this page needs a restart.

It is **pure presentation**. It is handed a `survey` callable and a `remover`
callable, so a test can drive the whole panel without deleting anything. It
never calls `data_removal.remove()` by name - that is only the default.

The survey is a callable rather than a list so the panel can take it fresh: the
Settings dialog builds the panel only when the page is first opened (walking
the reports and logs folders must not slow Settings down), and **Done** after a
removal surveys again, so the sizes shown are always the sizes now.

The styling lives in `styles.py` with everything else (object names
`cacheDialog*`, kept from when this was the Remove Cache dialog).
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pypts.utilities.data_removal import RemovableItem, RemovalOutcome, remove, total_bytes

#: The survey categories this page offers: `data_removal.survey()` also lists
#: the configuration, which is Restore default settings' business.
STORAGE_KEYS = ("state", "reports", "logs")

#: Ticked when the panel opens. The recents list is pypts' own housekeeping;
#: reports and run logs are test records, so removing them stays a deliberate
#: extra click rather than the default.
DEFAULT_SELECTION = ("state",)

#: Left margin that lines a row's detail text up with its checkbox's label.
_CHECKBOX_INDENT = 22


def count_of(number: int, noun: str) -> str:
    """"1 item" / "71 items". A page nobody wants to read twice says it once."""
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


class StoragePanel(QWidget):
    """Choose, remove, report - in one panel."""

    #: A removal ran, whatever it achieved. The GUI rebuilds what it held in memory.
    removed = Signal()

    def __init__(
        self,
        survey: Callable[[], Sequence[RemovableItem]],
        remover: Callable[[Sequence[RemovableItem]], RemovalOutcome] = remove,
        blocked_reason: str | None = None,
    ) -> None:
        """
        Args:
            survey: what there is to remove, and how big. Called when the panel
                is built and again after Done. Categories outside STORAGE_KEYS
                are left out.
            remover: deletes the chosen items and says what happened.
            blocked_reason: why nothing may be removed right now - a recipe is
                running, and emptying the reports folder under the Report
                thread would take the run down. None: removal is allowed.
        """
        super().__init__()
        self._survey = survey
        self._remover = remover
        self.blocked_reason = blocked_reason

        self._items: list[RemovableItem] = []
        self.outcome: RemovalOutcome | None = None
        #: What was ticked when the operator pressed Remove - the result view
        #: reads this rather than the full survey, so it only reports on what went.
        self.removed_items: list[RemovableItem] = []
        #: One checkbox per category, by key. The panel's whole state.
        self.checkboxes: dict[str, QCheckBox] = {}

        #: "confirm" until something is removed, "result" afterwards.
        self.showing = "confirm"
        self.result_page: QWidget | None = None
        self.back_button: QPushButton | None = None

        # Views are swapped in the layout, not stacked: a QStackedWidget's
        # sizeHint is its tallest page, which would leave the short result view
        # floating in the confirm view's height.
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.confirm_page = self._build_confirm_page()
        self.body.addWidget(self.confirm_page)

    # --- View 1: what will go --------------------------------------------------

    def _build_confirm_page(self) -> QWidget:
        self._items = [item for item in self._survey() if item.key in STORAGE_KEYS]
        self.checkboxes = {}

        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        subtitle = QLabel("Choose what to delete from this machine.")
        subtitle.setObjectName("cacheDialogSubtitle")
        subtitle.setWordWrap(True)
        column.addWidget(subtitle)

        if self.blocked_reason is not None:
            column.addSpacing(8)
            blocked = QLabel(self.blocked_reason)
            blocked.setObjectName("cacheDialogFailure")
            blocked.setWordWrap(True)
            column.addWidget(blocked)
        column.addSpacing(14)

        for index, item in enumerate(self._items):
            if index > 0:
                column.addWidget(self._separator())
            column.addWidget(self._item_row(item))

        column.addSpacing(12)
        column.addWidget(self._total_row())

        column.addSpacing(16)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch()
        # Text and enabled state are settled by _selection_changed().
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.setObjectName("cacheDialogRemoveBtn")
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(self._do_remove)
        buttons.addWidget(self.remove_button)
        column.addLayout(buttons)

        # Only now: every box exists, and so do the widgets the handler touches.
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
        box.setEnabled(item.item_count > 0 and self.blocked_reason is None)
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
        """Keep the total and the Remove button honest as boxes are ticked."""
        selected = self.selected_items()
        self.total_label.setText(format_size(total_bytes(selected)))
        self.remove_button.setEnabled(bool(selected) and self.blocked_reason is None)
        if any(item.item_count for item in self._items):
            self.remove_button.setText("Remove selected")
        else:
            self.remove_button.setText("Nothing to remove")

    # --- View 2: what went -----------------------------------------------------

    def _do_remove(self) -> None:
        if self.blocked_reason is not None:
            return
        self.removed_items = self.selected_items()
        self.outcome = self._remover(self.removed_items)

        # Hidden and taken out of the layout, not deleted: a caller may still
        # hold a reference to a control on it.
        self.body.removeWidget(self.confirm_page)
        self.confirm_page.hide()

        self.result_page = self._build_result_page(self.outcome)
        self.body.addWidget(self.result_page)
        self.showing = "result"
        self.removed.emit()

    def _build_result_page(self, outcome: RemovalOutcome) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        if outcome.failures:
            heading = "Partly removed"
        else:
            heading = "Removed"
        title = QLabel(heading)
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

        column.addSpacing(16)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch()
        self.back_button = QPushButton("Done")
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self._back_to_choosing)
        buttons.addWidget(self.back_button)
        column.addLayout(buttons)
        return page

    def _back_to_choosing(self) -> None:
        """A fresh survey, so the sizes shown are the sizes after the removal."""
        if self.result_page is not None:
            self.body.removeWidget(self.result_page)
            self.result_page.hide()
            self.result_page = None
        self.confirm_page = self._build_confirm_page()
        self.body.addWidget(self.confirm_page)
        self.showing = "confirm"

    # --- Bits ------------------------------------------------------------------

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setObjectName("cacheDialogSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line
