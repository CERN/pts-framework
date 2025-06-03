# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QListView, QPushButton
from PyQt5.QtCore import Qt, QAbstractListModel

class TestStepsModel(QAbstractListModel):
    def __init__(self, steps=None):
        super(TestStepsModel, self).__init__()
        self.steps = steps or []

    def data(self, index, role):
        if role == Qt.DisplayRole:
            return self.steps[index.row()]

    def rowCount(self, index):
        return len(self.steps)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Testing Steps GUI")

        self.model = TestStepsModel(["Step 1: Initialize", "Step 2: Run Tests", "Step 3: Collect Results", "Step 4: Cleanup"])

        self.view = QListView()
        self.view.setModel(self.model)

        self.button = QPushButton("Run Selected Step")
        self.button.clicked.connect(self.run_selected_step)

        layout = QVBoxLayout()
        layout.addWidget(self.view)
        layout.addWidget(self.button)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

    def run_selected_step(self):
        selected_indexes = self.view.selectedIndexes()
        if selected_indexes:
            selected_step = self.model.data(selected_indexes[0], Qt.DisplayRole)
            print(f"Running: {selected_step}")

app = QApplication(sys.argv)
window = MainWindow()
window.show()
app.exec_()