# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont, QBrush
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QTreeView, QVBoxLayout, QWidget

from pypts import recipe
from pypts.gui_components.styles import CERN_BLUE, STATUS_COLORS
from pypts.utils import get_step_result_colors


class SummaryBadge(QLabel):
    def __init__(self, count: int, label: str, bg: str, fg: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._bg = bg
        self._fg = fg
        self.update_count(count, label)

    def update_count(self, count: int, label: str):
        self.setText(f"<b style='font-size:16px'>{count}</b>&nbsp;&nbsp;{label}")
        self.setStyleSheet(
            f"background:{self._bg}; color:{self._fg}; border-radius:6px; padding:6px 16px; font-size:11px; font-weight:600;"
        )


class StepResultModel(QAbstractItemModel):
    def __init__(self, result_data: list[recipe.StepResult]):
        super().__init__()
        self.result_data = result_data

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_items = parent.internalPointer().subresults if parent.isValid() else self.result_data
        child_item = parent_items[row]
        return self.createIndex(row, column, child_item)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        index_item: recipe.StepResult = index.internalPointer()
        parent_uuid = index_item.parent
        if parent_uuid is None:
            return QModelIndex()

        parent_item = recipe.StepResult.get_result_by_uuid(self.result_data, parent_uuid)
        if parent_item is None:
            return QModelIndex()

        siblings = self.result_data
        if parent_item.parent is not None:
            grandparent = recipe.StepResult.get_result_by_uuid(self.result_data, parent_item.parent)
            siblings = grandparent.subresults if grandparent is not None else self.result_data

        for row, step in enumerate(siblings):
            if step.uuid == parent_uuid:
                return self.createIndex(row, 0, parent_item)
        return QModelIndex()

    def rowCount(self, parent):
        if parent.column() > 0:
            return 0
        items = parent.internalPointer().subresults if parent.isValid() else self.result_data
        return len(items)

    def columnCount(self, parent):
        return 3

    def data(self, index, role):
        if not index.isValid():
            return None

        item: recipe.StepResult = index.internalPointer()

        outputs = ""
        if item.outputs:
            output_lines = []
            for name, value in item.outputs.items():
                config = item.step.output_mapping.get(name, {})
                config_str = ", ".join(f"{key}={val}" for key, val in config.items()) if config else "no config"
                output_lines.append(f"{name}={value} ({config_str})")
            outputs = "; ".join(output_lines)

        if index.column() == 1:
            background_color, text_color = get_step_result_colors(item.result, recipe.ResultType)
            if role == Qt.BackgroundRole:
                return QBrush(QColor(background_color))
            if role == Qt.ForegroundRole:
                return QBrush(QColor(text_color))

        columns = [item.step.name, str(item.result), outputs]
        if role == Qt.DisplayRole:
            return columns[index.column()]
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

        self._badge_pass = SummaryBadge(0, "PASS", STATUS_COLORS["PASS"]["bg"], STATUS_COLORS["PASS"]["text"])
        self._badge_fail = SummaryBadge(0, "FAIL", STATUS_COLORS["FAIL"]["bg"], STATUS_COLORS["FAIL"]["text"])
        self._badge_total = SummaryBadge(0, "TOTAL", "#E3ECF9", CERN_BLUE)
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
        self.tree_view.setColumnWidth(0, 220)
        self.tree_view.setColumnWidth(1, 100)
        root.addWidget(self.tree_view, stretch=1)

    def set_dark(self, dark: bool):
        self._dark = dark

    def set_results(self, results: list[recipe.StepResult]):
        flattened = list(_walk_results(results))
        pass_count = sum(1 for result in flattened if result.result == recipe.ResultType.PASS)
        fail_count = sum(1 for result in flattened if result.result == recipe.ResultType.FAIL)
        self._badge_pass.update_count(pass_count, "PASS")
        self._badge_fail.update_count(fail_count, "FAIL")
        self._badge_total.update_count(len(flattened), "TOTAL")

        model = StepResultModel(results)
        self.tree_view.setModel(model)
        self.tree_view.expandAll()
        self.tree_view.resizeColumnToContents(0)
        self.tree_view.resizeColumnToContents(1)


def _walk_results(results: Iterable[recipe.StepResult]):
    for result in results:
        yield result
        yield from _walk_results(result.subresults)
