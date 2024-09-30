import recipe
import logging
import sys
from PyQt5.QtWidgets import QWidget, QListWidget, QGridLayout, QApplication, QLabel, QTableWidget, QTableWidgetItem, QPlainTextEdit, QMessageBox, QHBoxLayout, QVBoxLayout, QTableView, QPushButton
from PyQt5.QtCore import QObject, pyqtSignal, QThread, Qt
from PyQt5.QtGui import QFont, QPalette, QColor, QPixmap
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
        self.setGeometry(100, 100, 1200, 800)

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

        left_half_layout.addWidget(self.recipe_label)
        left_half_layout.addWidget(self.step_list)

        self.picture_box = QLabel(self)
        self.picture_box.setText("Image here")

        self.message_box = QLabel(self)

        self.button_list_layout = QHBoxLayout()
        self.continue_button = QPushButton()
        self.continue_button.setText("Continue")
        self.button_list_layout.addWidget(self.continue_button)
        self.continue_button.pressed.connect(lambda: self.q_in.put("continue"))

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
        i = 0
        self.step_list.setRowCount(len(sequence.steps))
        for step in sequence.steps:
            new_item = QTableWidgetItem(step.name)
            new_item.setFlags(new_item.flags() ^ Qt.ItemIsEditable)
            self.step_list.setItem(i, 0, new_item)
            i += 1

    def update_step_result(self, step, result):
        step_line = int(step.id)
        new_result_item = QTableWidgetItem(str(result["result"]).split(".")[1])
        new_result_item.setFlags(new_result_item.flags() ^ Qt.ItemIsEditable)
        self.step_list.setItem(step_line, 1, new_result_item)
        self.step_list.update()

    def show_message(self, message, image_path, options):
        self.message_box.setText(message)
        if image_path != "":
            image_pixmap = QPixmap(image_path).scaled(800, 500, Qt.KeepAspectRatio)
            self.picture_box.setPixmap(image_pixmap)
        # recreate buttons for return from this interaction
        

class RecipeCallbackProxy(QObject):
    pre_run_recipe_signal = pyqtSignal(str, str)
    pre_run_sequence_signal = pyqtSignal(recipe.Sequence)
    post_run_step_signal = pyqtSignal(recipe.Step, dict)
    user_interact_signal = pyqtSignal(str, str, list)

    def __init__(self, q):
        super().__init__()
        self.q = q

    def run(self):
        while True:
            callback_name, callback_data = self.q.get()
            try:
                # the signals have the same names as the callback_names, with an appended '_signal' to them.
                # We construct the signal name and get it dynamically, then emit the signal with callback_data as parameters
                signal_name = callback_name + "_signal"
                signal = getattr(self, signal_name)
                signal.emit(*callback_data)
            except AttributeError: # raised if the signal doesn't exist. This allows to not implement them all
                pass

                

    
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()

    q_out, q_in = recipe.run_threaded("recipe1.yaml")
    window.q_in = q_in
    recipe_thread = QThread()
    recipe_callback_proxy = RecipeCallbackProxy(q_out)
    recipe_callback_proxy.moveToThread(recipe_thread)
    recipe_thread.started.connect(recipe_callback_proxy.run)

    # All the signals from the proxy are connected to the GUI from here
    recipe_callback_proxy.pre_run_recipe_signal.connect(window.update_recipe_name)
    recipe_callback_proxy.pre_run_sequence_signal.connect(window.update_sequence)
    recipe_callback_proxy.post_run_step_signal.connect(window.update_step_result)
    recipe_callback_proxy.user_interact_signal.connect(window.show_message)

    recipe_thread.start()

    exit_code = app.exec()
    
    sys.exit(exit_code)
