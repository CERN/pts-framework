# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
ResultsPanel: the post-run summary view in the CenterView.

Adapted from old_code/hmi/gui_components/results_panel.py. The key change:
StepResultModel works from StepOutcome (pickle-safe) instead of
recipe.StepResult (live objects that cannot cross the process boundary).

Each step row opens into an Inputs and an Outputs group, one row per value -
`voltage = 12.1` with its check (`range 11 .. 13`) in the Info column - which
is what the old result tree showed inline (migration finding M-3).
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.palette import get_palette
from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.utilities.common import describe_value


class SummaryBadge(QLabel):
    def __init__(self, count: int, label: str, bg: str, fg: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._bg = bg
        self._fg = fg
        self.update_count(count, label)

    def update_count(self, count: int, label: str):
        self.setText(f"<b style='font-size:16px'>{count}</b>&nbsp;&nbsp;{label}")
        self._apply_colors()

    def set_colors(self, bg: str, fg: str) -> None:
        """Recolour in place - the badges follow the theme like everything else."""
        self._bg = bg
        self._fg = fg
        self._apply_colors()

    def _apply_colors(self) -> None:
        self.setStyleSheet(
            f"background:{self._bg}; color:{self._fg}; border-radius:6px;"
            f" padding:6px 16px; font-size:11px; font-weight:600;"
        )


class ResultNode:
    """
    One row of the results tree: a step, a group (Inputs / Outputs) or a value.

    Only a step row carries an `outcome`, which is what gives it a verdict chip.
    """

    def __init__(
        self, text: str, parent: ResultNode | None = None,
        outcome: StepOutcome | None = None, info: str = "",
    ) -> None:
        self.text = text
        self.parent = parent
        self.outcome = outcome
        self.info = info
        self.children: list[ResultNode] = []
        if parent is not None:
            parent.children.append(self)

    def row(self) -> int:
        if self.parent is None:
            return 0
        return self.parent.children.index(self)


def build_result_tree(outcomes: tuple[StepOutcome, ...]) -> ResultNode:
    """The invisible root; its children are the steps, in execution order."""
    root = ResultNode("")
    for outcome in outcomes:
        step_node = ResultNode(outcome.step_name, root, outcome, outcome.error_info)
        if outcome.inputs:
            group = ResultNode("Inputs", step_node)
            for name, value in outcome.inputs:
                ResultNode(describe_value(name, value), group)
        if outcome.outputs:
            expectations = dict(outcome.expectations)
            group = ResultNode("Outputs", step_node)
            for name, value in outcome.outputs:
                expectation = expectations.get(name, "")
                ResultNode(describe_value(name, value), group, info=expectation)
    return root


class StepResultModel(QAbstractItemModel):
    """
    The results tree over StepOutcome - three columns: name / result / info.

    Step rows are the top level; under each, an Inputs and an Outputs group
    with one row per value. A group with nothing in it is left out.
    """

    COLUMNS: ClassVar[list[str]] = ["Step Name", "Result", "Info"]

    def __init__(self, outcomes: tuple[StepOutcome, ...], dark: bool = False):
        super().__init__()
        self._root = build_result_tree(outcomes)
        #: Which theme's verdict chips data() hands out. Public, because the
        #: panel flips it when the theme changes rather than rebuilding a model.
        self.dark = dark

    def _node(self, index: QModelIndex) -> ResultNode:
        if index.isValid():
            return index.internalPointer()
        return self._root

    def index(self, row, column, parent=None):
        if parent is None:
            parent = QModelIndex()
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        return self.createIndex(row, column, self._node(parent).children[row])

    def parent(self, index=None):
        # Called with no argument, this is QObject.parent(); the model has none.
        if index is None or not index.isValid():
            return QModelIndex()
        parent_node = index.internalPointer().parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent=None):  # noqa: N802 - Qt virtual
        if parent is None:
            parent = QModelIndex()
        if parent.isValid() and parent.column() > 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent=None):  # noqa: N802 - Qt virtual
        return 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802 - Qt virtual
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node: ResultNode = index.internalPointer()
        outcome = node.outcome

        if index.column() == 1 and outcome is not None:
            verdicts = get_palette(self.dark).verdicts
            chip = verdicts.get(outcome.result.name, verdicts["PENDING"])
            if role == Qt.BackgroundRole:
                return QBrush(QColor(chip.background))
            if role == Qt.ForegroundRole:
                return QBrush(QColor(chip.text))

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return node.text
            if index.column() == 1:
                if outcome is None:
                    return ""
                return str(outcome.result)
            if index.column() == 2:
                return node.info
        return None


class ResultsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        summary_row = QWidget()
        summary_layout = QHBoxLayout(summary_row)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)

        self._badge_pass = SummaryBadge(0, "PASS", "", "")
        self._badge_fail = SummaryBadge(0, "FAIL", "", "")
        self._badge_total = SummaryBadge(0, "TOTAL", "", "")
        self._paint_badges()
        summary_layout.addWidget(self._badge_pass)
        summary_layout.addWidget(self._badge_fail)
        summary_layout.addWidget(self._badge_total)
        summary_layout.addStretch()
        root.addWidget(summary_row)

        self.tree_view = QTreeView()
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setRootIsDecorated(True)
        self.tree_view.setItemsExpandable(True)
        header = self.tree_view.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree_view.setColumnWidth(0, 260)
        self.tree_view.setColumnWidth(1, 110)
        root.addWidget(self.tree_view, stretch=1)

        # An empty model from the start: set_dark() has something to flip before
        # the first run, and the view has a header before there are results.
        self._model = StepResultModel((), dark=self._dark)
        self.tree_view.setModel(self._model)

    def set_dark(self, dark: bool):
        self._dark = dark
        self._model.dark = dark
        self._paint_badges()
        self.tree_view.viewport().update()

    def _paint_badges(self) -> None:
        """The three summary badges, in the current theme's chip colours."""
        palette = get_palette(self._dark)
        passed = palette.verdicts["PASS"]
        failed = palette.verdicts["FAIL"]
        self._badge_pass.set_colors(passed.background, passed.text)
        self._badge_fail.set_colors(failed.background, failed.text)
        # TOTAL is not a verdict, so it wears the brand rather than a chip.
        self._badge_total.set_colors(palette.menu_highlight, palette.brand)

    def set_results(self, outcomes: tuple[StepOutcome, ...]):
        pass_count = sum(1 for o in outcomes if o.result == ResultType.PASS)
        fail_count = sum(1 for o in outcomes if o.result == ResultType.FAIL)
        self._badge_pass.update_count(pass_count, "PASS")
        self._badge_fail.update_count(fail_count, "FAIL")
        self._badge_total.update_count(len(outcomes), "TOTAL")

        self._model = StepResultModel(outcomes, dark=self._dark)
        self.tree_view.setModel(self._model)
        # Open, as the old result tree was: the values are why the panel exists.
        self.tree_view.expandAll()
        self.tree_view.resizeColumnToContents(0)
