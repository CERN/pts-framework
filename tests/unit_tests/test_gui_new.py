# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest
import logging
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from queue import SimpleQueue
from PySide6.QtWidgets import QApplication, QTableWidgetItem
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtGui import QPixmap
from pypts import gui, recipe
import uuid

# Skip all GUI tests when running in CI
pytestmark = pytest.mark.skipif(
    os.environ.get('CI') is not None or 
    os.environ.get('GITHUB_ACTIONS') is not None or
    os.environ.get('GITLAB_CI') is not None or
    os.environ.get('JENKINS_URL') is not None,
    reason="GUI tests are skipped in CI environments"
)


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication for testing Qt widgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Don't quit here as other tests might still be running


@pytest.fixture
def main_window(qapp):
    """Create a MainWindow instance for testing."""
    window = gui.MainWindow()
    yield window
    window.close()


@pytest.fixture
def sample_sequence():
    """Create a sample sequence for testing."""
    step1 = recipe.Step(step_name="Test Step 1")
    step2 = recipe.Step(step_name="Test Step 2")
    step3 = recipe.Step(step_name="Test Step 3")
    
    # Create a mock sequence object that has the required attributes
    sequence = recipe.Sequence(sequence_data={
        "sequence_name": "Test Sequence",
        "locals": {},
        "parameters": {},
        "outputs": {},
        "setup_steps": [],
        "steps": [],
        "teardown_steps": []
    })
    # Manually set steps since we can't easily create them through the normal YAML process
    sequence.steps = [step1, step2, step3]
    return sequence


@pytest.fixture
def sample_step_results():
    """Create sample step results for testing."""
    step1 = recipe.Step(step_name="Parent Step")
    step2 = recipe.Step(step_name="Child Step 1")
    step3 = recipe.Step(step_name="Child Step 2")
    
    parent_result = recipe.StepResult(step=step1)
    parent_result.result = recipe.ResultType.PASS
    
    child_result1 = recipe.StepResult(step=step2, parent=parent_result.uuid)
    child_result1.result = recipe.ResultType.PASS
    
    child_result2 = recipe.StepResult(step=step3, parent=parent_result.uuid)
    child_result2.result = recipe.ResultType.FAIL
    
    parent_result.subresults = [child_result1, child_result2]
    
    return [parent_result]


class TestMainWindowInitialization:
    """Test MainWindow initialization and basic setup."""
    
    def test_main_window_creation(self, main_window):
        """Test that MainWindow creates without errors and has expected widgets."""
        assert main_window is not None
        assert main_window.windowTitle() == "PTS"
        assert main_window.step_list is not None
        assert main_window.result_list is not None
        assert main_window.picture_box is not None
        assert main_window.message_box is not None
        assert main_window.log_text_box is not None
        assert main_window.yes_button is not None
        assert main_window.no_button is not None
    
    def test_initial_button_state(self, main_window):
        """Test that interaction buttons are initially disabled."""
        assert not main_window.yes_button.isEnabled()
        assert not main_window.no_button.isEnabled()
    
    def test_step_list_setup(self, main_window):
        """Test that step list is properly configured."""
        assert main_window.step_list.columnCount() == 2
        assert main_window.step_list.horizontalHeaderItem(0).text() == "Step name"
        assert main_window.step_list.horizontalHeaderItem(1).text() == "Status"
    
    def test_cern_logo_loaded(self, main_window):
        """Test that CERN logo is loaded or a default pixmap is set."""
        pixmap = main_window.picture_box.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()


class TestLoggingIntegration:
    """Test logging functionality with the GUI."""
    
    def test_log_handler_creation(self, main_window):
        """Test that log handler is created and configured."""
        assert main_window.log_handler is not None
        assert isinstance(main_window.log_handler, gui.TextEditLoggerHandler)
    
    def test_log_message_display(self, main_window, qtbot):
        """Test that log messages are displayed in the log text box."""
        # Clear any existing logs
        main_window.log_text_box.clear()
        
        # Create a test logger and send a message
        test_logger = logging.getLogger("test_logger")
        test_message = "Test log message for GUI"
        
        # In PySide6, we'll test the handler directly instead of waiting for signal
        # Create a log record and emit it directly
        record = logging.LogRecord(
            name="test_logger", level=logging.INFO, pathname="", lineno=0,
            msg=test_message, args=(), exc_info=None
        )
        main_window.log_handler.emit(record)
        
        # Process any pending Qt events to ensure the message is displayed
        qtbot.wait(100)  # Small wait for UI update
        
        # Check that the message appears in the log text box
        log_content = main_window.log_text_box.toPlainText()
        assert test_message in log_content


class TestRecipeNameUpdate:
    """Test recipe name and description updates."""
    
    def test_update_recipe_name_basic(self, main_window):
        """Test basic recipe name update."""
        event_dict = {
            "recipe_name": "Test Recipe",
            "recipe_description": "This is a test recipe"
        }
        
        main_window.update_recipe_name(event_dict)
        
        expected_text = "Running Test Recipe...\nThis is a test recipe"
        assert main_window.recipe_label.text() == expected_text
        assert main_window.windowTitle() == "PTS: Test Recipe"
    
    def test_update_recipe_name_with_special_characters(self, main_window):
        """Test recipe name update with special characters."""
        event_dict = {
            "recipe_name": "Recipe-Test_v2.1",
            "recipe_description": "Description with (special) chars & symbols!"
        }
        
        main_window.update_recipe_name(event_dict)
        
        expected_text = "Running Recipe-Test_v2.1...\nDescription with (special) chars & symbols!"
        assert main_window.recipe_label.text() == expected_text
        assert main_window.windowTitle() == "PTS: Recipe-Test_v2.1"


class TestSequenceUpdate:
    """Test sequence population in the step list."""
    
    def test_update_sequence_basic(self, main_window, sample_sequence):
        """Test basic sequence update populates step list."""
        event_dict = {"sequence": sample_sequence}
        
        main_window.update_sequence(event_dict)
        
        assert main_window.step_list.rowCount() == 3
        
        # Check that step names are populated correctly
        assert main_window.step_list.item(0, 0).text() == "Test Step 1"
        assert main_window.step_list.item(1, 0).text() == "Test Step 2"
        assert main_window.step_list.item(2, 0).text() == "Test Step 3"
        
        # Check that UUIDs are stored in UserRole
        assert main_window.step_list.item(0, 0).data(Qt.ItemDataRole.UserRole) == str(sample_sequence.steps[0].id)
        assert main_window.step_list.item(1, 0).data(Qt.ItemDataRole.UserRole) == str(sample_sequence.steps[1].id)
        assert main_window.step_list.item(2, 0).data(Qt.ItemDataRole.UserRole) == str(sample_sequence.steps[2].id)
        
        # Check initial status
        assert main_window.step_list.item(0, 1).text() == "Pending"
        assert main_window.step_list.item(1, 1).text() == "Pending"
        assert main_window.step_list.item(2, 1).text() == "Pending"
    
    def test_update_sequence_prevents_duplicate_updates(self, main_window, sample_sequence):
        """Test that sequence update only happens once."""
        event_dict = {"sequence": sample_sequence}
        
        # First update
        main_window.update_sequence(event_dict)
        original_row_count = main_window.step_list.rowCount()
        
        # Second update should not change anything
        main_window.update_sequence(event_dict)
        assert main_window.step_list.rowCount() == original_row_count
        assert main_window.already_updated is True


class TestStepResultUpdate:
    """Test step result updates in the step list."""
    
    def setup_step_list_with_steps(self, main_window, step_ids):
        """Helper method to setup step list with given step IDs."""
        main_window.step_list.setRowCount(len(step_ids))
        for i, step_id in enumerate(step_ids):
            name_item = QTableWidgetItem(f"Step {i+1}")
            name_item.setData(Qt.ItemDataRole.UserRole, str(step_id))
            main_window.step_list.setItem(i, 0, name_item)
            
            status_item = QTableWidgetItem("Pending")
            main_window.step_list.setItem(i, 1, status_item)
    
    def test_update_step_result_pass(self, main_window):
        """Test updating step result to PASS."""
        test_uuid = str(uuid.uuid4())
        self.setup_step_list_with_steps(main_window, [test_uuid])
        
        step_status_vm = {
            "step_uuid": test_uuid,
            "status_text": "PASS",
            "status_color": "green"
        }
        
        main_window.update_step_result(step_status_vm)
        
        status_item = main_window.step_list.item(0, 1)
        assert status_item.text() == "PASS"
        assert status_item.background().color().name() == "#008000"  # Green
    
    def test_update_step_result_fail(self, main_window):
        """Test updating step result to FAIL."""
        test_uuid = str(uuid.uuid4())
        self.setup_step_list_with_steps(main_window, [test_uuid])
        
        step_status_vm = {
            "step_uuid": test_uuid,
            "status_text": "FAIL",
            "status_color": "red"
        }
        
        main_window.update_step_result(step_status_vm)
        
        status_item = main_window.step_list.item(0, 1)
        assert status_item.text() == "FAIL"
        assert status_item.background().color().name() == "#ff0000"  # Red
    
    def test_update_step_result_nonexistent_uuid(self, main_window, caplog):
        """Test updating step result with non-existent UUID logs warning."""
        self.setup_step_list_with_steps(main_window, [str(uuid.uuid4())])
        
        step_status_vm = {
            "step_uuid": str(uuid.uuid4()),  # Different UUID
            "status_text": "PASS",
            "status_color": "green"
        }
        
        with caplog.at_level(logging.WARNING):
            main_window.update_step_result(step_status_vm)
        
        assert "Could not find step with UUID" in caplog.text


class TestRunningStepHighlight:
    """Test highlighting of currently running steps."""
    
    def test_update_running_step(self, main_window):
        """Test highlighting currently running step."""
        test_uuid = str(uuid.uuid4())
        main_window.step_list.setRowCount(1)
        
        name_item = QTableWidgetItem("Test Step")
        name_item.setData(Qt.ItemDataRole.UserRole, test_uuid)
        main_window.step_list.setItem(0, 0, name_item)
        
        status_item = QTableWidgetItem("Pending")
        main_window.step_list.setItem(0, 1, status_item)
        
        event_dict = {"step_uuid": test_uuid}
        main_window.update_running_step(event_dict)
        
        # Check that items are bold and status shows "Running..."
        assert main_window.step_list.item(0, 0).font().bold()
        assert main_window.step_list.item(0, 1).font().bold()
        assert main_window.step_list.item(0, 1).text() == "Running..."
    
    def test_update_running_step_nonexistent_uuid(self, main_window, caplog):
        """Test updating running step with non-existent UUID logs warning."""
        main_window.step_list.setRowCount(1)
        
        name_item = QTableWidgetItem("Test Step")
        name_item.setData(Qt.ItemDataRole.UserRole, str(uuid.uuid4()))
        main_window.step_list.setItem(0, 0, name_item)
        
        event_dict = {"step_uuid": str(uuid.uuid4())}  # Different UUID
        
        with caplog.at_level(logging.WARNING):
            main_window.update_running_step(event_dict)
        
        assert "Could not find step with UUID" in caplog.text


class TestMessageDisplay:
    """Test message display functionality."""
    
    def test_show_message_basic(self, main_window):
        """Test basic message display without image."""
        response_q = SimpleQueue()
        event_dict = {
            "response_q": response_q,
            "message": "Test message for user",
            "image_path": ""
        }
        
        main_window.show_message(event_dict)
        
        assert main_window.message_box.text() == "Test message for user"
        assert main_window.yes_button.isEnabled()
        assert main_window.no_button.isEnabled()
        assert main_window.response_q == response_q
    
    def test_show_message_with_valid_image(self, main_window):
        """Test message display with valid image."""
        response_q = SimpleQueue()
        
        # Create a temporary image file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            pixmap = QPixmap(100, 100)
            pixmap.fill(Qt.GlobalColor.blue)
            pixmap.save(tmp_file.name, 'PNG')
            temp_image_path = tmp_file.name
        
        try:
            event_dict = {
                "response_q": response_q,
                "message": "Test message with image",
                "image_path": temp_image_path
            }
            
            main_window.show_message(event_dict)
            
            assert main_window.message_box.text() == "Test message with image"
            # Image should be loaded and displayed
            current_pixmap = main_window.picture_box.pixmap()
            assert current_pixmap is not None
            assert not current_pixmap.isNull()
        finally:
            os.unlink(temp_image_path)
    
    def test_show_message_with_invalid_image(self, main_window, caplog):
        """Test message display with invalid image path."""
        response_q = SimpleQueue()
        event_dict = {
            "response_q": response_q,
            "message": "Test message with invalid image",
            "image_path": "/nonexistent/path/image.png"
        }
        
        with caplog.at_level(logging.WARNING):
            main_window.show_message(event_dict)
        
        assert "Image not found at" in caplog.text
        # Should fall back to CERN logo (check by size since PySide6 pixmap equality is different)
        current_pixmap = main_window.picture_box.pixmap()
        assert current_pixmap.size() == main_window.cern_logo.size()


class TestUserInteraction:
    """Test user interaction responses."""
    
    def test_interaction_response_yes(self, main_window):
        """Test 'Yes' response."""
        response_q = SimpleQueue()
        main_window.response_q = response_q
        main_window.yes_button.setEnabled(True)
        main_window.no_button.setEnabled(True)
        
        main_window.interaction_response("yes")
        
        assert response_q.get() == "yes"
        assert not main_window.yes_button.isEnabled()
        assert not main_window.no_button.isEnabled()
        assert main_window.message_box.text() == ""
        # Check pixmap size since PySide6 pixmap equality works differently
        current_pixmap = main_window.picture_box.pixmap()
        assert current_pixmap.size() == main_window.cern_logo.size()
    
    def test_interaction_response_no(self, main_window):
        """Test 'No' response."""
        response_q = SimpleQueue()
        main_window.response_q = response_q
        main_window.yes_button.setEnabled(True)
        main_window.no_button.setEnabled(True)
        
        main_window.interaction_response("no")
        
        assert response_q.get() == "no"
        assert not main_window.yes_button.isEnabled()
        assert not main_window.no_button.isEnabled()


class TestSerialNumberInput:
    """Test serial number input functionality."""
    
    @patch('pypts.gui.QInputDialog')
    def test_get_serial_number_success(self, mock_input_dialog, main_window):
        """Test successful serial number input."""
        response_q = SimpleQueue()
        event_dict = {"response_q": response_q}
        
        # Mock the dialog to return a successful result
        mock_dialog_instance = Mock()
        mock_dialog_instance.getText.return_value = ("ABC123", True)
        mock_input_dialog.return_value = mock_dialog_instance
        
        main_window.get_serial_number(event_dict)
        
        assert response_q.get() == "ABC123"
    
    @patch('pypts.gui.QInputDialog')
    def test_get_serial_number_cancelled(self, mock_input_dialog, main_window):
        """Test cancelled serial number input."""
        response_q = SimpleQueue()
        event_dict = {"response_q": response_q}
        
        # Mock the dialog to return a cancelled result
        mock_dialog_instance = Mock()
        mock_dialog_instance.getText.return_value = ("", False)
        mock_input_dialog.return_value = mock_dialog_instance
        
        main_window.get_serial_number(event_dict)
        
        assert response_q.get() == "CANCELLED"
    
    @patch('pypts.gui.QInputDialog')
    def test_get_serial_number_empty_input(self, mock_input_dialog, main_window):
        """Test empty serial number input."""
        response_q = SimpleQueue()
        event_dict = {"response_q": response_q}
        
        # Mock the dialog to return empty string but OK pressed
        mock_dialog_instance = Mock()
        mock_dialog_instance.getText.side_effect = [("  ", True), ("ABC123", True)]
        mock_input_dialog.return_value = mock_dialog_instance
        
        main_window.get_serial_number(event_dict)
        
        # Should retry and get the second value
        assert response_q.get() == "ABC123"


class TestResultsDisplay:
    """Test results display in tree view."""
    
    def test_show_results(self, main_window, sample_step_results):
        """Test displaying results in tree view."""
        event_dict = {"results": sample_step_results}
        
        main_window.show_results(event_dict)
        
        model = main_window.result_list.model()
        assert model is not None
        assert isinstance(model, gui.StepResultModel)
        assert model.result_data == sample_step_results


class TestStepResultModel:
    """Test the StepResultModel for tree view."""
    
    def test_model_creation(self, sample_step_results):
        """Test creating StepResultModel."""
        model = gui.StepResultModel(sample_step_results)
        assert model.result_data == sample_step_results
    
    def test_row_count_root(self, sample_step_results):
        """Test row count at root level."""
        model = gui.StepResultModel(sample_step_results)
        root_index = QModelIndex()
        assert model.rowCount(root_index) == 1
    
    def test_column_count(self, sample_step_results):
        """Test column count."""
        model = gui.StepResultModel(sample_step_results)
        assert model.columnCount(QModelIndex()) == 2
    
    def test_data_display(self, sample_step_results):
        """Test data display in model."""
        model = gui.StepResultModel(sample_step_results)
        
        # Test root item data
        root_index = model.index(0, 0, QModelIndex())
        assert model.data(root_index, Qt.ItemDataRole.DisplayRole) == "Parent Step"
        
        result_index = model.index(0, 1, QModelIndex())
        assert model.data(result_index, Qt.ItemDataRole.DisplayRole) == "PASS"
    
    def test_parent_child_relationships(self, sample_step_results):
        """Test parent-child relationships in model."""
        model = gui.StepResultModel(sample_step_results)
        
        # Get root item
        root_index = model.index(0, 0, QModelIndex())
        
        # Check children count
        assert model.rowCount(root_index) == 2
        
        # Get first child
        child1_index = model.index(0, 0, root_index)
        assert model.data(child1_index, Qt.ItemDataRole.DisplayRole) == "Child Step 1"
        
        # Verify parent relationship
        parent_of_child1 = model.parent(child1_index)
        assert parent_of_child1 == root_index


class TestEventHandlers:
    """Test additional event handlers."""
    
    def test_handle_post_load_recipe(self, main_window, caplog):
        """Test post load recipe event handler."""
        event_dict = {
            "recipe_name": "Test Recipe",
            "recipe_version": "1.0"
        }
        
        with caplog.at_level(logging.INFO):
            main_window.handle_post_load_recipe(event_dict)
        
        assert "Recipe 'Test Recipe' (v1.0) loaded." in caplog.text
    
    def test_handle_post_run_sequence(self, main_window, caplog):
        """Test post run sequence event handler."""
        event_dict = {
            "sequence_name": "Test Sequence",
            "sequence_result": "PASS"
        }
        
        with caplog.at_level(logging.INFO):
            main_window.handle_post_run_sequence(event_dict)
        
        assert "Sequence 'Test Sequence' finished with result: PASS." in caplog.text


class TestTextEditLoggerHandler:
    """Test the custom logging handler."""
    
    def test_handler_creation(self, main_window):
        """Test creating TextEditLoggerHandler."""
        handler = gui.TextEditLoggerHandler(main_window)
        assert handler is not None
        assert isinstance(handler, logging.Handler)
    
    def test_emit_signal(self, main_window, qtbot):
        """Test that emit sends proper signal."""
        handler = gui.TextEditLoggerHandler(main_window)
        
        # Create a log record
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test message", args=(), exc_info=None
        )
        
        with qtbot.waitSignal(handler.new_message) as blocker:
            handler.emit(record)
        
        assert "Test message" in blocker.args[0] 