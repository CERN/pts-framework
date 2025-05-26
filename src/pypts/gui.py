import logging
from PyQt6.QtWidgets import (QWidget, QListWidget, QGridLayout, QApplication, QLabel, QTableWidget, 
                             QTableWidgetItem, QPlainTextEdit, QMessageBox, QHBoxLayout, 
                             QVBoxLayout, QTableView, QPushButton, QInputDialog, QLineEdit, 
                             QTreeView, QAbstractItemView)
from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QAbstractItemModel, QModelIndex
from PyQt6.QtGui import QFont, QPalette, QColor, QPixmap, QTextOption
from queue import SimpleQueue
from typing import List
from pypts import recipe
import uuid # Import uuid
from utils import get_project_root

class TextEditLoggerHandler(QObject, logging.Handler):
    """A logging handler that emits Qt signals for log messages."""
    new_message = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        super(logging.Handler).__init__()
        
    def emit(self, record):
        msg = self.format(record)
        self.new_message.emit(msg)


class MainWindow(QWidget):
    """The main application window, displaying recipe progress and results."""
    def __init__(self, *args, **kwargs):
        """Initializes the main window UI components."""
        super().__init__(*args, **kwargs)

        self.q_in = None
        self.response_q = None

        self.already_updated = False

        self.setWindowTitle("PTS")
        self.setGeometry(100, 100, 1600, 1000)
        """Get the root path of the project and build string path from it"""
        cern_logo_path = str(get_project_root() / "images" / "CERN_Logo.png")
        self.cern_logo = QPixmap(cern_logo_path).scaled(800, 500, Qt.AspectRatioMode.KeepAspectRatio)

        top_level_layout = QHBoxLayout()
        left_half_layout = QVBoxLayout()
        right_half_layout = QVBoxLayout()

        self.recipe_label = QLabel(self)

        self.step_list = QTableWidget(self)
        self.step_list.setMaximumWidth(600)
        self.step_list.setColumnCount(2)
        self.step_list.setHorizontalHeaderLabels(["Step name", "Status"])
        self.step_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
        self.picture_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

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


    def update_recipe_name(self, event_dict):
        """Updates the recipe name label and window title from the event dictionary."""
        recipe_name = event_dict["recipe_name"]
        # recipe_description = event_dict["recipe_description"] # Currently unused
        self.recipe_label.setText(recipe_name)
        self.setWindowTitle(f"PTS: {recipe_name}")

    def update_sequence(self, event_dict):
        """Populates the step list table when a sequence starts using data from the event dictionary.
        
        Stores the step UUID in the UserRole for later identification.
        """
        sequence: recipe.Sequence = event_dict["sequence"]
        if not self.already_updated:
            self.step_list.setRowCount(len(sequence.steps))
            for i, step in enumerate(sequence.steps):
                # Store step name in the first column
                name_item = QTableWidgetItem(step.name)
                name_item.setFlags(name_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                # Store the step's UUID in the UserRole for later lookup
                name_item.setData(Qt.ItemDataRole.UserRole, str(step.id))
                self.step_list.setItem(i, 0, name_item)
                
                # Optionally add an initial empty/pending status item
                status_item = QTableWidgetItem("Pending")
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                status_item.setFlags(status_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.step_list.setItem(i, 1, status_item)
                
            self.already_updated = True
            self.step_list.update() # Ensure visual update

    def update_step_result(self, step_status_vm: dict):
        """Updates the status of a step in the live step list table.
        
        Receives a ViewModel dictionary with step UUID, status text, and color.
        Finds the corresponding row using the UUID and updates the status cell.
        """
        # Extract data from the ViewModel
        step_uuid_to_find = step_status_vm["step_uuid"]
        result_string = step_status_vm["status_text"]
        background_color = step_status_vm["status_color"]
        
        # Find the row corresponding to the step UUID
        target_row = -1
        for row in range(self.step_list.rowCount()):
            item = self.step_list.item(row, 0) # Get item from the first column (name/uuid)
            if item:
                stored_uuid = item.data(Qt.ItemDataRole.UserRole)
                if stored_uuid == str(step_uuid_to_find):
                    target_row = row
                    break
        
        if target_row != -1:
            # Create the new status item using ViewModel data
            new_result_item = QTableWidgetItem(result_string)
            new_result_item.setFlags(new_result_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            new_result_item.setBackground(QColor(background_color))
            new_result_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Update the status in the found row (second column)
            self.step_list.setItem(target_row, 1, new_result_item)
        else:
            # Handle case where UUID wasn't found (optional logging/error)
            logging.warning(f"Could not find step with UUID {step_uuid_to_find} in the step list to update status.")

        # self.step_list.update() # setItem should trigger update, but call explicitly if needed

    def show_results(self, event_dict):
        """Displays the final, hierarchical results in the tree view using data from the event dictionary.
        
        Uses StepResultModel to populate the QTreeView.
        """
        results: List[recipe.StepResult] = event_dict["results"]
        myResultModel = StepResultModel(results)
        self.result_list.setModel(myResultModel)
        self.result_list.update()

    def show_message(self, event_dict):
        """Displays a user message and interaction options from the event dictionary."""
        response_q: SimpleQueue = event_dict["response_q"]
        message = event_dict["message"]
        image_path = event_dict["image_path"]
        print(image_path)
        # options = event_dict["options"] # Currently unused
        self.message_box.setText(message)
        if image_path != "":
            image_pixmap = QPixmap(image_path).scaled(800, 600, Qt.AspectRatioMode.KeepAspectRatio)
            self.picture_box.setPixmap(image_pixmap)
        self.yes_button.setEnabled(True)
        self.no_button.setEnabled(True)
        self.response_q = response_q
    
    def interaction_response(self, response):
        """Sends the user's response back via the response queue and resets UI."""
        self.response_q.put(response)
        self.yes_button.setEnabled(False)
        self.no_button.setEnabled(False)
        self.picture_box.setPixmap(self.cern_logo)
        self.message_box.clear()

    def get_serial_number(self, event_dict):
        """Prompts the user for a serial number and sends it back via the response queue from the event dictionary."""
        response_q: SimpleQueue = event_dict["response_q"]
        while True:
            # QInputDialog static methods are deprecated in PyQt6
            dialog = QInputDialog(self)
            text, ok = dialog.getText(self, "Serial Number of DUT", "Serial Number:")
            if ok and text:
                response_q.put(text)
                break       
        
    def update_running_step(self, event_dict):
        """Highlights the step that is currently running in the step list table."""
        step_uuid_to_find = event_dict["step_uuid"]
        
        # Reset previous running step highlight (optional, depends on desired behavior)
        # You might need to keep track of the previously highlighted row index
        # Or iterate through all rows and reset font
        
        # Find the row corresponding to the step UUID
        target_row = -1
        for row in range(self.step_list.rowCount()):
            item = self.step_list.item(row, 0) # Get item from the first column (name/uuid)
            if item:
                stored_uuid = item.data(Qt.ItemDataRole.UserRole)
                if stored_uuid == str(step_uuid_to_find):
                    target_row = row
                    break
        
        if target_row != -1:
            # Highlight the name item (column 0)
            name_item = self.step_list.item(target_row, 0)
            if name_item:
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
                
            # Highlight the status item (column 1)
            status_item = self.step_list.item(target_row, 1)
            if status_item:
                 # Set status to 'Running...' and make bold
                 status_item.setText("Running...")
                 font = status_item.font()
                 font.setBold(True)
                 status_item.setFont(font)
                 # Optionally change text color
                 # status_item.setForeground(QColor("blue")) 

            # Ensure the item is visible if the list is scrollable
            self.step_list.scrollToItem(self.step_list.item(target_row, 0), QAbstractItemView.ScrollHint.EnsureVisible)

        else:
            logging.warning(f"Could not find step with UUID {step_uuid_to_find} in the step list to highlight as running.")

    def handle_post_load_recipe(self, event_dict):
        """Handles the event triggered after a recipe is loaded."""
        recipe_name = event_dict["recipe_name"]
        recipe_version = event_dict["recipe_version"]
        logging.info(f"Recipe '{recipe_name}' (v{recipe_version}) loaded.")
        # Potential UI update: self.some_label.setText(f"Loaded: {recipe_name} v{recipe_version}")

    def handle_post_run_sequence(self, event_dict):
        """Handles the event triggered after a sequence finishes."""
        sequence_name = event_dict["sequence_name"]
        sequence_result = event_dict["sequence_result"]
        logging.info(f"Sequence '{sequence_name}' finished with result: {sequence_result}.")
        # Potential UI update: Could mark sequence as done in a separate list/view


class StepResultModel(QAbstractItemModel):
    """A Qt model for displaying hierarchical StepResult data in a QTreeView.

    Note: This model is currently coupled to the `recipe.StepResult` class structure.
    """
    def __init__(self, result_data: List[recipe.StepResult]):
        """Initializes the model with the raw list of StepResult objects."""
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
            case Qt.ItemDataRole.DisplayRole:
                return columns[index.column()]
            case _:
                return None 