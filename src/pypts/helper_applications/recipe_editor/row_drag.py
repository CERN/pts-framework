"""
Drag a row of the step table onto another to move its step there.

pypts' StepTableContent is reused unchanged: this watches its viewport from the
outside (an event filter) rather than turning on Qt's own row moving, which would
shuffle the table's items itself - the table is rebuilt from the recipe after
every edit, so the move has to happen in the recipe. A drop says which row was
dragged, onto which row, and whether above or below it (`row_dropped`); the
window decides what that means for the recipe.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame, QTableWidget

#: The drag's own data type: only a drag that started in this table is accepted.
ROW_MIME = "application/x-pypts-step-row"


class RowDragger(QObject):
    """Row drag-and-drop on a QTableWidget, reported as `row_dropped(source, target, below)`."""

    row_dropped = Signal(int, int, bool)

    def __init__(self, table: QTableWidget) -> None:
        super().__init__(table)
        self._table = table
        self._press_row = -1
        self._press_at = QPoint()
        viewport = table.viewport()
        viewport.setAcceptDrops(True)
        viewport.installEventFilter(self)
        # Where the step would land: a line between two rows.
        self._marker = QFrame(viewport)
        self._marker.setObjectName("dropMarker")
        self._marker.setFixedHeight(3)
        self._marker.hide()

    def set_marker_colour(self, colour: str) -> None:
        self._marker.setStyleSheet(f"background-color: {colour};")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_row = self._table.rowAt(event.position().toPoint().y())
                self._press_at = event.position().toPoint()
            return False
        if kind == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if self._press_row < 0 or not (event.buttons() & Qt.MouseButton.LeftButton):
                return False
            moved = (event.position().toPoint() - self._press_at).manhattanLength()
            if moved < QApplication.startDragDistance():
                return False
            self._start_drag(self._press_row)
            self._press_row = -1
            return True
        if kind == QEvent.Type.MouseButtonRelease:
            self._press_row = -1
            return False
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if isinstance(event, QDragMoveEvent) and event.mimeData().hasFormat(ROW_MIME):
                event.acceptProposedAction()
                self._show_marker(event.position().toPoint().y())
                return True
            return False
        if kind == QEvent.Type.DragLeave:
            self._marker.hide()
            return False
        if kind == QEvent.Type.Drop and isinstance(event, QDropEvent):
            self._marker.hide()
            if not event.mimeData().hasFormat(ROW_MIME):
                return False
            source = int(bytes(event.mimeData().data(ROW_MIME)).decode())
            target, below = self.drop_target(event.position().toPoint().y())
            event.acceptProposedAction()
            if target >= 0:
                self.row_dropped.emit(source, target, below)
            return True
        return False

    def drop_target(self, y: int) -> tuple[int, bool]:
        """The row a drop at `y` lands on, and whether below it. Under the last row: below it."""
        row = self._table.rowAt(y)
        if row < 0:
            last = self._last_visible_row()
            return last, True
        rect = self._table.visualRect(self._table.model().index(row, 0))
        return row, y > rect.center().y()

    def _last_visible_row(self) -> int:
        for row in range(self._table.rowCount() - 1, -1, -1):
            if not self._table.isRowHidden(row):
                return row
        return -1

    def _show_marker(self, y: int) -> None:
        row, below = self.drop_target(y)
        if row < 0:
            self._marker.hide()
            return
        rect = self._table.visualRect(self._table.model().index(row, 0))
        line_y = rect.bottom() if below else rect.top()
        self._marker.setGeometry(0, max(0, line_y - 1), self._table.viewport().width(), 3)
        self._marker.show()
        self._marker.raise_()

    def _start_drag(self, row: int) -> None:
        mime = QMimeData()
        mime.setData(ROW_MIME, str(row).encode())
        drag = QDrag(self._table.viewport())
        drag.setMimeData(mime)
        rect = self._table.visualRect(self._table.model().index(row, 0))
        full = rect.united(self._table.visualRect(self._table.model().index(row, 1)))
        drag.setPixmap(self._table.viewport().grab(full))
        drag.exec(Qt.DropAction.MoveAction)
        self._marker.hide()
