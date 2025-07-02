import sys
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from PySide6.QtGui import QKeySequence, QUndoStack, QUndoCommand, QShortcut
from PySide6.QtCore import Qt

class EditItemCommand(QUndoCommand):
    def __init__(self, item, old_text, new_text, column=0):
        super().__init__("Edit item")
        self.item = item
        self.old_text = old_text
        self.new_text = new_text
        self.column = column

    def undo(self):
        self.item.setText(self.column, self.old_text)

    def redo(self):
        self.item.setText(self.column, self.new_text)


class UndoableTreeWidget(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.undo_stack = QUndoStack(self)
        self.setColumnCount(1)
        self.setHeaderLabels(["Name"])
        self.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked | QTreeWidget.EditTrigger.EditKeyPressed)

        # Add example item
        item = QTreeWidgetItem(["Item 1"])
        item._old_text = item.text(0)
        self.addTopLevelItem(item)

        # Connect signals
        self.itemChanged.connect(self.on_item_changed)

        # Shortcuts
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self.undo_stack.undo)

        redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_shortcut.activated.connect(self.undo_stack.redo)

        self._editing = False

    def on_item_changed(self, item, column):
        if self._editing:
            return
        self._editing = True

        if not hasattr(item, "_old_text"):
            item._old_text = item.text(column)
            self._editing = False
            return

        old_text = item._old_text
        new_text = item.text(column)

        if old_text != new_text:
            cmd = EditItemCommand(item, old_text, new_text, column)
            self.undo_stack.push(cmd)
            item._old_text = new_text

        self._editing = False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    tree = UndoableTreeWidget()
    tree.show()
    sys.exit(app.exec())