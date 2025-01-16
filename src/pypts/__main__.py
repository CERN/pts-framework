
import logging
import sys
from PyQt5.QtWidgets import QWidget, QListWidget, QGridLayout, QApplication, QLabel, QTableWidget, QTableWidgetItem, QPlainTextEdit, QMessageBox, QHBoxLayout, QVBoxLayout, QTableView, QPushButton, QInputDialog, QLineEdit, QTreeView
from PyQt5.QtCore import QObject, pyqtSignal, QThread, Qt, QAbstractItemModel, QModelIndex
from PyQt5.QtGui import QFont, QPalette, QColor, QPixmap
from threading import Thread
from queue import Queue, SimpleQueue
from typing import List, Dict, Self
from contextlib import suppress
from pypts.pts import *
from pypts.recipe import *
import os
from importlib.resources import files

logger = logging.getLogger(__name__)


log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)
logging.getLogger("paramiko.transport").setLevel("WARN")


class TextEditLoggerHandler(QObject, logging.Handler):
    new_message = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        super(logging.Handler).__init__()
        
    def emit(self, record):
        msg = self.format(record)
        self.new_message.emit(msg)


class MainWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.q_in = None
        self.response_q = None

        self.already_updated = False

        self.setWindowTitle("PTS")
        self.setGeometry(100, 100, 1600, 1000)

        self.cern_logo = QPixmap("images/CERN_Logo.png").scaled(800, 500, Qt.KeepAspectRatio)

        top_level_layout = QHBoxLayout()
        left_half_layout = QVBoxLayout()
        right_half_layout = QVBoxLayout()

        self.recipe_label = QLabel(self)

        self.step_list = QTableWidget(self)
        self.step_list.setMaximumWidth(600)
        self.step_list.setColumnCount(2)
        self.step_list.setHorizontalHeaderLabels(["Step name", "Status"])
        self.step_list.setSelectionBehavior(QTableView.SelectRows)
        self.step_list.setColumnWidth(0, 450)
        self.step_list.horizontalHeader().setStretchLastSection(True)

        self.step_list.update()

        self.result_list = QTreeView(self)
        self.result_list.setMaximumWidth(600)

        left_half_layout.addWidget(self.recipe_label)
        left_half_layout.addWidget(self.step_list)
        left_half_layout.addWidget(self.result_list)

        self.picture_box = QLabel(self)
        self.picture_box.setPixmap(self.cern_logo)
        self.picture_box.setMinimumSize(800, 600)
        self.picture_box.setAlignment(Qt.AlignCenter)

        self.message_box = QLabel(self)

        self.button_list_layout = QHBoxLayout()
        self.yes_button = QPushButton()
        self.yes_button.setText("Yes")
        self.yes_button.setEnabled(False)
        self.no_button = QPushButton()
        self.no_button.setText("No")
        self.no_button.setEnabled(False)
        self.button_list_layout.addWidget(self.yes_button)
        self.button_list_layout.addWidget(self.no_button)
        self.yes_button.pressed.connect(lambda: self.interaction_response("yes"))
        self.no_button.pressed.connect(lambda: self.interaction_response("no"))

        self.log_text_box = QPlainTextEdit(self)
        self.log_text_box.setReadOnly(True)
        self.log_text_box.setFont(QFont("Courier", 10))
        self.log_text_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text_box.setStyleSheet('background-color: whitesmoke')
        
        right_half_layout.addWidget(self.picture_box)
        right_half_layout.addWidget(self.message_box)
        right_half_layout.addLayout(self.button_list_layout)
        right_half_layout.addWidget(self.log_text_box)

        top_level_layout.addLayout(left_half_layout)
        top_level_layout.addLayout(right_half_layout)
        self.setLayout(top_level_layout)

        self.log_handler = TextEditLoggerHandler(self)
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s : %(name)s : %(message)s'))
        self.log_handler.new_message.connect(self.log_text_box.appendPlainText)
        logging.getLogger().addHandler(self.log_handler)

        self.show()


    def update_recipe_name(self, recipe_name, recipe_description):
        self.recipe_label.setText(recipe_name)
        self.setWindowTitle(f"PTS: {recipe_name}")

    def update_sequence(self, sequence):
        if not self.already_updated:
            i = 0
            self.step_list.setRowCount(len(sequence.steps))
            for step in sequence.steps:
                new_item = QTableWidgetItem(step.name)
                new_item.setFlags(new_item.flags() ^ Qt.ItemIsEditable)
                self.step_list.setItem(i, 0, new_item)
                i += 1
            self.already_updated = True

    def update_step_result(self, result: recipe.StepResult):
        #step_line = int(result.step.id)
        result_string = str(result)
        new_result_item = QTableWidgetItem(result_string)
        new_result_item.setFlags(new_result_item.flags() ^ Qt.ItemIsEditable)
        match result.get_result():
            case recipe.ResultType.PASS:
                background_color = "green"
            case recipe.ResultType.FAIL:
                background_color = "red"
            case recipe.ResultType.DONE:
                background_color = "cyan"
            case recipe.ResultType.SKIP:
                background_color = "yellow"
            case recipe.ResultType.ERROR:
                background_color = "red"
        
        new_result_item.setBackground(QColor(background_color))
        # font = new_result_item.font().setBold(True)
        # new_result_item.setFont(font)
        new_result_item.setTextAlignment(Qt.AlignCenter)
        #self.step_list.setItem(step_line, 1, new_result_item)
        self.step_list.update()

    def show_results(self, results: List[recipe.StepResult]):
        myResultModel = StepResultModel(results)
        self.result_list.setModel(myResultModel)
        self.result_list.update()

    def show_message(self, response_q:SimpleQueue, message, image_path, options):
        self.message_box.setText(message)
        if image_path != "":
            image_pixmap = QPixmap(image_path).scaled(800, 600, Qt.KeepAspectRatio)
            self.picture_box.setPixmap(image_pixmap)
        self.yes_button.setEnabled(True)
        self.no_button.setEnabled(True)
        self.response_q = response_q
    
    def interaction_response(self, response):
        self.response_q.put(response)
        self.yes_button.setEnabled(False)
        self.no_button.setEnabled(False)
        self.picture_box.setPixmap(self.cern_logo)
        self.message_box.clear()

    def get_serial_number(self, response_q:SimpleQueue):
        while True:
            text, ok = QInputDialog().getText(self, "Serial Number of DUT", "Serial Number:")
            if ok and text:
                response_q.put(text)
                break       
        

class StepResultModel(QAbstractItemModel):
    def __init__(self, result_data):
        super().__init__()
        self.result_data: List[recipe.StepResult] = result_data

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        
        if parent.isValid():
            parent_item = parent.internalPointer().subresults
        else:
            parent_item = self.result_data

        child_item = parent_item[row]

        return self.createIndex(row, column, child_item)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        index_item: recipe.StepResult = index.internalPointer()
        parent_uuid = index_item.parent

        if parent_uuid is None:
            return QModelIndex()

        parent_item: recipe.StepResult = recipe.StepResult.get_result_by_uuid(self.result_data, parent_uuid)
        
        if parent_item.parent is None:
            list_to_search = self.result_data
        else:
            grandparent_item = recipe.StepResult.get_result_by_uuid(self.result_data, parent_item.parent)
            list_to_search = grandparent_item.subresults

        for i, step in enumerate(list_to_search):
            if step.uuid == parent_uuid:
                return self.createIndex(i, 0, parent_item)
        
        return QModelIndex()
   
    def rowCount(self, parent):
        if parent.column() > 0:
            return 0
        
        if parent.isValid():
            parent_item = parent.internalPointer().subresults
        else:
            parent_item = self.result_data

        return len(parent_item)

    def columnCount(self, parent):
        return 2
    
    def data(self, index, role):
        if not index.isValid():
            return None
        
        index_item: recipe.StepResult = index.internalPointer()
        
        columns = [
            index_item.step.name,
            str(index_item.result)
        ]

        match role:
            case Qt.DisplayRole:
                return columns[index.column()]
            case _:
                return None



class RecipeEventProxy(QObject):
    pre_run_recipe_signal = pyqtSignal(str, str)
    post_run_recipe_signal = pyqtSignal(list)
    pre_run_sequence_signal = pyqtSignal(recipe.Sequence)
    post_run_step_signal = pyqtSignal(recipe.StepResult)
    user_interact_signal = pyqtSignal(SimpleQueue, str, str, list)
    get_serial_number_signal = pyqtSignal(SimpleQueue)

    def __init__(self, event_q):
        super().__init__()
        self.event_q = event_q

    def run(self):
        while True:
            event_name, event_data = self.event_q.get()
            with suppress(AttributeError): # If we can't find the signal, ignore and move on
                # the signals have the same names as the event_names, with an appended '_signal' to them.
                # We construct the signal name and get it dynamically, then emit the signal with event_data as parameters
                signal_name = event_name + "_signal"
                signal = getattr(self, signal_name)
                signal.emit(*event_data)


    
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()

    # event_q, report_q, q_in = recipe.Recipe.run_threaded("reliability.yaml", sequence_name="Reliability Loop")
    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'reliability.yaml')
    api = run_pts(yaml_path, sequence_name="Reliability Loop")
    # event_q, report_q, q_in = recipe.Recipe.run_threaded("indexing.yaml", sequence_name="Main")
    # event_q, report_q, q_in = recipe.Recipe.run_threaded("recipe1.yaml", sequence_name="Main")
    # window.q_in = q_in
    window.q_in = api.input_queue
    recipe_event_processing_thread = QThread()
    recipe_event_proxy = RecipeEventProxy(api.event_queue)
    recipe_event_proxy.moveToThread(recipe_event_processing_thread)
    recipe_event_processing_thread.started.connect(recipe_event_proxy.run)

    # All the signals from the proxy are connected to the GUI from here
    recipe_event_proxy.pre_run_recipe_signal.connect(window.update_recipe_name)
    recipe_event_proxy.post_run_recipe_signal.connect(window.show_results)
    recipe_event_proxy.pre_run_sequence_signal.connect(window.update_sequence)
    recipe_event_proxy.post_run_step_signal.connect(window.update_step_result)
    recipe_event_proxy.user_interact_signal.connect(window.show_message)
    recipe_event_proxy.get_serial_number_signal.connect(window.get_serial_number)

    recipe_event_processing_thread.start()

    exit_code = app.exec()
    
    sys.exit(exit_code)
