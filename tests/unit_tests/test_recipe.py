# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import pypts.recipe
from pypts.recipe import ResultType
from pypts.recipe import Recipe, StepResult, ResultType, Recipe, Step, IndexedStep, PythonModuleStep, SequenceStep, UserInteractionStep, WaitStep
import uuid
from enum import Enum
import pytest
import uuid
import queue
from unittest.mock import MagicMock, patch


#
def test_result_type_values():
    # Test the enum values and their integer representations
    assert ResultType.SKIP.value == 0
    assert ResultType.DONE.value == 1
    assert ResultType.PASS.value == 2
    assert ResultType.FAIL.value == 3
    assert ResultType.ERROR.value == 4

def test_result_type_str():
    # Test the string representation of each enum value
    assert str(ResultType.SKIP) == "SKIP"
    assert str(ResultType.DONE) == "DONE"
    assert str(ResultType.PASS) == "PASS"
    assert str(ResultType.FAIL) == "FAIL"
    assert str(ResultType.ERROR) == "ERROR"

def test_result_type_enum_consistency():
    # Check that the enum is consistent (i.e., that the string representation
    # matches the value as expected)
    for result_type in ResultType:
        assert str(result_type) == result_type.name

def test_result_type_access():
    # Test access by name
    assert ResultType["SKIP"] == ResultType.SKIP
    assert ResultType["DONE"] == ResultType.DONE
    assert ResultType["PASS"] == ResultType.PASS
    assert ResultType["FAIL"] == ResultType.FAIL
    assert ResultType["ERROR"] == ResultType.ERROR

def test_invalid_enum_access():
    # Test invalid access (should raise KeyError)
    with pytest.raises(KeyError):
        ResultType["INVALID"]

def test_recipe_loading():
    '''
    Test that the recipe is loaded correctly by loading a fake recipe and checking the attributes.
    Also tests that the recipe is run with the correct serial number.
    '''
    # Prepare test data
    recipe_data = [
        {"name": "Test Recipe", "description": "For testing", "version": "1.0", "globals": {}},
        {"sequence_name": "Main", "locals": {}, "parameters": {}, "outputs": {},
         "setup_steps": [], "steps": [], "teardown_steps": []}
    ]

    # Create mock dependencies
    mock_file_loader = MagicMock()
    mock_file_loader.return_value = iter(recipe_data)

    # Track sent events
    sent_events = []
    def mock_event_sender(runtime, event_name, *event_data):
        sent_events.append((runtime, event_name, event_data))

    # Create a mock for getting serial numbers
    def mock_get_serial_number(runtime):
        return "TEST123"

    # Create the recipe with injected dependencies
    recipe = Recipe(
        recipe_file_path="fake_path.yaml",
        file_loader=mock_file_loader,
        event_sender=mock_event_sender
    )

    # Verify the recipe was loaded correctly
    assert recipe.name == "Test Recipe"
    assert recipe.description == "For testing"
    assert "Main" in recipe.sequences

    # Create a mock runtime for running the recipe
    mock_runtime = MagicMock()

    # Run the recipe with the injected serial number function
    recipe.run(
        runtime=mock_runtime,
        get_serial_number_func=mock_get_serial_number
    )

    # Verify the expected events were sent
    assert len(sent_events) > 0
    assert sent_events[0][1] == "pre_run_recipe"
    assert sent_events[0][2] == ("Test Recipe", "For testing")

    # Verify runtime was called correctly
    mock_runtime.set_global.assert_any_call("serial_number", "TEST123")


# Test initialization
def test_step_result_initialization():
    step_result = StepResult()
    assert isinstance(step_result.uuid, uuid.UUID)
    assert step_result.result is None  # result is None on initialization
    assert step_result.inputs == {}
    assert step_result.outputs == {}
    assert step_result.error_info == ""
    assert isinstance(step_result.subresults, list)
    assert step_result.parent is None
    assert step_result.recipe_name is None
    assert step_result.recipe_file_name is None
    assert step_result.serial_number is None
    assert step_result.sequence_name is None
    assert step_result.pypts_version == "unknown"


# Test setting error
def test_set_error():
    step_result = StepResult()
    step_result.set_error(error_info="An error occurred", inputs={"key": "value"})

    assert step_result.result == ResultType.ERROR
    assert step_result.error_info == "An error occurred"
    assert step_result.inputs == {"key": "value"}


# Test setting skip result
def test_set_skip():
    step_result = StepResult()
    step_result.set_skip()

    assert step_result.result == ResultType.SKIP


# Test setting a custom result
def test_set_result():
    step_result = StepResult()
    step_result.set_result(result_type=ResultType.PASS, inputs={"input1": "value"}, outputs={"output1": "value"})

    assert step_result.result == ResultType.PASS
    assert step_result.inputs == {"input1": "value"}
    assert step_result.outputs == {"output1": "value"}


def test_append_subresult():
    step_result = StepResult()
    subresult = StepResult()  # No need to pass result here
    subresult.set_result(ResultType.FAIL)  # Set result for the subresult

    step_result.append_subresult(subresult)

    assert len(step_result.subresults) == 1
    assert step_result.subresults[0].result == ResultType.FAIL


def test_get_result_by_uuid():
    step_result_1 = StepResult()
    step_result_1.set_result(ResultType.PASS)  # Set result after initialization

    step_result_2 = StepResult()
    step_result_2.set_result(ResultType.FAIL)

    step_results = [step_result_1, step_result_2]
    result = StepResult.get_result_by_uuid(step_results, step_result_2.uuid)

    assert result.result == ResultType.FAIL


# Test evaluating multiple step results
def test_evaluate_multiple_step_results():
    step_result_1 = StepResult()
    step_result_1.set_result(ResultType.PASS)

    step_result_2 = StepResult()
    step_result_2.set_result(ResultType.FAIL)

    step_results = [step_result_1, step_result_2]
    highest_result = StepResult.evaluate_multiple_step_results(step_results)

    assert highest_result == ResultType.FAIL  # FAIL > PASS


# Test `is_type` method
def test_is_type():
    step_result = StepResult()
    step_result.set_result(ResultType.PASS)

    assert step_result.is_type(ResultType.PASS)  # Should return True for PASS
    assert not step_result.is_type(ResultType.FAIL)  # Should return False for FAIL


# Test printing result (just checking for no exceptions)
def test_print_result():
    step_result = StepResult()
    step_result.set_result(ResultType.PASS)

    # You may want to redirect stdout to capture printed output for testing
    # For simplicity, let's just assert the result is being set properly
    assert step_result.result == ResultType.PASS


# Test printing result with subresults
def test_print_result_with_subresults():
    step_result = StepResult()
    step_result.set_result(ResultType.PASS)

    subresult = StepResult()
    subresult.set_result(ResultType.FAIL)

    step_result.append_subresult(subresult)

    # You may want to capture the printed output or just check the subresults list
    assert len(step_result.subresults) == 1
    assert step_result.subresults[0].result == ResultType.FAIL


# Assume the serialize function is in the same file or imported
# from your_module import serialize

# 1. Test serialization of Enum
class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3


def test_serialize_enum():
    assert pypts.recipe.serialize(Color.RED) == "RED"
    assert pypts.recipe.serialize(Color.GREEN) == "GREEN"
    assert pypts.recipe.serialize(Color.BLUE) == "BLUE"



# 3. Test serialization of an object without attributes (e.g., integers, floats, strings)
def test_serialize_basic_types():
    assert pypts.recipe.serialize(123) == "123"
    assert pypts.recipe.serialize(45.67) == "45.67"
    assert pypts.recipe.serialize("hello") == "hello"


# 6. Test serialization of None (edge case)
def test_serialize_none():
    assert pypts.recipe.serialize(None) == "None"


@pytest.fixture
def runtime():
    """Fixture to create a Runtime instance with mocked queues."""
    event_queue = queue.Queue()
    report_queue = queue.Queue()
    return pypts.recipe.Runtime(event_queue, report_queue)


def test_runtime_initialization(runtime):
    """Test if the Runtime class is initialized correctly."""
    assert isinstance(runtime, pypts.recipe.Runtime)
    assert runtime.event_queue.empty()
    assert runtime.report_queue.empty()
    assert runtime.results == []
    assert runtime.globals == []
    assert runtime.sequences == {}
    assert runtime.local_stack == []
    assert runtime.recipe_name is None
    assert runtime.recipe_file_name is None
    assert runtime.serial_number is None
    assert runtime.current_sequence_name is None
    assert runtime.pypts_version == "unknown"


def test_push_locals(runtime):
    """Test pushing locals onto the stack."""
    locals_data = {'a': 1, 'b': 2}
    runtime.push_locals(locals_data)

    assert len(runtime.local_stack) == 1
    assert runtime.local_stack[-1] == locals_data


def test_pop_locals(runtime):
    """Test popping locals from the stack."""
    locals_data = {'a': 1, 'b': 2}
    runtime.push_locals(locals_data)

    popped = runtime.pop_locals()

    assert popped == locals_data
    assert len(runtime.local_stack) == 0


def test_get_local(runtime):
    """Test getting a local variable from the stack."""
    locals_data = {'a': 1, 'b': 2}
    runtime.push_locals(locals_data)

    assert runtime.get_local('a') == 1
    assert runtime.get_local('b') == 2


def test_set_local(runtime):
    """Test setting a local variable."""
    locals_data = {'a': 1, 'b': 2}
    runtime.push_locals(locals_data)

    runtime.set_local('a', 10)
    assert runtime.get_local('a') == 10
    assert runtime.get_local('b') == 2


def test_set_globals(runtime):
    """Test setting multiple global variables at once."""
    globals_data = {'global1': 'value1', 'global2': 'value2'}
    runtime.set_globals(globals_data)
    assert runtime.get_globals() == globals_data


def test_append_result(runtime):
    """Test appending a result to an existing result."""
    parent_result = StepResult()

    # Append the parent result to the runtime and get its UUID
    runtime.append_result(None, parent_result)
    parent_step_id = parent_result.uuid  # Use the parent result's UUID

    # Create a subresult and append it to the parent result
    subresult = StepResult()
    subresult.set_result(ResultType.DONE)

    # Append the subresult to the parent result using the parent's UUID
    runtime.append_result(parent_step_id, subresult)

    # Check if the subresult was added correctly
    assert len(parent_result.subresults) == 1


def test_append_subresult(runtime):
    """Test appending a subresult to an existing result."""
    # Create a parent result and add it to the runtime results
    parent_step_id = uuid.uuid4()  # This is the ID we'll use to find the parent result
    parent_result = StepResult()

    # Set the parent_step_id to the parent result's UUID (important for finding it later)
    parent_result.uuid = parent_step_id

    # Append the parent result to the runtime
    runtime.append_result(None, parent_result)  # Append the parent result without a parent ID

    # Ensure that the parent result is in the runtime's results
    assert len(runtime.get_results()) == 1

    # Create the subresult and set its result type
    subresult = StepResult()
    subresult.set_result(ResultType.DONE)

    # Append the subresult to the parent result
    runtime.append_result(parent_step_id, subresult)  # This should append to the parent

    # Check if the subresult was added correctly to the parent result
    assert len(parent_result.subresults) == 1
    assert parent_result.subresults[0] == subresult


def test_send_event(runtime):
    """Test sending an event through the Runtime."""
    event_name = 'event_test'
    event_data = ('data1', 2)

    # Mocking the actual event queue
    mock_event_queue = MagicMock()
    runtime.event_queue = mock_event_queue

    runtime.send_event(event_name, *event_data)

    # Assert the correct event is placed into the queue
    mock_event_queue.put.assert_called_once_with((event_name, event_data))


@pytest.fixture
def recipe():
    from pathlib import Path
    # Assuming the file is in the 'tests' directory
    recipe_file_path = Path(__file__).parent / "test_recipe.yaml"

    # Initialize the Recipe object with the real file path
    return Recipe(recipe_file_path)


@pytest.fixture
def runtime():
    event_queue = queue.SimpleQueue()
    report_queue = queue.SimpleQueue()
    return pypts.recipe.Runtime(event_queue, report_queue)


def test_recipe_metadata_loaded_correctly(recipe):
    assert recipe.name == "Example Test Recipe"
    assert recipe.version == "0.1.0"
    assert recipe.description.startswith("A sample recipe")


def test_main_sequence_exists_and_has_steps(recipe):
    assert "Main" in recipe.sequences
    main_sequence = recipe.sequences["Main"]
    assert hasattr(main_sequence, "steps")
    assert isinstance(main_sequence.steps, list)
    assert len(main_sequence.steps) == 5  # Should match YAML

def test_range_check_pass_fail(recipe, runtime):
    runtime.set_globals(recipe.globals)
    runtime.set_sequences(recipe.sequences)

    inside_step = recipe.sequences["Main"].steps[3]
    outside_step = recipe.sequences["Main"].steps[4]

    inside_result = inside_step.run(runtime, {})
    outside_result = outside_step.run(runtime, {})

    # compare is probably just a boolean
    assert inside_result.outputs["compare"] is True
    assert outside_result.outputs["compare"] is False


def test_sequence_init_missing_data_raises():
    with pytest.raises(FileNotFoundError):
        pypts.recipe.Sequence()

def test_sequence_init_from_data():
    mock_step = MagicMock()
    mock_step.name = "MockStep"

    sequence_data = {
        "sequence_name": "TestSeq",
        "locals": {"var1": None},
        "parameters": [],
        "outputs": [],
        "setup_steps": [],
        "steps": [{"steptype": "DummyStep"}],
        "teardown_steps": []
    }

    with patch("pypts.recipe.Step.build_step", return_value=mock_step):
        sequence = pypts.recipe.Sequence(sequence_data=sequence_data)

    assert sequence.name == "TestSeq"
    assert sequence.locals == {"var1": None}
    assert sequence.parameters == []
    assert sequence.outputs == []
    assert len(sequence.steps) == 1
    assert sequence.steps[0].name == "MockStep"


@patch("pypts.recipe.Step.run_steps")
@patch("pypts.recipe.StepResult.evaluate_multiple_step_results")
def test_sequence_run_executes_steps(mock_evaluate, mock_run_steps):
    # Arrange
    mock_runtime = MagicMock()
    mock_runtime.send_event = MagicMock()
    mock_runtime.set_local = MagicMock()
    mock_runtime.push_locals = MagicMock()
    mock_runtime.pop_locals = MagicMock()

    mock_step_result = MagicMock()
    mock_evaluate.return_value = "final_result"
    mock_run_steps.side_effect = lambda runtime, steps, parent: [mock_step_result] * len(steps)

    sequence_data = {
        "sequence_name": "TestRun",
        "locals": {},
        "parameters": [],
        "outputs": [],
        "setup_steps": [],
        "steps": [{"steptype": "DummyStep"}],
        "teardown_steps": [{"steptype": "TeardownStep"}]
    }

    with patch("pypts.recipe.Step.build_step", return_value=MagicMock()):
        seq = pypts.recipe.Sequence(sequence_data=sequence_data)
        result = seq.run(mock_runtime, input={"test_param": 123})

    # Assert
    assert result == "final_result"
    assert mock_runtime.set_local.called
    assert mock_runtime.push_locals.called
    assert mock_runtime.pop_locals.called
    assert mock_runtime.send_event.call_count == 2  # pre_run_sequence and post_run_sequence


def test_step_initialization():
    step = Step(step_name="MyStep", input_mapping={"a": {"type": "direct", "value": 1}})
    assert step.name == "MyStep"
    assert isinstance(step.id, uuid.UUID)


def test_check_indexing_false():
    step = Step("TestStep", input_mapping={"a": {"type": "direct", "value": 5}})
    assert step.check_indexing() is False

def test_check_indexing_true():
    step = Step("TestStep", input_mapping={"a": {"type": "direct", "value": 5, "indexed": True}})
    assert step.check_indexing() is True


