# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sequence navigation and structured edit intents for YamVIEW."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pypts.YamVIEW.recipe_step_setup import Sequence_setup, Skip_setup, Step_setup
from pypts.YamVIEW.styles import get_editor_theme_colors

FOLDER_TYPES = {"setup_folder", "main_folder", "teardown_folder"}


class StepBlock(QFrame):
    def __init__(self, step_name: str, step_data: dict[str, Any], parent=None):
        super().__init__(parent)
        self.step_name = step_name
        self.step_data = step_data
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("sequencerCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(step_name)
        label.setObjectName("sequencerStepTitle")
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(label)
        layout.addStretch()
        self.setMinimumHeight(max(34, label.sizeHint().height() + 10))


def _build_header_widget(text: str, indent: int) -> QFrame:
    container = QFrame()
    container.setObjectName("sequencerHeaderContainer")
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(indent + 8, 2, 8, 2)
    label = QLabel(text)
    label.setObjectName("sequencerHeader")
    label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    layout.addWidget(label)
    layout.addStretch()
    container.setMinimumHeight(max(32, label.sizeHint().height() + 12))
    return container


def _item_size_for(widget: QWidget) -> QSize:
    hint = widget.sizeHint()
    return QSize(hint.width(), max(hint.height(), widget.minimumHeight()))


class SequencerWidget(QWidget):
    """Display the recipe structure and emit model-independent edit intents."""

    def __init__(self, yaml_viewer=None, parent=None):
        super().__init__(parent)
        self.yaml_viewer = yaml_viewer
        self.steps: list[dict[str, Any]] = []
        self.yaml_update_callback: Callable[[list[dict[str, Any]]], None] | None = None
        self._dark = False
        self.expanded = False
        self._expanded_ids: set[str] = set()
        self.current_setup_window: Step_setup | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.Yamlbar = QToolBar()
        self.Yamlbar.setObjectName("yamSequencerToolbar")
        self.Yamlbar.setIconSize(QSize(22, 22))
        style = QApplication.style()
        self.action_add_sequence = QAction(
            style.standardIcon(QStyle.SP_FileDialogNewFolder), "Add sequence", self
        )
        self.action_add_step = QAction("➕", self)
        self.action_add_step.setToolTip("Add step to the selected stage")
        self.action_manage_steps = QAction("±", self)
        self.action_manage_steps.setToolTip("Edit skip/error flags")
        self.action_delete = QAction("Delete", self)
        self.action_delete.setToolTip("Delete the selected step or sequence")
        for action in (
            self.action_add_sequence,
            self.action_add_step,
            self.action_manage_steps,
            self.action_delete,
        ):
            self.Yamlbar.addAction(action)
        self.action_add_sequence.triggered.connect(self.on_add_sequence)
        self.action_add_step.triggered.connect(self.on_add_step)
        self.action_manage_steps.triggered.connect(self.on_change_state_step)
        self.action_delete.triggered.connect(self.delete_selected)

        self.list_widget = StepListWidget(self)
        self.list_widget.setObjectName("sequencerList")
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.step_clicked.connect(self.navigate_to_step)
        self.list_widget.step_double_clicked.connect(self.edit_step)
        layout.addWidget(self.Yamlbar)
        layout.addWidget(self.list_widget)
        self.set_dark(False)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        colors = get_editor_theme_colors(dark)
        self.list_widget.setStyleSheet(
            "QListWidget#sequencerList {"
            f"background-color: {colors['surface_alt']};"
            f"border: 1px solid {colors['border']};"
            "border-radius: 8px;padding: 6px;}"
        )

    def set_yaml_data(self, steps_list: list[dict[str, Any]]) -> None:
        self.steps = steps_list
        self.refresh()

    def _node_key(self, node: dict[str, Any]) -> str:
        return str(node.get("_id") or node.get("_sequence_id") or node.get("steptype"))

    def refresh(self) -> None:
        """Render sequence/stage headers and leaf steps from the working structure."""
        selected = self.current_node()
        selected_key = self._node_key(selected) if selected else None
        self.list_widget.clear()

        def add_node(node: dict[str, Any], indent: int = 0) -> None:
            is_folder = node.get("steptype") in FOLDER_TYPES | {"sequence_folder"}
            if is_folder:
                key = self._node_key(node)
                expanded = self.expanded or key in self._expanded_ids
                prefix = "➖" if expanded else "➕"
                item = QListWidgetItem()
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setData(Qt.UserRole, node)
                item.setData(Qt.UserRole + 2, indent)
                widget = _build_header_widget(f"{prefix} {node['step_name']}", indent)
                item.setSizeHint(_item_size_for(widget))
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, widget)
                descendants: list[QListWidgetItem] = []
                for child in node.get("children", []):
                    start = self.list_widget.count()
                    add_node(child, indent + 20)
                    descendants.extend(
                        self.list_widget.item(index)
                        for index in range(start, self.list_widget.count())
                    )
                item.setData(Qt.UserRole + 1, descendants)
                if not expanded:
                    for descendant in descendants:
                        descendant.setHidden(True)
                return

            if node.get("steptype") == "preamble":
                item = QListWidgetItem()
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setData(Qt.UserRole, node)
                widget = _build_header_widget(node["step_name"], indent)
            else:
                item = QListWidgetItem()
                item.setFlags(
                    Qt.ItemIsEnabled
                    | Qt.ItemIsSelectable
                    | Qt.ItemIsDragEnabled
                    | Qt.ItemIsDropEnabled
                )
                item.setData(Qt.UserRole, node)
                block = StepBlock(node.get("step_name", "Unnamed step"), node)
                widget = QFrame()
                row = QHBoxLayout(widget)
                row.setContentsMargins(indent + 4, 2, 4, 2)
                row.addWidget(block)
                widget.setMinimumHeight(block.minimumHeight() + 4)
            item.setSizeHint(_item_size_for(widget))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
            if selected_key == self._node_key(node):
                self.list_widget.setCurrentItem(item)

        for node in self.steps:
            add_node(node)

    def current_node(self) -> dict[str, Any] | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _sequence(self, sequence_id: str) -> dict[str, Any] | None:
        return next(
            (node for node in self.steps if node.get("_sequence_id") == sequence_id),
            None,
        )

    def _folder(self, sequence_id: str, folder_type: str) -> dict[str, Any] | None:
        sequence = self._sequence(sequence_id)
        if sequence is None:
            return None
        return next(
            (child for child in sequence["children"] if child.get("steptype") == folder_type),
            None,
        )

    def _selected_destination(self) -> tuple[str, str] | None:
        node = self.current_node()
        if node and node.get("steptype") in FOLDER_TYPES:
            return node["_sequence_id"], node["steptype"]
        if node and node.get("_parent"):
            return node["_sequence_id"], node["_parent"]
        if node and node.get("steptype") == "sequence_folder":
            return node["_sequence_id"], "main_folder"
        sequence = next(
            (item for item in self.steps if item.get("steptype") == "sequence_folder"),
            None,
        )
        if sequence:
            return sequence["_sequence_id"], "main_folder"
        return None

    def _notify(self) -> bool:
        self.refresh()
        if callable(self.yaml_update_callback):
            return self.yaml_update_callback(self.steps) is not False
        return True

    def on_item_clicked(self, item: QListWidgetItem) -> None:
        node = item.data(Qt.UserRole)
        if node.get("steptype") not in FOLDER_TYPES | {"sequence_folder"}:
            return
        key = self._node_key(node)
        if key in self._expanded_ids:
            self._expanded_ids.remove(key)
        else:
            self._expanded_ids.add(key)
        self.refresh()

    def navigate_to_step(self, step_data: dict[str, Any]) -> None:
        if not self.yaml_viewer or "_node" not in step_data:
            return
        node = step_data["_node"]
        pattern = (
            r"steptype:\s*" + re.escape(node.get("steptype", ""))
            + r"[\s\S]*?step_name:\s*" + re.escape(node.get("step_name", ""))
        )
        match = re.search(pattern, self.yaml_viewer.toPlainText())
        if match:
            cursor = self.yaml_viewer.textCursor()
            cursor.setPosition(match.start())
            self.yaml_viewer.setTextCursor(cursor)
            self.yaml_viewer.setFocus()

    def on_add_sequence(self) -> None:
        dialog = Sequence_setup(parent=self)
        if not dialog.exec():
            return
        data = dialog.result_sequence
        sequence_id = data["sequence_name"]
        suffix = 2
        while self._sequence(sequence_id):
            sequence_id = f"{data['sequence_name']}#{suffix}"
            suffix += 1
        self.steps.append(_sequence_node(data, sequence_id))
        self._expanded_ids.add(sequence_id)
        self._notify()

    def on_add_step(self) -> None:
        destination = self._selected_destination()
        if destination is None:
            QMessageBox.warning(self, "No sequence", "Add a sequence before adding steps.")
            return
        dialog = Step_setup(parent=self)
        dialog._skip_warning = True
        if not dialog.exec():
            return
        sequence_id, parent_type = destination
        folder = self._folder(sequence_id, parent_type)
        if folder is None:
            return
        step = dialog.result_step
        step["_parent"] = parent_type
        step["_sequence_id"] = sequence_id
        folder["children"].append(step)
        self._expanded_ids.update({sequence_id, f"{sequence_id}:{parent_type}"})
        self._notify()

    def edit_step(self, step_data: dict[str, Any]) -> None:
        if "_node" not in step_data or not step_data.get("_parent"):
            return
        if self.current_setup_window:
            self.current_setup_window.close()
            self.current_setup_window.deleteLater()
        dialog = Step_setup(parent=self)
        dialog.AlreadyID = step_data["_id"]
        try:
            dialog.load_definition(step_data["_node"])
        except (KeyError, ValueError) as error:
            QMessageBox.warning(self, "Invalid step", str(error))
            return
        self.current_setup_window = dialog
        dialog.finished.connect(
            lambda result, original=step_data: self._finish_edit(result, original)
        )
        dialog.show()

    def _finish_edit(self, result: int, original: dict[str, Any]) -> None:
        dialog = self.current_setup_window
        if result != QDialog.Accepted or dialog is None:
            return
        replacement = dialog.result_step
        replacement["_parent"] = original["_parent"]
        replacement["_sequence_id"] = original["_sequence_id"]
        folder = self._folder(original["_sequence_id"], original["_parent"])
        if folder is None:
            return
        for index, child in enumerate(folder["children"]):
            if child.get("_id") == original.get("_id"):
                folder["children"][index] = replacement
                self._notify()
                return

    def move_step(
        self,
        step: dict[str, Any],
        sequence_id: str,
        parent_type: str,
        index: int | None = None,
    ) -> bool:
        source = self._folder(step.get("_sequence_id", ""), step.get("_parent", ""))
        destination = self._folder(sequence_id, parent_type)
        if source is None or destination is None or step not in source["children"]:
            return False
        source["children"].remove(step)
        step["_sequence_id"] = sequence_id
        step["_parent"] = parent_type
        if index is None:
            destination["children"].append(step)
        else:
            destination["children"].insert(index, step)
        return self._notify()

    def move_step_to_folder(
        self, step, old_parent, new_parent, old_seq_id, new_seq_id
    ) -> None:
        self.move_step(step, new_seq_id, new_parent)

    def on_steps_reordered(self, *args) -> None:
        """Compatibility entry point; drag/drop commits through :meth:`move_step`."""

    def on_change_state_step(self) -> None:
        if not any(item.get("steptype") == "sequence_folder" for item in self.steps):
            return
        dialog = Skip_setup(self.steps, self)
        if dialog.exec():
            self._notify()

    def delete_selected(self, confirm: bool = True) -> bool:
        node = self.current_node()
        return self.delete_node(node, confirm=confirm)

    def delete_node(self, node: dict[str, Any] | None, confirm: bool = True) -> bool:
        """Delete one identified step or sequence; virtual folders are protected."""
        if node is None:
            return False
        node_type = node.get("steptype")
        if node_type == "preamble" or node_type in FOLDER_TYPES:
            return False
        if confirm:
            label = node.get("step_name", "selected item")
            answer = QMessageBox.question(
                self,
                "Delete item",
                f"Delete '{label}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        if node_type == "sequence_folder":
            self.steps.remove(node)
        else:
            folder = self._folder(node.get("_sequence_id", ""), node.get("_parent", ""))
            if folder is None or node not in folder["children"]:
                return False
            folder["children"].remove(node)
        return self._notify()

    def clear(self) -> None:
        self.steps = []
        self._expanded_ids.clear()
        self.list_widget.clear()


def _sequence_node(data: dict[str, Any], sequence_id: str) -> dict[str, Any]:
    """Create YamVIEW navigation metadata around one plain sequence document."""
    folders = []
    for title, folder_type, field_name in (
        ("Setup Steps", "setup_folder", "setup_steps"),
        ("Main Steps", "main_folder", "steps"),
        ("Teardown Steps", "teardown_folder", "teardown_steps"),
    ):
        children = []
        for index, node in enumerate(data.get(field_name, [])):
            stable_id = node.get("id") or f"{sequence_id}:{folder_type}:{index}"
            children.append(
                {
                    "step_name": node["step_name"],
                    "steptype": node["steptype"],
                    "_node": node,
                    "_parent": folder_type,
                    "_sequence_id": sequence_id,
                    "_id": stable_id,
                }
            )
        folders.append(
            {
                "step_name": title,
                "steptype": folder_type,
                "children": children,
                "_sequence_id": sequence_id,
                "_id": f"{sequence_id}:{folder_type}",
            }
        )
    return {
        "step_name": f"Sequence: {data['sequence_name']}",
        "steptype": "sequence_folder",
        "children": folders,
        "_node": data,
        "_sequence_id": sequence_id,
        "_id": sequence_id,
    }


class StepListWidget(QListWidget):
    step_clicked = Signal(dict)
    step_double_clicked = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragEnabled(True)
        self._mouse_press_pos = QPoint()

    @property
    def sequencer(self) -> SequencerWidget:
        return self.parent()

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        node = item.data(Qt.UserRole) if item else None
        if not node or not node.get("_parent"):
            return
        widget = self.itemWidget(item)
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        if widget:
            pixmap = widget.grab()
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.MoveAction)

    def mousePressEvent(self, event) -> None:
        self._mouse_press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (event.position().toPoint() - self._mouse_press_pos).manhattanLength() < QApplication.startDragDistance():
            item = self.itemAt(event.position().toPoint())
            node = item.data(Qt.UserRole) if item else None
            if node:
                self.step_clicked.emit(node)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        node = item.data(Qt.UserRole) if item else None
        if node:
            self.step_double_clicked.emit(node)
        super().mouseDoubleClickEvent(event)

    def dropEvent(self, event) -> None:
        dragged_item = self.currentItem()
        target_item = self.itemAt(event.position().toPoint())
        dragged = dragged_item.data(Qt.UserRole) if dragged_item else None
        target = target_item.data(Qt.UserRole) if target_item else None
        if not dragged or not dragged.get("_parent") or not target:
            event.ignore()
            return
        if target.get("steptype") in FOLDER_TYPES:
            sequence_id = target["_sequence_id"]
            parent_type = target["steptype"]
            index = None
        elif target.get("_parent"):
            sequence_id = target["_sequence_id"]
            parent_type = target["_parent"]
            folder = self.sequencer._folder(sequence_id, parent_type)
            index = folder["children"].index(target) if folder else None
        else:
            event.ignore()
            return
        if self.sequencer.move_step(dragged, sequence_id, parent_type, index):
            event.acceptProposedAction()
        else:
            event.ignore()
