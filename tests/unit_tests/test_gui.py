import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QModelIndex
from queue import SimpleQueue
from pypts import recipe
from pypts import gui
import uuid

@pytest.fixture(scope="module")
def app():
    return QApplication([])

@pytest.fixture
def main_window(app):
    return gui.MainWindow()

def make_step_result(name="Step 1", result=recipe.ResultType.PASS, parent=None):
    step = recipe.Step(name=name)
    return recipe.StepResult(step=step, result=result, parent=parent)

def test_update_recipe_name(main_window):
    event = {"recipe_name": "Test Recipe"}
    main_window.update_recipe_name(event)
    assert main_window.recipe_label.text() == "Test Recipe"
    assert "Test Recipe" in main_window.windowTitle()

def test_update_sequence(main_window):
    dummy_step = recipe.Step(name="Step A")
    dummy_step.id = uuid.uuid4()
    sequence = recipe.Sequence(sequence_data={
        "sequence_name": "Seq",
        "locals": {},
        "parameters": [],
        "outputs": [],
        "steps": [{"name": "Step A", "type": "info"}],
        "setup_steps": [],
        "teardown_steps": [],
    })
    event = {"sequence": sequence}
    main_window.update_sequence(event)
    assert main_window.step_list.rowCount() == 1
    assert main_window.step_list.item(0, 0).text() == "Step A"

def test_update_step_result(main_window):
    test_uuid = str(uuid.uuid4())
    main_window.step_list.setRowCount(1)
    item = main_window.step_list.item(0, 0) or main_window.step_list.setItem(0, 0, gui.QTableWidgetItem("Step A"))
    item = main_window.step_list.item(0, 0)
    item.setData(gui.Qt.ItemDataRole.UserRole, test_uuid)

    event = {
        "step_uuid": test_uuid,
        "status_text": "PASS",
        "status_color": "green"
    }
    main_window.update_step_result(event)
    assert main_window.step_list.item(0, 1).text() == "PASS"

def test_show_results(app):
    results = [
        make_step_result("Step A", result=recipe.ResultType.PASS),
        make_step_result("Step B", result=recipe.ResultType.FAIL),
    ]
    model = gui.StepResultModel(results)
    index_0 = model.index(0, 0, QModelIndex())
    index_1 = model.index(1, 1, QModelIndex())
    assert model.data(index_0, gui.Qt.ItemDataRole.DisplayRole) == "Step A"
    assert model.data(index_1, gui.Qt.ItemDataRole.DisplayRole) == str(recipe.ResultType.FAIL)
