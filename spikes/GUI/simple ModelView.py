# https://doc.qt.io/qt-6/modelview.html

from PyQt6.QtWidgets import QApplication, QTableView
from PyQt6.QtCore import QAbstractTableModel, Qt, QTime
import sys
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import QTimer


class MyModel(QAbstractTableModel):
    def __init__(self):
        super(MyModel, self).__init__()
        self.rowCount
        self.columnCount
        pass

    def startTimer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.timerEvent)
        self.timer.start(1000)  # Timer set to 1 second intervals

    def timerEvent(self):
        # Emit dataChanged signal to update the view
        top_left = self.index(0, 1)
        bottom_right = self.index(0, 1)
        self.dataChanged.emit(top_left, bottom_right)

    def rowCount(self, parent=None):
        return 4  # Example row count
    
    def columnCount(self, parent=None):
        return 3  # Example column count
    
    def data(self, index, role):
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if index.row() == 0 and index.column() == 1:
                    return QTime.currentTime().toString()
                return f"Row {index.row()}, Column {index.column()}"
            case Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setBold(True)
                return font
            case Qt.ItemDataRole.BackgroundRole:
                if (index.row() == 0 and index.column() == 0):
                    return QColor(Qt.GlobalColor.red)
            case Qt.ItemDataRole.TextAlignmentRole:
                if (index.row() == 1 and index.column() == 2):
                    return Qt.AlignmentFlag.AlignRight
            case Qt.ItemDataRole.CheckStateRole:
                if (index.row() == 1 and index.column() == 3):
                    return Qt.CheckState.Checked
            


if  __name__ == "__main__":
    app = QApplication(sys.argv)
    table_view = QTableView()
    myModel = MyModel()
    table_view.setModel(myModel)
    table_view.show()
    sys.exit(app.exec())