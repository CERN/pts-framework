import logging
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from queue import SimpleQueue
from contextlib import suppress
from pypts.pts import run_pts
from pypts import recipe
import os
from pypts.gui import MainWindow, TextEditLoggerHandler # Import necessary GUI classes

logger = logging.getLogger(__name__)


log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)
logging.getLogger("paramiko.transport").setLevel("WARN")


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

    # Set up logger handler from MainWindow
    logging.getLogger().addHandler(window.log_handler)

    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'reliability.yaml')
    api = run_pts(yaml_path, sequence_name="Reliability Loop")
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
