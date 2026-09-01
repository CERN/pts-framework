# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
ResultsPanel: the post-run summary view in the CenterView.

Adapted from old_code/hmi/gui_components/results_panel.py. The key change:
StepResultModel works from StepOutcome (flat, pickle-safe) instead of
recipe.StepResult (live objects that cannot cross the process boundary).
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


class StepResultModel(QAbstractItemModel):
    """Flat model over StepOutcome - no hierarchy, three columns: name/result/error."""

    COLUMNS: ClassVar[list[str]] = ["Step Name", "Result", "Info"]

    def __init__(self, outcomes: tuple[StepOutcome, ...], dark: bool = False):
        super().__init__()
        self._outcomes = outcomes
        #: Which theme's verdict chips data() hands out. Public, because the
        #: panel flips it when the theme changes rather than rebuilding a model.
        self.dark = dark

    def index(self, row, column, parent=None):
        if parent is None:
            parent = QModelIndex()
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        return self.createIndex(row, column, self._outcomes[row])

    def parent(self, index=None):
        return QModelIndex()

    def rowCount(self, parent=None):  # noqa: N802 - Qt virtual
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._outcomes)

    def columnCount(self, parent=None):  # noqa: N802 - Qt virtual
        return 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802 - Qt virtual
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        outcome: StepOutcome = index.internalPointer()

        if index.column() == 1:
            verdicts = get_palette(self.dark).verdicts
            chip = verdicts.get(outcome.result.name, verdicts["PENDING"])
            if role == Qt.BackgroundRole:
                return QBrush(QColor(chip.background))
            if role == Qt.ForegroundRole:
                return QBrush(QColor(chip.text))

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return outcome.step_name
            if index.column() == 1:
                return str(outcome.result)
            if index.column() == 2:
                return outcome.error_info or ""
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
        self.tree_view.setRootIsDecorated(False)
        self.tree_view.setItemsExpandable(False)
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
        self.tree_view.resizeColumnToContents(0)
