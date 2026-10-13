"""
PROBLEMS: what the verificator found, under the step table.

Laid out like pypts' LOG OUTPUT - a section label over a framed monospace box -
because it sits where the operator window has its log. A click on a problem
asks the window to go to it (`issue_activated`); its hint is shown under the
list, as the Recipe Creator shows it.

Beside the title a badge says at a glance how the recipe stands: a green OK, a
yellow ! (warnings only) or a red ERROR. No recipe open: no badge.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pypts.helper_applications.recipe_creator.issue import ValidationIssue

#: objectName of the list; editor_stylesheet() frames it as pypts frames its log.
PROBLEMS_LIST_NAME = "problemsList"
#: objectName of the badge; editor_stylesheet() colours it by its `state` property.
PROBLEMS_BADGE_NAME = "problemsBadge"

#: The badge's states, its `state` property.
STATE_NONE = ""
STATE_OK = "ok"
STATE_WARNING = "warning"
STATE_ERROR = "error"

#: What the badge says in each state.
BADGE_TEXT = {STATE_OK: "OK", STATE_WARNING: "!", STATE_ERROR: "ERROR"}
BADGE_TOOLTIP = {
    STATE_OK: "No problems - the recipe loads as it is",
    STATE_WARNING: "Warnings only - the recipe loads, but read them",
    STATE_ERROR: "Errors - the recipe does not load as it is",
}


class ProblemsPanel(QWidget):
    """The verificator's issues, one line each, and the selected one's hint."""

    issue_activated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel("PROBLEMS")
        title.setObjectName("sectionLabel")
        self._badge = QLabel()
        self._badge.setObjectName(PROBLEMS_BADGE_NAME)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state = STATE_NONE
        self._set_state(STATE_NONE)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(title)
        title_row.addWidget(self._badge)
        title_row.addStretch(1)

        self._list = QListWidget()
        self._list.setObjectName(PROBLEMS_LIST_NAME)
        # Wrapped, not cut off with an ellipsis: a problem is read whole.
        self._list.setWordWrap(True)
        self._list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._clicked)

        self._hint = QLabel()
        self._hint.setObjectName("formHelp")
        self._hint.setWordWrap(True)
        self._hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addLayout(title_row)
        column.addWidget(self._list, 1)
        column.addWidget(self._hint)

    def show_issues(self, issues: list[ValidationIssue]) -> None:
        self._list.clear()
        self._hint.clear()
        if not issues:
            self._set_state(STATE_OK)
            self._list.addItem("No problems - the recipe loads as it is.")
            return
        if any(issue.is_error for issue in issues):
            self._set_state(STATE_ERROR)
        else:
            self._set_state(STATE_WARNING)
        for issue in issues:
            # Plain words, as LOG OUTPUT writes its levels (an emoji's taller glyph
            # also made the list cut the wrapped text short).
            if issue.is_error:
                mark = "ERROR  "
            else:
                mark = "WARNING"
            where = ""
            if issue.line:
                where = f" (line {issue.line})"
            item = QListWidgetItem(f"{mark} {issue.field}: {issue.message}{where}")
            item.setData(Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(issue.hint)
            self._list.addItem(item)

    def show_message(self, text: str, state: str = STATE_NONE) -> None:
        """One line that is not a verificator issue: no recipe, text that cannot be read."""
        self._list.clear()
        self._hint.clear()
        self._set_state(state)
        self._list.addItem(text)

    def state(self) -> str:
        """The badge's state: STATE_NONE, STATE_OK, STATE_WARNING or STATE_ERROR."""
        return self._state

    def badge_text(self) -> str:
        return self._badge.text()

    def count(self) -> int:
        return self._list.count()

    def item_text(self, row: int) -> str:
        item = self._list.item(row)
        if item is None:
            return ""
        return item.text()

    def _set_state(self, state: str) -> None:
        self._state = state
        self._badge.setText(BADGE_TEXT.get(state, ""))
        self._badge.setToolTip(BADGE_TOOLTIP.get(state, ""))
        self._badge.setVisible(state != STATE_NONE)
        # The stylesheet picks the colour by the property: polish again to apply it.
        self._badge.setProperty("state", state)
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)

    def _clicked(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(issue, ValidationIssue):
            self._hint.setText(issue.hint)
            self.issue_activated.emit(issue)
