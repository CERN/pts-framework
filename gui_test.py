import recipe
import logging
import sys
from PyQt5.QtWidgets import QWidget, QListWidget, QGridLayout, QApplication, QLabel, QTableWidget, QTableWidgetItem, QPlainTextEdit, QMessageBox
from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QPalette, QColor
from threading import Thread
from queue import Queue

logger = logging.getLogger(__name__)




log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.INFO, format=log_format)

# class TextEditLogger(logging.Handler):
#     signal = pyqtSignal(str)
#     def __init__(self, widget:QPlainTextEdit):
#         super().__init__()
#         self.widget = widget

#     def emit(self, record):
#         msg = self.format(record)
#         self.signal.emit(msg)
#         #self.widget.appendPlainText(msg)

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

        self.setWindowTitle("PTS")
        self.setGeometry(100, 100, 600, 800)

        layout = QGridLayout(self)
        self.setLayout(layout)

        self.recipe_label = QLabel(self)
        layout.addWidget(self.recipe_label, 0, 0)

        self.step_list = QTableWidget(self)
        self.step_list.setColumnCount(2)
        layout.addWidget(self.step_list, 1, 0)

        self.log_text_box = QPlainTextEdit(self)
        self.log_text_box.setReadOnly(True)
        self.log_text_box.setFont(QFont("Courier", 10))
        self.log_text_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text_box.setStyleSheet('background-color: whitesmoke')

        layout.addWidget(self.log_text_box, 2, 0)
        self.log_handler = TextEditLoggerHandler(self)
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s : %(name)s : %(message)s'))
        self.log_handler.new_message.connect(self.log_text_box.appendPlainText)
        logging.getLogger().addHandler(self.log_handler)

        self.show()

    # def update_log(self, message):
    #     self.logTextBox.appendPlainText(message)

    def update_recipe_name(self, recipe_name, recipe_description):
        print("Updating recipe name in GUI")
        self.recipe_label.setText(recipe_name)

    def update_sequence(self, sequence):
        print("Updating sequence in GUI")
        i = 0
        self.step_list.setRowCount(len(sequence.steps))
        for step in sequence.steps:
            self.step_list.setItem(i, 0, QTableWidgetItem(step.name))
            i += 1

    def update_step_result(self, step, result):
        step_line = int(step.id)
        step_result_string = str(result["result"]).split(".")[1]
        self.step_list.setItem(step_line, 1, QTableWidgetItem(step_result_string))
        self.step_list.update()

    def show_popup(self, message):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Message")
        msg_box.setText(message)
        msg_box.exec()
        self.q_in.put("continue")
        

class RecipeProxyWorker(QObject):
    pre_run_recipe_signal = pyqtSignal(str, str)
    pre_run_sequence_signal = pyqtSignal(recipe.Sequence)
    post_run_step_signal = pyqtSignal(recipe.Step, dict)
    gui_info_signal = pyqtSignal(str)

    def __init__(self, q):
        super().__init__()
        self.q = q

    def run(self):
        while True:
            callback_name, callback_data = self.q.get()
            # print(f"Received callback {callback_name}")
            try:
                signal = getattr(self, callback_name + "_signal")
                signal.emit(*tuple(callback_data.values()))
            except AttributeError:
                pass
            # match callback_name:
            #     case "pre_run_recipe":
            #         self.pre_run_recipe_signal.emit(*tuple(callback_data.values()))
            #     case "pre_run_sequence":
            #         self.pre_run_sequence_signal.emit(*tuple(callback_data.values()))
            #     case "post_run_step":
            #         self.post_run_step_signal.emit(*tuple(callback_data.values()))
                

    
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()

    q_out, q_in = recipe.run_threaded("recipe1.yaml")
    window.q_in = q_in
    recipe_thread = QThread()
    proxy_worker = RecipeProxyWorker(q_out)
    proxy_worker.moveToThread(recipe_thread)
    recipe_thread.started.connect(proxy_worker.run)
    proxy_worker.pre_run_recipe_signal.connect(window.update_recipe_name)
    proxy_worker.pre_run_sequence_signal.connect(window.update_sequence)
    proxy_worker.post_run_step_signal.connect(window.update_step_result)
    proxy_worker.gui_info_signal.connect(window.show_popup)

    recipe_thread.start()

    exit_code = app.exec()
    
    sys.exit(exit_code)
