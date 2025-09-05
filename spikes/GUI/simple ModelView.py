# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# https://doc.qt.io/qt-6/modelview.html

from PySide6.QtWidgets import QApplication, QTableView
from PySide6.QtCore import QAbstractTableModel, Qt, QTime
import sys
from PySide6.QtGui import QFont, QColor
from PySide6.QtCore import QTimer


class MyModel(QAbstractTableModel):
    def __init__(self, timer_interval: int = 1000):
        super(MyModel, self).__init__()
        self.startTimer(timer_interval)
        pass

    def startTimer(self, timer_interval):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.timerEvent)
        self.timer.start(1000)  # Timer set to 1 second intervals

    def timerEvent(self):
        # Emit dataChanged signal to update the view
        top_left = self.index(0, 1)
        bottom_right = self.index(0, 1)
        self.dataChanged.emit(top_left, bottom_right)

    def rowCount(self, parent=None):
        return 6  # Example row count
    
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
    myModel = MyModel(timer_interval=1000)
    table_view.setModel(myModel)
    table_view.show()
    sys.exit(app.exec())