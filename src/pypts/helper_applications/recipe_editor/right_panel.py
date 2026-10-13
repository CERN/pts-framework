"""
The right-hand column: four ways of editing, switched by tabs at its top.

Form (one step, every field), Cards (every step of the sequence, the selected one
open), Grid (one row per step) and Outline (the whole recipe as a tree). Only the
view on show is kept up to date; a view is brought up to date when it is shown.
Under them, "+ Add step after this" - the same step-type menu as the toolbar.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QMenu,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_editor.row_map import StepRef
from pypts.helper_applications.recipe_editor.schema_form import SchemaForm
from pypts.helper_applications.recipe_editor.step_views import CardsView, GridView, OutlineView

#: The views, in tab order.
VIEW_NAMES = ("Form", "Cards", "Grid", "Outline")
FORM, CARDS, GRID, OUTLINE = range(4)


class RightPanel(QWidget):
    """The tabs, the view stack, and the Add step button."""

    step_chosen = Signal(object)
    sequence_chosen = Signal(int)
    view_changed = Signal(int)

    def __init__(self, model: RecipeModel, add_step_menu: QMenu, parent: QWidget | None = None):
        super().__init__(parent)
        self._ref: StepRef | None = None
        self._sequence_index = 0
        self._refs: list[StepRef] = []
        self._issues: list = []

        self.form = SchemaForm(model)
        self.cards = CardsView(model)
        self.grid = GridView(model)
        self.outline = OutlineView(model)
        self._views = (self.form, self.cards, self.grid, self.outline)

        # A plain tab bar, drawn by pypts' stylesheet as its Run | Results tabs are.
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for name in VIEW_NAMES:
            self.tabs.addTab(name)
        self.tabs.setTabToolTip(FORM, "The selected step, every field")
        self.tabs.setTabToolTip(CARDS, "Every step of the sequence; the selected one open")
        self.tabs.setTabToolTip(GRID, "One row per step - quick edits across many")
        self.tabs.setTabToolTip(OUTLINE, "The whole recipe as a tree")

        self.stack = QStackedWidget()
        for view in self._views:
            self.stack.addWidget(view)

        self.add_button = QPushButton("+ Add step after this")
        self.add_button.setToolTip(
            "Add a step after the selected one (at the end when none is selected)"
        )
        self.add_button.setMenu(add_step_menu)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(self.tabs)
        column.addWidget(self.stack, 1)
        column.addWidget(self.add_button)

        self.tabs.currentChanged.connect(self.set_view)
        for view in (self.cards, self.grid, self.outline):
            view.step_chosen.connect(self.step_chosen)
        self.outline.sequence_chosen.connect(self.sequence_chosen)

    # -- what the window calls -----------------------------------------------------

    def set_view(self, index: int) -> None:
        if self.tabs.currentIndex() != index:
            self.tabs.setCurrentIndex(index)
            return
        self.stack.setCurrentIndex(index)
        view = self._views[index]
        view.set_refs(self._refs, self._sequence_index)
        view.show_step(self._ref, self._sequence_index)
        view.refresh()
        view.set_issues(self._issues)
        self.view_changed.emit(index)

    def current_view(self) -> int:
        return self.stack.currentIndex()

    def show_step(self, ref: StepRef | None, sequence_index: int) -> None:
        changed = ref != self._ref or sequence_index != self._sequence_index or ref is None
        self._ref = ref
        self._sequence_index = sequence_index
        if changed or self._view().current_ref() != ref:
            self._view().show_step(ref, sequence_index)

    def current_ref(self) -> StepRef | None:
        return self._ref

    def set_refs(self, refs: list[StepRef], sequence_index: int) -> None:
        self._refs = list(refs)
        self._sequence_index = sequence_index
        self._view().set_refs(self._refs, sequence_index)

    def refresh(self) -> None:
        self._view().refresh()
        if self._view() is self.form:
            # The form may have let go of a deleted step.
            self._ref = self.form.current_ref()

    def set_issues(self, issues: list) -> None:
        self._issues = issues
        self._view().set_issues(issues)

    def set_dark(self, dark: bool) -> None:
        for view in (self.cards, self.grid, self.outline):
            view.set_dark(dark)

    def _view(self):  # noqa: ANN202 - one of the four views
        return self._views[self.stack.currentIndex()]
