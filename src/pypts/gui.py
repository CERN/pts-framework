import logging
from PyQt6.QtWidgets import (QWidget, QListWidget, QGridLayout, QApplication, QLabel, QTableWidget, 
                             QTableWidgetItem, QPlainTextEdit, QMessageBox, QHBoxLayout, 
                             QVBoxLayout, QTableView, QPushButton, QInputDialog, QLineEdit, 
                             QTreeView, QAbstractItemView, QMainWindow, QMenuBar, QFrame)
from PyQt6.QtCore import QObject, pyqtSignal, QThread, Qt, QAbstractItemModel, QModelIndex
from PyQt6.QtGui import QFont, QPalette, QColor, QPixmap, QTextOption, QAction
from queue import SimpleQueue
from typing import List
from pypts import recipe
import uuid # Import uuid
from .pts import run_pts
from .event_proxy import RecipeEventProxy


class TextEditLoggerHandler(QObject, logging.Handler):
    """A logging handler that emits Qt signals for log messages."""
    new_message = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        super(logging.Handler).__init__()
        
    def emit(self, record):
        msg = self.format(record)
        self.new_message.emit(msg)


class MainWindow(QMainWindow):
    """The main application window, displaying recipe progress and results."""
    def __init__(self, *args, **kwargs):
        """Initializes the main window UI components."""
        super().__init__(*args, **kwargs)

        self.q_in = None
        self.response_q = None

        # Attributes to hold recipe execution state
        self.pts_api = None
        self.recipe_event_proxy = None
        self.recipe_event_processing_thread = None
        self._launched_with_recipe = False # Flag to track launch mode

        self.already_updated = False

        self.setWindowTitle("PTS")
        self.setGeometry(100, 100, 1600, 1000)

        # Create a central widget to hold the main layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        self.cern_logo = QPixmap("images/CERN_Logo.png").scaled(800, 500, Qt.AspectRatioMode.KeepAspectRatio)

        # Main layout for the central widget (now vertical to accommodate the separator)
        main_layout = QVBoxLayout()

        # Add a horizontal separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        # Create the horizontal layout for the two halves (step list/results and picture/log)
        content_layout = QHBoxLayout()
        left_half_layout = QVBoxLayout()
        right_half_layout = QVBoxLayout()

        # Parent widgets to central_widget or self
        self.recipe_label = QLabel(central_widget)

        self.step_list = QTableWidget(central_widget)
        self.step_list.setMaximumWidth(600)
        self.step_list.setColumnCount(2)
        self.step_list.setHorizontalHeaderLabels(["Step name", "Status"])
        self.step_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.step_list.setColumnWidth(0, 450)
        self.step_list.horizontalHeader().setStretchLastSection(True)

        self.step_list.update()

        self.result_list = QTreeView(central_widget)
        self.result_list.setMaximumWidth(600)

        left_half_layout.addWidget(self.recipe_label)
        left_half_layout.addWidget(self.step_list)
        left_half_layout.addWidget(self.result_list)

        self.picture_box = QLabel(central_widget)
        self.picture_box.setPixmap(self.cern_logo)
        self.picture_box.setMinimumSize(800, 600)
        self.picture_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.message_box = QLabel(central_widget)

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

        self.log_text_box = QPlainTextEdit(central_widget)
        self.log_text_box.setReadOnly(True)
        self.log_text_box.setFont(QFont("Courier", 10))
        self.log_text_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text_box.setStyleSheet('background-color: whitesmoke')
        
        right_half_layout.addWidget(self.picture_box)
        right_half_layout.addWidget(self.message_box)
        right_half_layout.addLayout(self.button_list_layout)
        right_half_layout.addWidget(self.log_text_box)

        # Add the left and right halves to the content layout
        content_layout.addLayout(left_half_layout)
        content_layout.addLayout(right_half_layout)

        # Add the content layout below the separator in the main layout
        main_layout.addLayout(content_layout)

        # Set the layout on the central widget
        central_widget.setLayout(main_layout)

        # Create Menu Bar
        self._create_menu_bar()

        self.log_handler = TextEditLoggerHandler(self)
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s : %(name)s : %(message)s'))
        self.log_handler.new_message.connect(self.log_text_box.appendPlainText)
        logging.getLogger().addHandler(self.log_handler)

        self.show()

    def _create_menu_bar(self):
        """Creates the main menu bar with 'File' and 'About' menus."""
        menu_bar = self.menuBar()  # QMainWindow has a built-in menuBar()
        # File Menu
        file_menu = menu_bar.addMenu("&File")
        # About Menu
        about_menu = menu_bar.addMenu("&About")

        # File Menu Actions
        self.open_action = QAction("&Open Recipe...", self)
        self.open_action.triggered.connect(self._open_recipe_file) # Connect to a (new) handler method
        file_menu.addAction(self.open_action)

        file_menu.addSeparator()

        exit_action = QAction("&Exit", self)
        exit_action.triggered.connect(self.close) # Connect to QMainWindow.close
        file_menu.addAction(exit_action)

        # About Menu Actions (Placeholder)
        about_action = QAction("&About PTS", self)
        # about_action.triggered.connect(self._show_about_dialog) # Connect later
        about_menu.addAction(about_action)

    def set_initial_launch_mode(self, launched_with_recipe: bool):
        """Sets a flag indicating if the GUI was launched with a recipe.

        This is used to potentially disable the 'Open Recipe...' menu item.
        """
        self._launched_with_recipe = launched_with_recipe
        # Disable 'Open' if launched with a specific recipe, as requested
        if self.open_action: # Ensure it exists
            self.open_action.setEnabled(not launched_with_recipe)
            if launched_with_recipe:
                self.open_action.setToolTip("Cannot open a new recipe when launched with a specific file.")
            else:
                 self.open_action.setToolTip("Open a YAML recipe file")

    def _open_recipe_file(self):
        """Placeholder for the logic to open a recipe file using QFileDialog.

        This will be implemented later. It should:
        1. Use QFileDialog.getOpenFileName to get a YAML file path.
        2. If a path is selected, call self.load_and_run_recipe(path).
        3. Handle potential errors during file selection or loading.
        """
        # Implementation deferred
        logging.info("'Open Recipe...' action triggered (implementation pending).")
        # Example structure:
        # from PyQt6.QtWidgets import QFileDialog
        # file_name, _ = QFileDialog.getOpenFileName(self, "Open Recipe File", "", "YAML Files (*.yaml *.yml)")
        # if file_name:
        #     try:
        #         self.load_and_run_recipe(file_name)
        #     except Exception as e:
        #         self.show_error_message(f"Failed to load recipe '{file_name}':\n{e}")
        pass

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

    # --- Methods related to Recipe Loading and Execution ---

    def load_and_run_recipe(self, yaml_path: str, sequence_name: str = "Main"):
        """Loads a recipe file, starts execution, and connects signals.

        Args:
            yaml_path: Path to the YAML recipe file.
            sequence_name: The sequence within the recipe to run.

        Raises:
            FileNotFoundError: If yaml_path does not exist.
            Exception: For other errors during run_pts or setup.
        """
        logging.info(f"Loading recipe: {yaml_path}, sequence: {sequence_name}")

        # TODO: Add logic here to gracefully stop/clean up any previous recipe execution
        # self._cleanup_recipe_resources()

        try:
            # Call run_pts from the pts module
            self.pts_api = run_pts(yaml_path, sequence_name=sequence_name)
            self.q_in = self.pts_api.input_queue # Store input queue

            # Setup the event proxy and its thread
            self.recipe_event_processing_thread = QThread()
            self.recipe_event_proxy = RecipeEventProxy(self.pts_api.event_queue)
            self.recipe_event_proxy.moveToThread(self.recipe_event_processing_thread)

            # Connect signals from the proxy to the MainWindow slots
            self.recipe_event_proxy.pre_run_recipe_signal.connect(self.update_recipe_name)
            self.recipe_event_proxy.post_run_recipe_signal.connect(self.show_results)
            self.recipe_event_proxy.pre_run_sequence_signal.connect(self.update_sequence)
            self.recipe_event_proxy.post_run_step_signal.connect(self.update_step_result)
            self.recipe_event_proxy.pre_run_step_signal.connect(self.update_running_step)
            self.recipe_event_proxy.user_interact_signal.connect(self.show_message)
            self.recipe_event_proxy.get_serial_number_signal.connect(self.get_serial_number)
            self.recipe_event_proxy.post_load_recipe_signal.connect(self.handle_post_load_recipe)
            self.recipe_event_proxy.post_run_sequence_signal.connect(self.handle_post_run_sequence)

            # Connect the thread's started signal to the proxy's run method
            self.recipe_event_processing_thread.started.connect(self.recipe_event_proxy.run)

            # Start the event processing thread
            self.recipe_event_processing_thread.start()
            logging.info("Recipe event processing thread started.")

        except FileNotFoundError as fnf_error:
            logging.error(f"Recipe file not found: {yaml_path}")
            raise fnf_error # Re-raise to be caught by launch_gui
        except Exception as e:
            logging.error(f"Error during run_pts or proxy setup for {yaml_path}: {e}", exc_info=True)
            # Clean up partially created resources if possible
            self._cleanup_recipe_resources() # Call cleanup
            raise e # Re-raise to be caught by launch_gui or _open_recipe_file

    def _cleanup_recipe_resources(self):
        """Stops the event processing thread and cleans up related objects."""
        if self.recipe_event_processing_thread and self.recipe_event_processing_thread.isRunning():
            logging.debug("Requesting recipe event processing thread to quit...")
            # Ideally, RecipeEventProxy.run should have a loop condition that can be set to False
            # For now, we request quit and wait briefly.
            self.recipe_event_processing_thread.quit()
            if not self.recipe_event_processing_thread.wait(1000): # Wait 1 second
                logging.warning("Recipe event processing thread did not quit gracefully, terminating...")
                self.recipe_event_processing_thread.terminate()
                self.recipe_event_processing_thread.wait() # Wait after terminate
            logging.debug("Recipe event processing thread stopped.")

        self.recipe_event_proxy = None
        self.recipe_event_processing_thread = None
        self.pts_api = None
        self.q_in = None
        # Consider resetting UI elements like step list, result list etc.
        # self.step_list.clearContents(); self.step_list.setRowCount(0)
        # self.result_list.setModel(None)
        # self.recipe_label.clear()
        logging.info("Cleaned up recipe resources.")

    def show_error_message(self, message: str):
        """Displays a critical error message box to the user."""
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        """Handles the window close event to ensure cleanup."""
        logging.info("Close event triggered. Cleaning up resources...")
        self._cleanup_recipe_resources() # Ensure thread is stopped
        super().closeEvent(event) # Call the default handler


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