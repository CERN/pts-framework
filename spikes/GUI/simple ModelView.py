# https://doc.qt.io/qt-6/modelview.html

from PyQt6.QtWidgets import QApplication, QTableView
from PyQt6.QtCore import QAbstractTableModel, Qt
import sys


class MyModel(QAbstractTableModel):
    def __init__(self):
        super(MyModel, self).__init__()
        self.rowCount
        self.columnCount
        pass

    def rowCount(self, parent=None):
        return 4  # Example row count
    
    def columnCount(self, parent=None):
        return 3  # Example column count
    
    def data(self, index, role):
        if role == Qt.ItemDataRole.DisplayRole:
            return f"Row {index.row()}, Column {index.column()}"
        return None


if  __name__ == "__main__":
    app = QApplication(sys.argv)
    table_view = QTableView()
    myModel = MyModel()
    table_view.setModel(myModel)
    table_view.show()
    sys.exit(app.exec())