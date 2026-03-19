# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for pypts.recipe — covers ResultType enum, Recipe loading,
Sequence construction/execution, Step, StepResult, Runtime, and serialize()."""

import pytest
import uuid
import queue
from enum import Enum
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

import pypts.recipe
from pypts.recipe import (
    Recipe,
    Runtime,
    Sequence,
    Step,
    IndexedStep,
    PythonModuleStep,
    SequenceStep,
    UserInteractionStep,
    WaitStep,
    SerialNumberStep,
    StepResult,
    ResultType,
    serialize,
)


# ============================================================
# Helpers
# ============================================================

def _make_recipe_data(overrides=None, sequences=None):
    """Build minimal valid recipe data for the file_loader."""
    main = {
        "name": "Test",
        "description": "desc",
        "version": "1.0",
        "main_sequence": "Main",
        "globals": {},
    }
    if overrides:
        main.update(overrides)

    seq = sequences or [{
        "sequence_name": "Main",
        "locals": {},
        "parameters": {},
        "outputs": {},
        "setup_steps": [],
        "steps": [],
        "teardown_steps": [],
    }]
    return [main] + seq


def _loader_for(data):
    """Create a mock file_loader that yields the given data."""
    loader = MagicMock()
    loader.return_value = iter(data)
    return loader


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def runtime():
    """Create a Runtime instance with clean class-level state."""
    Runtime.stop_event.clear()
    Runtime.recipe_thread = None
    Runtime.recipe_event_proxy = None
    eq = queue.SimpleQueue()
    rq = queue.SimpleQueue()
    yield Runtime(eq, rq)
    Runtime.stop_event.clear()
    Runtime.recipe_thread = None
    Runtime.recipe_event_proxy = None


@pytest.fixture
def recipe_from_yaml():
    """Load the real test_recipe.yaml file into a Recipe object."""
    recipe_file_path = Path(__file__).parent / "test_recipe.yaml"
    return Recipe(recipe_file_path)


# ============================================================
# ResultType enum
# ============================================================

class TestResultType:
    def test_enum_values(self):
        """Verify the integer values assigned to each ResultType member."""
        assert ResultType.SKIP.value == 0
        assert ResultType.DONE.value == 1
        assert ResultType.PASS.value == 2
        assert ResultType.FAIL.value == 3
        assert ResultType.ERROR.value == 4

    def test_str_representation(self):
        """Verify that str(ResultType.X) returns the member name."""
        assert str(ResultType.SKIP) == "SKIP"
        assert str(ResultType.DONE) == "DONE"
        assert str(ResultType.PASS) == "PASS"
        assert str(ResultType.FAIL) == "FAIL"
        assert str(ResultType.ERROR) == "ERROR"

    def test_enum_consistency(self):
        """Verify that str() matches .name for every member."""
        for result_type in ResultType:
            assert str(result_type) == result_type.name

    def test_access_by_name(self):
        """Verify bracket access by string name (ResultType['PASS'])."""
        assert ResultType["SKIP"] == ResultType.SKIP
        assert ResultType["DONE"] == ResultType.DONE
        assert ResultType["PASS"] == ResultType.PASS
        assert ResultType["FAIL"] == ResultType.FAIL
        assert ResultType["ERROR"] == ResultType.ERROR

    def test_invalid_name_raises_key_error(self):
        """Verify that accessing a non-existent member by name raises KeyError."""
        with pytest.raises(KeyError):
            ResultType["INVALID"]

    def test_severity_ordering(self):
        """Verify severity ordering: SKIP < DONE < PASS < FAIL < ERROR < STOP."""
        assert ResultType.SKIP < ResultType.DONE < ResultType.PASS < ResultType.FAIL < ResultType.ERROR < ResultType.STOP

    def test_all_members_have_str(self):
        """Verify that every ResultType member has a valid string representation."""
        for member in ResultType:
            assert str(member) == member.name


# ============================================================
# Recipe loading (mock file_loader)
# ============================================================

class TestRecipeLoading:
    def test_loads_valid_recipe(self):
        """Verify basic recipe loading sets name, version, and sequences."""
        data = _make_recipe_data()
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert r.name == "Test"
        assert r.version == "1.0"
        assert "Main" in r.sequences

    def test_loading_with_event_sender(self):
        """Verify that running a loaded recipe emits pre_run_recipe via the event sender."""
        recipe_data = [
            {"name": "Test Recipe", "description": "For testing", "version": "1.0",
             "main_sequence": "Main", "globals": {}},
            {"sequence_name": "Main", "locals": {}, "parameters": {}, "outputs": {},
             "setup_steps": [], "steps": [], "teardown_steps": []}
        ]

        mock_file_loader = MagicMock()
        mock_file_loader.return_value = iter(recipe_data)

        sent_events = []
        def mock_event_sender(runtime, event_name, *event_data):
            sent_events.append((runtime, event_name, event_data))

        r = Recipe(
            recipe_file_path="fake_path.yaml",
            file_loader=mock_file_loader,
            event_sender=mock_event_sender
        )

        assert r.name == "Test Recipe"
        assert r.description == "For testing"
        assert "Main" in r.sequences

        mock_runtime = MagicMock()
        r.run(runtime=mock_runtime)

        assert len(sent_events) > 0
        assert sent_events[0][1] == "pre_run_recipe"
        assert sent_events[0][2] == ("Test Recipe", "For testing")

    def test_missing_required_field_raises(self):
        """Verify that omitting a required field (name/description/version/globals) raises."""
        for field in ["name", "description", "version", "globals"]:
            data = _make_recipe_data()
            del data[0][field]
            with pytest.raises(Exception):
                Recipe("fake.yaml", file_loader=_loader_for(data))

    def test_report_overwrite_mode(self):
        """Verify that report='overwrite' sets report_overwrite to True."""
        data = _make_recipe_data(overrides={"report": "overwrite"})
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert r.report_overwrite is True

    def test_report_append_mode(self):
        """Verify that report='append' sets report_overwrite to False."""
        data = _make_recipe_data(overrides={"report": "append"})
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert r.report_overwrite is False

    def test_invalid_report_mode_raises(self):
        """Verify that an unsupported report mode raises an exception."""
        data = _make_recipe_data(overrides={"report": "invalid_mode"})
        with pytest.raises(Exception):
            Recipe("fake.yaml", file_loader=_loader_for(data))

    def test_test_package_with_dot_raises(self):
        """Verify that a test_package containing a dot raises an exception."""
        data = _make_recipe_data(overrides={"test_package": "my.package"})
        with pytest.raises(Exception):
            Recipe("fake.yaml", file_loader=_loader_for(data))

    def test_test_package_none_ok(self):
        """Verify that omitting test_package results in None."""
        data = _make_recipe_data()
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert r.test_package is None

    def test_multiple_sequences(self):
        """Verify that multiple sequences are loaded correctly."""
        seqs = [
            {"sequence_name": "Main", "locals": {}, "parameters": {}, "outputs": {},
             "setup_steps": [], "steps": [], "teardown_steps": []},
            {"sequence_name": "Sub", "locals": {}, "parameters": {}, "outputs": {},
             "setup_steps": [], "steps": [], "teardown_steps": []},
        ]
        data = _make_recipe_data(sequences=seqs)
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert "Main" in r.sequences
        assert "Sub" in r.sequences

    def test_sequence_missing_name_skipped(self):
        """Verify that a sequence document without 'sequence_name' is silently skipped."""
        seqs = [
            {"sequence_name": "Main", "locals": {}, "parameters": {}, "outputs": {},
             "setup_steps": [], "steps": [], "teardown_steps": []},
            {"locals": {}, "parameters": {}, "outputs": {},
             "setup_steps": [], "steps": [], "teardown_steps": []},
        ]
        data = _make_recipe_data(sequences=seqs)
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert len(r.sequences) == 1

    def test_recipe_file_name_stored(self):
        """Verify that recipe_file_name stores only the filename (not the full path)."""
        data = _make_recipe_data()
        r = Recipe("path/to/my_recipe.yaml", file_loader=_loader_for(data))
        assert r.recipe_file_name == "my_recipe.yaml"

    def test_globals_stored(self):
        """Verify that global variables from the recipe are stored."""
        data = _make_recipe_data(overrides={"globals": {"host": "10.0.0.1", "port": 22}})
        r = Recipe("fake.yaml", file_loader=_loader_for(data))
        assert r.globals == {"host": "10.0.0.1", "port": 22}


# ============================================================
# Recipe from YAML file
# ============================================================

class TestRecipeFromYaml:
    def test_metadata_loaded_correctly(self, recipe_from_yaml):
        """Verify that the YAML recipe name, version, and description are parsed."""
        assert recipe_from_yaml.name == "Example Test Recipe"
        assert recipe_from_yaml.version == "0.1.0"
        assert recipe_from_yaml.description.startswith("A sample recipe")

    def test_main_sequence_exists_and_has_steps(self, recipe_from_yaml):
        """Verify the Main sequence has the expected number of steps."""
        assert "Main" in recipe_from_yaml.sequences
        main_sequence = recipe_from_yaml.sequences["Main"]
        assert hasattr(main_sequence, "steps")
        assert isinstance(main_sequence.steps, list)
        assert len(main_sequence.steps) == 5

    def test_range_check_pass_fail(self, recipe_from_yaml, runtime):
        """Verify that a value inside range produces PASS and outside range produces FAIL."""
        runtime.set_globals(recipe_from_yaml.globals)
        runtime.set_sequences(recipe_from_yaml.sequences)
        runtime.test_package = recipe_from_yaml.test_package

        inside_step = recipe_from_yaml.sequences["Main"].steps[3]
        outside_step = recipe_from_yaml.sequences["Main"].steps[4]

        inside_result = inside_step.process_outputs(runtime, inside_step.run(runtime, {}).outputs)
        outside_result = outside_step.process_outputs(runtime, outside_step.run(runtime, {}).outputs)

        assert inside_result is ResultType.PASS
        assert outside_result is ResultType.FAIL


# ============================================================
# Sequence
# ============================================================

class TestSequence:
    def test_no_data_no_file_raises(self):
        """Verify that creating a Sequence with no data and no file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            Sequence()

    def test_from_data(self):
        """Verify that a Sequence can be constructed from a data dict."""
        seq_data = {
            "sequence_name": "TestSeq",
            "locals": {"x": 1},
            "parameters": ["p1"],
            "outputs": ["o1"],
            "setup_steps": [],
            "steps": [{"steptype": "WaitStep", "step_name": "W", "input_mapping": {}, "output_mapping": {}}],
            "teardown_steps": [],
        }
        seq = Sequence(sequence_data=seq_data)
        assert seq.name == "TestSeq"
        assert seq.locals == {"x": 1}
        assert len(seq.steps) == 1

    def test_from_data_with_build_step_mock(self):
        """Verify Sequence construction with mocked Step.build_step."""
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
            sequence = Sequence(sequence_data=sequence_data)

        assert sequence.name == "TestSeq"
        assert sequence.locals == {"var1": None}
        assert len(sequence.steps) == 1
        assert sequence.steps[0].name == "MockStep"

    def test_run_executes_steps(self):
        """Verify that Sequence.run calls setup, main, and teardown steps via Step.run_steps."""
        mock_runtime = MagicMock()
        mock_runtime.send_event = MagicMock()
        mock_runtime.set_local = MagicMock()
        mock_runtime.push_locals = MagicMock()
        mock_runtime.pop_locals = MagicMock()

        mock_step_result = MagicMock()
        with patch("pypts.recipe.StepResult.evaluate_multiple_step_results", return_value="final_result"), \
             patch("pypts.recipe.Step.run_steps",
                   side_effect=lambda runtime, steps, parent, **kwargs: [mock_step_result] * len(steps)):

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
                seq = Sequence(sequence_data=sequence_data)
                result = seq.run(mock_runtime, input={"test_param": 123})

        assert result == "final_result"
        assert mock_runtime.set_local.called
        assert mock_runtime.push_locals.called
        assert mock_runtime.pop_locals.called
        assert mock_runtime.send_event.call_count == 2  # pre_run_sequence + post_run_sequence

    def test_teardown_runs_even_after_error(self):
        """Verify that teardown steps execute even when main steps raise an exception."""
        mock_runtime = MagicMock()
        mock_runtime.stop_event = Event()
        mock_runtime.send_event = MagicMock()
        mock_runtime.push_locals = MagicMock()
        mock_runtime.pop_locals = MagicMock()
        mock_runtime.set_local = MagicMock()

        mock_teardown_result = MagicMock()
        mock_teardown_result.get_result.return_value = ResultType.DONE

        call_count = [0]
        def run_steps_side_effect(runtime, steps, parent, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("step failure")
            return [mock_teardown_result]

        with patch("pypts.recipe.Step.build_step", return_value=MagicMock()), \
             patch("pypts.recipe.Step.run_steps", side_effect=run_steps_side_effect), \
             patch("pypts.recipe.StepResult.evaluate_multiple_step_results", return_value=ResultType.ERROR):
            seq_data = {
                "sequence_name": "S",
                "locals": {},
                "parameters": [],
                "outputs": [],
                "setup_steps": [],
                "steps": [{"steptype": "DummyStep"}],
                "teardown_steps": [{"steptype": "DummyStep"}],
            }
            seq = Sequence(sequence_data=seq_data)
            result = seq.run(mock_runtime, {})

        # Teardown was called (run_steps called twice total)
        assert call_count[0] == 2


# ============================================================
# Step
# ============================================================

class TestStep:
    def test_initialization(self):
        """Verify Step stores name and generates a UUID."""
        step = Step(step_name="MyStep", input_mapping={"a": {"type": "direct", "value": 1}})
        assert step.name == "MyStep"
        assert isinstance(step.id, uuid.UUID)

    def test_check_indexing_false(self):
        """Verify check_indexing returns False when no input is marked indexed."""
        step = Step("TestStep", input_mapping={"a": {"type": "direct", "value": 5}})
        assert step.check_indexing() is False

    def test_check_indexing_true(self):
        """Verify check_indexing returns True when an input has indexed=True."""
        step = Step("TestStep", input_mapping={"a": {"type": "direct", "value": 5, "indexed": True}})
        assert step.check_indexing() is True


# ============================================================
# SerialNumberStep
# ============================================================

class TestSerialNumberStep:
    def test_sends_event_and_stores_serial(self):
        """Verify SerialNumberStep sends get_serial_number event, stores the serial
        in runtime.serial_number, and sets the global variable."""
        step = SerialNumberStep(
            step_name="Get Serial Number",
            input_mapping={},
            output_mapping={}
        )

        mock_runtime = MagicMock()
        mock_runtime.stop_event = Event()

        def mock_send_event(event_name, response_q, *args):
            if event_name == "get_serial_number":
                response_q.put("TEST123")

        mock_runtime.send_event.side_effect = mock_send_event

        result = step._step(mock_runtime, {}, uuid.uuid4())

        assert result["serial_number"] == "TEST123"
        assert mock_runtime.serial_number == "TEST123"
        mock_runtime.set_global.assert_called_once_with("serial_number", "TEST123")


# ============================================================
# StepResult
# ============================================================

class TestStepResult:
    def test_initialization_defaults(self):
        """Verify StepResult defaults: UUID generated, result is None, empty inputs/outputs."""
        sr = StepResult()
        assert isinstance(sr.uuid, uuid.UUID)
        assert sr.result is None
        assert sr.inputs == {}
        assert sr.outputs == {}
        assert sr.error_info == ""
        assert isinstance(sr.subresults, list)
        assert sr.parent is None
        assert sr.recipe_name is None
        assert sr.recipe_file_name is None
        assert sr.sequence_name is None
        assert sr.pypts_version == "unknown"

    def test_set_error(self):
        """Verify set_error sets result to ERROR with error_info and inputs."""
        sr = StepResult()
        sr.set_error(error_info="An error occurred", inputs={"key": "value"})
        assert sr.result == ResultType.ERROR
        assert sr.error_info == "An error occurred"
        assert sr.inputs == {"key": "value"}

    def test_set_skip(self):
        """Verify set_skip sets result to SKIP."""
        sr = StepResult()
        sr.set_skip()
        assert sr.result == ResultType.SKIP

    def test_set_result(self):
        """Verify set_result stores the given result type, inputs, and outputs."""
        sr = StepResult()
        sr.set_result(result_type=ResultType.PASS, inputs={"input1": "value"}, outputs={"output1": "value"})
        assert sr.result == ResultType.PASS
        assert sr.inputs == {"input1": "value"}
        assert sr.outputs == {"output1": "value"}

    def test_set_stop(self):
        """Verify set_stop sets result to STOP with error_info and inputs."""
        sr = StepResult()
        sr.set_stop(error_info="aborted", inputs={"k": "v"})
        assert sr.result == ResultType.STOP
        assert sr.error_info == "aborted"
        assert sr.inputs == {"k": "v"}

    def test_append_subresult(self):
        """Verify that subresults can be appended and are stored correctly."""
        sr = StepResult()
        sub = StepResult()
        sub.set_result(ResultType.FAIL)
        sr.append_subresult(sub)
        assert len(sr.subresults) == 1
        assert sr.subresults[0].result == ResultType.FAIL

    def test_get_result_by_uuid(self):
        """Verify that a StepResult can be found by its UUID."""
        sr1 = StepResult()
        sr1.set_result(ResultType.PASS)
        sr2 = StepResult()
        sr2.set_result(ResultType.FAIL)

        found = StepResult.get_result_by_uuid([sr1, sr2], sr2.uuid)
        assert found.result == ResultType.FAIL

    def test_get_result_by_uuid_not_found(self):
        """Verify that searching for a non-existent UUID returns None."""
        sr = StepResult()
        assert StepResult.get_result_by_uuid([sr], uuid.uuid4()) is None

    def test_get_result_by_uuid_in_subresults(self):
        """Verify that searching finds results nested in subresults."""
        parent = StepResult()
        child = StepResult()
        parent.append_subresult(child)
        found = StepResult.get_result_by_uuid([parent], child.uuid)
        assert found is child

    def test_evaluate_multiple_step_results(self):
        """Verify that evaluating multiple results returns the highest severity."""
        sr1 = StepResult()
        sr1.set_result(ResultType.PASS)
        sr2 = StepResult()
        sr2.set_result(ResultType.FAIL)

        highest = StepResult.evaluate_multiple_step_results([sr1, sr2])
        assert highest == ResultType.FAIL  # FAIL > PASS

    def test_evaluate_all_skip(self):
        """Verify that when all results are SKIP, evaluation returns SKIP."""
        results = [StepResult() for _ in range(3)]
        for r in results:
            r.set_skip()
        assert StepResult.evaluate_multiple_step_results(results) == ResultType.SKIP

    def test_evaluate_mixed(self):
        """Verify that ERROR is returned when mixed with DONE and PASS."""
        r1 = StepResult()
        r1.set_result(ResultType.DONE)
        r2 = StepResult()
        r2.set_result(ResultType.ERROR)
        r3 = StepResult()
        r3.set_result(ResultType.PASS)
        assert StepResult.evaluate_multiple_step_results([r1, r2, r3]) == ResultType.ERROR

    def test_is_type(self):
        """Verify is_type returns True for matching type and False otherwise."""
        sr = StepResult()
        sr.set_result(ResultType.PASS)
        assert sr.is_type(ResultType.PASS)
        assert not sr.is_type(ResultType.FAIL)

    def test_print_result(self):
        """Verify set_result(PASS) can be set without raising exceptions."""
        sr = StepResult()
        sr.set_result(ResultType.PASS)
        assert sr.result == ResultType.PASS

    def test_print_result_with_subresults(self):
        """Verify subresults are accessible after being appended."""
        sr = StepResult()
        sr.set_result(ResultType.PASS)
        sub = StepResult()
        sub.set_result(ResultType.FAIL)
        sr.append_subresult(sub)
        assert len(sr.subresults) == 1
        assert sr.subresults[0].result == ResultType.FAIL


# ============================================================
# serialize()
# ============================================================

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3


class TestSerialize:
    def test_enum(self):
        """Verify that Enum members serialize to their name."""
        assert serialize(Color.RED) == "RED"
        assert serialize(Color.GREEN) == "GREEN"
        assert serialize(Color.BLUE) == "BLUE"

    def test_result_type_enum(self):
        """Verify that ResultType members serialize to their name."""
        assert serialize(ResultType.PASS) == "PASS"

    def test_basic_types(self):
        """Verify that int, float, and str serialize to their string representation."""
        assert serialize(1234) == "1234"
        assert serialize(45.67) == "45.67"
        assert serialize("hello") == "hello"

    def test_none(self):
        """Verify that None serializes to the string 'None'."""
        assert serialize(None) == "None"

    def test_dict(self):
        """Verify that dicts are serialized recursively."""
        result = serialize({"a": 1, "b": ResultType.FAIL})
        assert result == {"a": "1", "b": "FAIL"}

    def test_list(self):
        """Verify that lists are serialized recursively."""
        result = serialize([1, "hello", ResultType.DONE])
        assert result == ["1", "hello", "DONE"]

    def test_set(self):
        """Verify that sets are serialized to a list."""
        result = serialize({1})
        assert isinstance(result, list)
        assert "1" in result

    def test_tuple(self):
        """Verify that tuples are serialized to a list."""
        result = serialize((1, 2))
        assert result == ["1", "2"]

    def test_object_with_dict(self):
        """Verify that objects with __dict__ are serialized recursively."""
        class Obj:
            def __init__(self):
                self.x = 42
        result = serialize(Obj())
        assert result["x"] == "42"

    def test_circular_reference(self):
        """Verify that circular references are handled without infinite recursion."""
        d = {}
        d["self"] = d
        result = serialize(d)
        assert "Circular reference" in str(result)


# ============================================================
# Runtime
# ============================================================

class TestRuntime:
    def test_initialization(self, runtime):
        """Verify Runtime default state after construction."""
        assert isinstance(runtime, Runtime)
        assert runtime.event_queue.empty()
        assert runtime.report_queue.empty()
        assert runtime.results == []
        assert runtime.globals == []
        assert runtime.sequences == {}
        assert runtime.local_stack == []
        assert runtime.recipe_name is None
        assert runtime.recipe_file_name is None
        assert runtime.current_sequence_name is None
        assert runtime.pypts_version == "unknown"

    def test_push_locals(self, runtime):
        """Verify pushing locals adds them to the stack."""
        runtime.push_locals({'a': 1, 'b': 2})
        assert len(runtime.local_stack) == 1
        assert runtime.local_stack[-1] == {'a': 1, 'b': 2}

    def test_pop_locals(self, runtime):
        """Verify popping locals removes and returns the top frame."""
        runtime.push_locals({'a': 1, 'b': 2})
        popped = runtime.pop_locals()
        assert popped == {'a': 1, 'b': 2}
        assert len(runtime.local_stack) == 0

    def test_get_local(self, runtime):
        """Verify that get_local retrieves values from the top locals frame."""
        runtime.push_locals({'a': 1, 'b': 2})
        assert runtime.get_local('a') == 1
        assert runtime.get_local('b') == 2

    def test_set_local(self, runtime):
        """Verify that set_local updates a value in the top locals frame."""
        runtime.push_locals({'a': 1, 'b': 2})
        runtime.set_local('a', 10)
        assert runtime.get_local('a') == 10
        assert runtime.get_local('b') == 2

    def test_local_stack_multiple_levels(self, runtime):
        """Verify that multiple push/pop operations maintain correct stack semantics."""
        runtime.push_locals({"a": 1})
        runtime.push_locals({"b": 2})
        assert runtime.get_local("b") == 2
        runtime.pop_locals()
        assert runtime.get_local("a") == 1

    def test_get_local_missing_raises(self, runtime):
        """Verify that accessing a non-existent local variable raises KeyError."""
        runtime.push_locals({"a": 1})
        with pytest.raises(KeyError):
            runtime.get_local("nonexistent")

    def test_set_globals(self, runtime):
        """Verify setting and getting global variables."""
        globals_data = {'global1': 'value1', 'global2': 'value2'}
        runtime.set_globals(globals_data)
        assert runtime.get_globals() == globals_data

    def test_set_global_and_get(self, runtime):
        """Verify individual global variable access."""
        runtime.set_globals({"x": 10, "y": 20})
        assert runtime.get_global("x") == 10
        assert runtime.get_global("y") == 20

    def test_get_global_missing_returns_none(self, runtime):
        """Verify that accessing a non-existent global returns None."""
        runtime.set_globals([])
        assert runtime.get_global(99) is None

    def test_sequences(self, runtime):
        """Verify setting and getting sequences."""
        mock_seq = MagicMock()
        runtime.set_sequences({"Main": mock_seq})
        assert runtime.get_sequence("Main") is mock_seq

    def test_append_result_to_root(self, runtime):
        """Verify appending a result with no parent adds to the root results list."""
        result = StepResult()
        runtime.append_result(None, result)
        assert result in runtime.get_results()

    def test_append_result_to_parent(self, runtime):
        """Verify appending a result with a parent UUID adds it as a subresult."""
        parent = StepResult()
        runtime.append_result(None, parent)
        child = StepResult()
        runtime.append_result(parent.uuid, child)
        assert child in parent.subresults

    def test_append_subresult_with_explicit_uuid(self, runtime):
        """Verify appending a subresult using an explicit parent UUID."""
        parent_step_id = uuid.uuid4()
        parent = StepResult()
        parent.uuid = parent_step_id

        runtime.append_result(None, parent)
        assert len(runtime.get_results()) == 1

        sub = StepResult()
        sub.set_result(ResultType.DONE)
        runtime.append_result(parent_step_id, sub)

        assert len(parent.subresults) == 1
        assert parent.subresults[0] == sub

    def test_send_event(self, runtime):
        """Verify that send_event places the event tuple in the event queue."""
        runtime.send_event("test_event", "data1", "data2")
        event = runtime.event_queue.get()
        assert event == ("test_event", ("data1", "data2"))

    def test_send_event_with_mock_queue(self, runtime):
        """Verify send_event calls put() on the event queue with correct arguments."""
        mock_event_queue = MagicMock()
        runtime.event_queue = mock_event_queue
        runtime.send_event('event_test', 'data1', 2)
        mock_event_queue.put.assert_called_once_with(('event_test', ('data1', 2)))
