# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest
import uuid
import copy
import time
import queue
from threading import Event
from unittest.mock import MagicMock, patch, PropertyMock
from pypts.recipe import Step, StepResult, ResultType, Runtime, Sequence
from pypts.steps import (
    IndexedStep,
    PythonModuleStep,
    SequenceStep,
    UserInteractionStep,
    WaitStep,
    UserLoadingStep,
    UserRunMethodStep,
    UserWriteStep,
    SerialNumberStep,
    SSHConnectStep,
    SSHCloseStep,
    SSHUploadStep,
    _sha256_file,
    _remote_file_exists,
    _remote_sha256,
)


# ============================================================
# Helpers & Fixtures
# ============================================================

class DummyStep(Step):
    """A minimal step that returns a fixed output dict."""
    def _step(self, runtime, input, parent_step):
        return {"value": 42}


class FailingStep(Step):
    """A step that always raises."""
    def _step(self, runtime, input, parent_step):
        raise ValueError("deliberate failure")


class PassFailStep(Step):
    """Returns whatever inputs are given back as outputs."""
    def _step(self, runtime, input, parent_step):
        return input


@pytest.fixture
def mock_runtime():
    """A lightweight mock Runtime that satisfies Step.run's contract."""
    rt = MagicMock(spec=Runtime)
    rt.stop_event = Event()
    rt.recipe_name = "TestRecipe"
    rt.recipe_file_name = "test.yaml"
    rt.serial_number = "SN001"
    rt.current_sequence_name = "Main"
    rt.pypts_version = "0.1.0"
    rt.report_queue = MagicMock()
    rt.continue_on_error = False
    rt.results = []
    return rt


@pytest.fixture
def real_runtime():
    """A real Runtime instance with queues for integration-style tests."""
    eq = queue.SimpleQueue()
    rq = queue.SimpleQueue()
    rt = Runtime(eq, rq)
    return rt


# ============================================================
# Step base class
# ============================================================

class TestStepInit:
    def test_defaults(self):
        step = Step(step_name="S1")
        assert step.name == "S1"
        assert isinstance(step.id, uuid.UUID)
        assert step.skip is False
        assert step.critical is False
        assert step.input_mapping == {}
        assert step.output_mapping == {}

    def test_custom_id(self):
        step = Step(step_name="S1", id="my-id")
        assert step.id == "my-id"

    def test_skip_flag(self):
        step = Step(step_name="S1", skip=True)
        assert step.is_skipped() is True

    def test_critical_flag(self):
        step = Step(step_name="S1", critical=True)
        assert step.is_critical() is True

    def test_str(self):
        step = DummyStep(step_name="MyStep")
        assert "DummyStep" in str(step)
        assert "MyStep" in str(step)


class TestCheckIndexing:
    def test_no_indexed_inputs(self):
        step = Step(step_name="S", input_mapping={"a": {"type": "direct", "value": 1}})
        assert step.check_indexing() is False

    def test_indexed_false(self):
        step = Step(step_name="S", input_mapping={"a": {"indexed": False}})
        assert step.check_indexing() is False

    def test_indexed_true(self):
        step = Step(step_name="S", input_mapping={"a": {"indexed": True}})
        assert step.check_indexing() is True

    def test_mixed_inputs(self):
        step = Step(step_name="S", input_mapping={
            "a": {"type": "direct", "value": 1},
            "b": {"indexed": True, "value": [1, 2]},
        })
        assert step.check_indexing() is True


# ============================================================
# Step.process_inputs
# ============================================================

class TestProcessInputs:
    def test_direct_value(self, mock_runtime):
        step = Step(step_name="S", input_mapping={"x": {"type": "direct", "value": 99}})
        result = step.process_inputs(mock_runtime)
        assert result["x"] == 99

    def test_inferred_direct_when_no_type(self, mock_runtime):
        step = Step(step_name="S", input_mapping={"x": {"value": 42}})
        result = step.process_inputs(mock_runtime)
        assert result["x"] == 42

    def test_local_variable(self, mock_runtime):
        mock_runtime.get_local.return_value = "local_val"
        step = Step(step_name="S", input_mapping={"x": {"type": "local", "local_name": "myvar"}})
        result = step.process_inputs(mock_runtime)
        assert result["x"] == "local_val"
        mock_runtime.get_local.assert_called_with("myvar")

    def test_global_variable(self, mock_runtime):
        mock_runtime.get_global.return_value = "global_val"
        step = Step(step_name="S", input_mapping={"x": {"type": "global", "global_name": "gvar"}})
        result = step.process_inputs(mock_runtime)
        assert result["x"] == "global_val"
        mock_runtime.get_global.assert_called_with("gvar")

    def test_global_name_shortcut(self, mock_runtime):
        """When global_name is set directly (without type), it fetches from globals."""
        mock_runtime.get_global.return_value = "gval"
        step = Step(step_name="S", input_mapping={"x": {"global_name": "ssh_client"}})
        result = step.process_inputs(mock_runtime)
        assert result["x"] == "gval"

    def test_method_type(self, mock_runtime):
        step = Step(step_name="S", input_mapping={"x": {"type": "method", "value": "func_ref"}})
        result = step.process_inputs(mock_runtime)
        assert result["x"] == "func_ref"


# ============================================================
# Step.process_outputs
# ============================================================

class TestProcessOutputs:
    def test_passthrough(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"res": {"type": "passthrough"}})
        result = step.process_outputs(mock_runtime, {"res": ResultType.PASS})
        assert result == ResultType.PASS

    def test_passfail_true(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"ok": {"type": "passfail"}})
        result = step.process_outputs(mock_runtime, {"ok": True})
        assert result == ResultType.PASS

    def test_passfail_false(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"ok": {"type": "passfail"}})
        result = step.process_outputs(mock_runtime, {"ok": False})
        assert result == ResultType.FAIL

    def test_equals_match(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "equals", "value": 10}})
        result = step.process_outputs(mock_runtime, {"val": 10})
        assert result == ResultType.PASS

    def test_equals_mismatch(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "equals", "value": 10}})
        result = step.process_outputs(mock_runtime, {"val": 99})
        assert result == ResultType.FAIL

    def test_range_inside(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "range", "min": 5, "max": 15}})
        result = step.process_outputs(mock_runtime, {"val": 10})
        assert result == ResultType.PASS

    def test_range_outside(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "range", "min": 5, "max": 15}})
        result = step.process_outputs(mock_runtime, {"val": 20})
        assert result == ResultType.FAIL

    def test_range_boundary_inclusive(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "range", "min": 5, "max": 15}})
        assert step.process_outputs(mock_runtime, {"val": 5}) == ResultType.PASS
        assert step.process_outputs(mock_runtime, {"val": 15}) == ResultType.PASS

    def test_global_output(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "global", "global_name": "gvar"}})
        result = step.process_outputs(mock_runtime, {"val": "saved"})
        mock_runtime.set_global.assert_called_with("gvar", "saved")
        # Global output doesn't change the result type
        assert result == ResultType.DONE

    def test_local_output(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "local", "local_name": "lvar"}})
        result = step.process_outputs(mock_runtime, {"val": "saved"})
        mock_runtime.set_local.assert_called_with("lvar", "saved")
        assert result == ResultType.DONE

    def test_local_output_missing_local_name(self, mock_runtime):
        step = Step(step_name="S", output_mapping={"val": {"type": "local"}})
        with pytest.raises(ValueError, match="missing required field 'local_name'"):
            step.process_outputs(mock_runtime, {"val": "x"})

    def test_no_output_mapping_returns_done(self, mock_runtime):
        step = Step(step_name="S", output_mapping={})
        result = step.process_outputs(mock_runtime, {"anything": 1})
        assert result == ResultType.DONE


# ============================================================
# Step.run (full lifecycle)
# ============================================================

class TestStepRun:
    def test_successful_run(self, mock_runtime):
        step = DummyStep(step_name="S", output_mapping={"value": {"type": "equals", "value": 42}})
        result = step.run(mock_runtime, {})
        assert isinstance(result, StepResult)
        assert result.result == ResultType.PASS
        assert result.outputs == {"value": 42}

    def test_skipped_step(self, mock_runtime):
        step = DummyStep(step_name="S", skip=True)
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.SKIP

    def test_error_in_step(self, mock_runtime):
        step = FailingStep(step_name="S")
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.ERROR
        assert "deliberate failure" in result.error_info

    def test_stop_event_before_execution(self, mock_runtime):
        mock_runtime.stop_event.set()
        step = DummyStep(step_name="S")
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.STOP

    def test_metadata_populated(self, mock_runtime):
        step = DummyStep(step_name="S")
        result = step.run(mock_runtime, {})
        assert result.recipe_name == "TestRecipe"
        assert result.recipe_file_name == "test.yaml"
        assert result.serial_number == "SN001"
        assert result.sequence_name == "Main"
        assert result.pypts_version == "0.1.0"

    def test_events_sent(self, mock_runtime):
        step = DummyStep(step_name="S")
        step.run(mock_runtime, {})
        event_calls = [c[0][0] for c in mock_runtime.send_event.call_args_list]
        assert "pre_run_step" in event_calls
        assert "post_run_step" in event_calls

    def test_result_sent_to_report_queue(self, mock_runtime):
        step = DummyStep(step_name="S")
        result = step.run(mock_runtime, {})
        mock_runtime.report_queue.put.assert_called_with(result)


# ============================================================
# Step.run_steps (multi-step execution)
# ============================================================

class TestRunSteps:
    def test_runs_all_steps(self, mock_runtime):
        steps = [DummyStep(step_name=f"S{i}") for i in range(3)]
        results = Step.run_steps(mock_runtime, steps, parent_step=None)
        assert len(results) == 3
        assert all(isinstance(r, StepResult) for r in results)

    def test_stops_on_error_by_default(self, mock_runtime):
        mock_runtime.continue_on_error = False
        mock_runtime.get_global.side_effect = Exception("no such global")
        steps = [DummyStep(step_name="OK"), FailingStep(step_name="FAIL"), DummyStep(step_name="NEVER")]
        results = Step.run_steps(mock_runtime, steps, parent_step=None)
        assert len(results) == 2
        assert results[1].result == ResultType.ERROR

    def test_continues_on_error_when_enabled(self, mock_runtime):
        mock_runtime.continue_on_error = True
        mock_runtime.get_global.return_value = True
        steps = [DummyStep(step_name="OK"), FailingStep(step_name="FAIL"), DummyStep(step_name="AFTER")]
        results = Step.run_steps(mock_runtime, steps, parent_step=None)
        assert len(results) == 3

    def test_critical_step_stops_even_with_continue_on_error(self, mock_runtime):
        mock_runtime.continue_on_error = True
        mock_runtime.get_global.return_value = True
        steps = [
            DummyStep(step_name="OK"),
            FailingStep(step_name="CRIT", critical=True),
            DummyStep(step_name="NEVER"),
        ]
        results = Step.run_steps(mock_runtime, steps, parent_step=None)
        assert len(results) == 2

    def test_empty_step_list(self, mock_runtime):
        results = Step.run_steps(mock_runtime, [], parent_step=None)
        assert results == []


# ============================================================
# Step.build_step
# ============================================================

class TestBuildStep:
    def test_build_wait_step(self):
        data = {"steptype": "WaitStep", "step_name": "Wait", "input_mapping": {"wait_time": {"type": "direct", "value": 0.01}}, "output_mapping": {}}
        step = Step.build_step(data)
        assert isinstance(step, WaitStep)
        assert step.name == "Wait"

    def test_build_case_insensitive(self):
        data = {"steptype": "waitstep", "step_name": "Wait", "input_mapping": {}, "output_mapping": {}}
        step = Step.build_step(data)
        assert isinstance(step, WaitStep)

    def test_build_sequence_step(self):
        data = {"steptype": "SequenceStep", "step_name": "SubSeq", "sequence": {"type": "internal", "name": "Sub"}, "input_mapping": {}, "output_mapping": {}}
        step = Step.build_step(data)
        assert isinstance(step, SequenceStep)

    def test_build_indexed_step_wraps_when_indexed(self):
        data = {
            "steptype": "WaitStep",
            "step_name": "IndexedWait",
            "input_mapping": {"wait_time": {"type": "direct", "value": [0.01, 0.02], "indexed": True}},
            "output_mapping": {},
        }
        step = Step.build_step(data)
        assert isinstance(step, IndexedStep)
        assert isinstance(step.template_step, WaitStep)

    def test_build_python_module_step(self):
        data = {
            "steptype": "PythonModuleStep",
            "step_name": "Run",
            "action_type": "method",
            "module": "my_module.py",
            "method_name": "my_func",
            "input_mapping": {},
            "output_mapping": {},
        }
        step = Step.build_step(data)
        assert isinstance(step, PythonModuleStep)

    def test_build_serial_number_step(self):
        data = {"steptype": "SerialNumberStep", "step_name": "SN", "input_mapping": {}, "output_mapping": {}}
        step = Step.build_step(data)
        assert isinstance(step, SerialNumberStep)


# ============================================================
# WaitStep
# ============================================================

class TestWaitStep:
    def test_waits_given_duration(self, mock_runtime):
        step = WaitStep(step_name="Wait", input_mapping={"wait_time": {"type": "direct", "value": 0.05}}, output_mapping={})
        start = time.monotonic()
        result = step.run(mock_runtime, {})
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04  # Allow small tolerance
        assert result.result == ResultType.DONE

    def test_negative_wait_raises(self, mock_runtime):
        step = WaitStep(step_name="Wait", input_mapping={"wait_time": {"type": "direct", "value": -1}}, output_mapping={})
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.ERROR


# ============================================================
# SequenceStep
# ============================================================

class TestSequenceStep:
    def test_init_requires_sequence_dict(self):
        with pytest.raises(ValueError, match="'sequence' dictionary"):
            SequenceStep(sequence="not_a_dict", step_name="S", input_mapping={}, output_mapping={})

    def test_init_requires_type_key(self):
        with pytest.raises(ValueError, match="'type' key"):
            SequenceStep(sequence={"name": "Sub"}, step_name="S", input_mapping={}, output_mapping={})

    def test_runs_internal_sequence(self, mock_runtime):
        mock_seq = MagicMock()
        mock_seq.run.return_value = ResultType.PASS
        mock_runtime.get_sequence.return_value = mock_seq

        step = SequenceStep(
            sequence={"type": "internal", "name": "Sub"},
            step_name="RunSub",
            input_mapping={},
            output_mapping={},
        )
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.PASS
        mock_seq.run.assert_called_once()

    def test_missing_sequence_errors(self, mock_runtime):
        mock_runtime.get_sequence.side_effect = KeyError("not found")
        step = SequenceStep(
            sequence={"type": "internal", "name": "Missing"},
            step_name="RunMissing",
            input_mapping={},
            output_mapping={},
        )
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.ERROR

    def test_unsupported_sequence_type_errors(self, mock_runtime):
        step = SequenceStep(
            sequence={"type": "unknown_type", "name": "X"},
            step_name="Bad",
            input_mapping={},
            output_mapping={},
        )
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.ERROR


# ============================================================
# UserInteractionStep
# ============================================================

class TestUserInteractionStep:
    def test_sends_event_and_returns_response(self, mock_runtime):
        step = UserInteractionStep(
            step_name="Ask",
            input_mapping={
                "message": {"type": "direct", "value": "Continue?"},
                "image_path": {"type": "direct", "value": None},
                "options": {"type": "direct", "value": ["Yes", "No"]},
            },
            output_mapping={"output": {"type": "passfail"}},
        )

        def capture_event(event_name, *args):
            if event_name == "user_interact":
                response_q = args[0]
                response_q.put("Yes")

        mock_runtime.send_event.side_effect = capture_event
        mock_runtime.get_global.side_effect = KeyError("no cancel_key")

        result = step.run(mock_runtime, {})
        assert result.outputs["output"] == "Yes"

    def test_stop_event_during_wait(self, mock_runtime):
        step = UserInteractionStep(
            step_name="Ask",
            input_mapping={
                "message": {"type": "direct", "value": "Wait..."},
                "image_path": {"type": "direct", "value": None},
                "options": {"type": "direct", "value": []},
            },
            output_mapping={"output": {"type": "passfail"}},
        )
        step.timeout_seconds = 0.01

        # Set stop event after a tiny delay
        def set_stop(*args, **kwargs):
            mock_runtime.stop_event.set()
        mock_runtime.send_event.side_effect = set_stop

        result = step.run(mock_runtime, {})
        assert result.outputs.get("output") is None


# ============================================================
# SerialNumberStep
# ============================================================

class TestSerialNumberStep:
    def test_stores_serial_number(self, mock_runtime):
        step = SerialNumberStep(step_name="SN", input_mapping={}, output_mapping={})

        def send_event_side_effect(event_name, *args):
            if event_name == "get_serial_number":
                response_q = args[0]
                response_q.put("ABC-123")

        mock_runtime.send_event.side_effect = send_event_side_effect

        result = step._step(mock_runtime, {}, uuid.uuid4())
        assert result["serial_number"] == "ABC-123"
        assert mock_runtime.serial_number == "ABC-123"
        mock_runtime.set_global.assert_called_with("serial_number", "ABC-123")

    def test_stop_event_returns_none(self, mock_runtime):
        step = SerialNumberStep(step_name="SN", input_mapping={}, output_mapping={})
        step.timeout_seconds = 0.01

        def set_stop(*args, **kwargs):
            mock_runtime.stop_event.set()

        mock_runtime.send_event.side_effect = set_stop

        result = step._step(mock_runtime, {}, uuid.uuid4())
        assert result["serial_number"] is None


# ============================================================
# IndexedStep
# ============================================================

class TestIndexedStep:
    def test_requires_step_instance(self):
        with pytest.raises(TypeError, match="valid Step instance"):
            IndexedStep("not_a_step", step_name="X")

    def test_wraps_template_step(self):
        template = DummyStep(step_name="Inner", input_mapping={"a": {"indexed": True}})
        indexed = IndexedStep(template, step_name="Outer")
        assert indexed.template_step is template
        assert indexed.check_indexing() is False  # wrapper itself is not indexed

    def test_runs_template_multiple_times(self, real_runtime):
        real_runtime.stop_event = Event()
        template = DummyStep(
            step_name="Inner",
            input_mapping={"a": {"type": "direct", "indexed": True}},
            output_mapping={},
        )
        indexed = IndexedStep(
            template,
            step_name="Outer",
            input_mapping={"a": {"type": "direct", "value": [1, 2, 3], "indexed": True}},
        )
        # Populate required runtime metadata
        real_runtime.recipe_name = "T"
        real_runtime.recipe_file_name = "t.yaml"
        real_runtime.serial_number = "SN"
        real_runtime.current_sequence_name = "Main"

        result = indexed.run(real_runtime, {})
        assert result.result is not None
        # The wrapper result plus 3 sub-step results are tracked via runtime.append_result
        # The 3 child step results are appended under the wrapper's uuid
        wrapper_result = real_runtime.results[0]
        assert len(wrapper_result.subresults) == 3

    def test_non_indexed_inputs_shared(self, mock_runtime):
        template = PassFailStep(
            step_name="Inner",
            input_mapping={
                "a": {"type": "direct", "indexed": True},
                "b": {"type": "direct"},
            },
            output_mapping={},
        )
        indexed = IndexedStep(
            template,
            step_name="Outer",
            input_mapping={
                "a": {"type": "direct", "value": [10, 20], "indexed": True},
                "b": {"type": "direct", "value": "shared"},
            },
        )

        result = indexed.run(mock_runtime, {})
        # Each sub-step should have received shared "b" value
        for sub in result.subresults:
            assert sub.inputs.get("b") == "shared"

    def test_empty_indexed_list_skips(self, mock_runtime):
        template = DummyStep(
            step_name="Inner",
            input_mapping={"a": {"type": "direct", "indexed": True}},
            output_mapping={},
        )
        indexed = IndexedStep(
            template,
            step_name="Outer",
            input_mapping={"a": {"type": "direct", "value": [], "indexed": True}},
        )

        result = indexed.run(mock_runtime, {})
        assert result.result == ResultType.SKIP


# ============================================================
# PythonModuleStep
# ============================================================

class TestPythonModuleStep:
    def test_init_requires_method_name_for_method_action(self):
        with pytest.raises(ValueError, match="method_name is required"):
            PythonModuleStep(
                action_type="method",
                module="mod.py",
                method_name=None,
                step_name="S",
                input_mapping={},
                output_mapping={},
            )

    def test_init_requires_module_path(self):
        with pytest.raises(ValueError, match="Module path is required"):
            PythonModuleStep(
                action_type="method",
                module="",
                method_name="func",
                step_name="S",
                input_mapping={},
                output_mapping={},
            )

    def test_method_call_returns_dict(self, mock_runtime):
        step = PythonModuleStep(
            action_type="method",
            module="os.path",
            method_name="exists",
            step_name="S",
            input_mapping={},
            output_mapping={},
        )

        # Mock the private __load_module to return a module with a testable function
        mock_module = MagicMock()
        mock_module.my_func = lambda x: {"result": x * 2}

        with patch.object(step, '_PythonModuleStep__load_module', return_value=mock_module):
            step.method_name = "my_func"
            output = step._step(mock_runtime, {"x": 5}, uuid.uuid4())

        assert output == {"result": 10}

    def test_method_call_wraps_non_dict(self, mock_runtime):
        step = PythonModuleStep(
            action_type="method",
            module="mod.py",
            method_name="func",
            step_name="S",
            input_mapping={},
            output_mapping={},
        )

        mock_module = MagicMock()
        mock_module.func = lambda: 42

        with patch.object(step, '_PythonModuleStep__load_module', return_value=mock_module):
            output = step._step(mock_runtime, {}, uuid.uuid4())

        assert output == {"output": 42}

    def test_method_call_none_returns_empty_dict(self, mock_runtime):
        step = PythonModuleStep(
            action_type="method",
            module="mod.py",
            method_name="func",
            step_name="S",
            input_mapping={},
            output_mapping={},
        )

        mock_module = MagicMock()
        mock_module.func = lambda: None

        with patch.object(step, '_PythonModuleStep__load_module', return_value=mock_module):
            output = step._step(mock_runtime, {}, uuid.uuid4())

        assert output == {}

    def test_read_attribute(self, mock_runtime):
        step = PythonModuleStep(
            action_type="read_attribute",
            module="mod.py",
            step_name="S",
            input_mapping={},
            output_mapping={},
        )

        mock_module = MagicMock()
        mock_module.MY_CONST = 99

        with patch.object(step, '_PythonModuleStep__load_module', return_value=mock_module):
            output = step._step(mock_runtime, {"attribute_name": "MY_CONST"}, uuid.uuid4())

        assert output["MY_CONST"] == 99

    def test_write_attribute(self, mock_runtime):
        step = PythonModuleStep(
            action_type="write_attribute",
            module="mod.py",
            step_name="S",
            input_mapping={},
            output_mapping={},
        )

        mock_module = MagicMock()

        with patch.object(step, '_PythonModuleStep__load_module', return_value=mock_module):
            output = step._step(
                mock_runtime,
                {"attribute_name": "MY_CONST", "attribute_value": 123},
                uuid.uuid4(),
            )

        assert mock_module.MY_CONST == 123
        assert output == {}

    def test_unknown_action_type_raises(self, mock_runtime):
        step = PythonModuleStep(
            action_type="method",  # set to valid to pass __init__
            module="mod.py",
            method_name="func",
            step_name="S",
            input_mapping={},
            output_mapping={},
        )
        step.action_type = "nonexistent"  # override after init

        mock_module = MagicMock()
        with patch.object(step, '_PythonModuleStep__load_module', return_value=mock_module):
            with pytest.raises(ValueError, match="Unknown action_type"):
                step._step(mock_runtime, {}, uuid.uuid4())


# ============================================================
# SSH steps
# ============================================================

class TestSSHHelpers:
    def test_sha256_file(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        digest = _sha256_file(f)
        import hashlib
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert digest == expected

    def test_remote_file_exists_true(self):
        sftp = MagicMock()
        sftp.stat.return_value = MagicMock()
        assert _remote_file_exists(sftp, "/tmp/test") is True

    def test_remote_file_exists_false(self):
        sftp = MagicMock()
        sftp.stat.side_effect = FileNotFoundError
        assert _remote_file_exists(sftp, "/tmp/missing") is False


class TestSSHConnectStep:
    def test_missing_host_raises(self, mock_runtime):
        mock_runtime.get_global.return_value = None
        step = SSHConnectStep(
            step_name="SSH",
            input_mapping={},
            output_mapping={},
        )
        result = step.run(mock_runtime, {})
        assert result.result == ResultType.ERROR

    @patch("pypts.steps.paramiko")
    def test_successful_connection(self, mock_paramiko, mock_runtime):
        def global_lookup(name):
            vals = {"host": "192.168.1.1", "user": "root", "password": "pass", "private_key": None, "port": "22"}
            return vals.get(name)
        mock_runtime.get_global.side_effect = global_lookup

        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_paramiko.AutoAddPolicy.return_value = MagicMock()

        step = SSHConnectStep(step_name="SSH", input_mapping={}, output_mapping={})
        output = step._step(mock_runtime, {}, uuid.uuid4())

        assert output["status"] == "connected"
        mock_client.connect.assert_called_once()


class TestSSHCloseStep:
    def test_close_active_connection(self, mock_runtime):
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        mock_runtime.get_global.side_effect = lambda name: mock_client if name == "ssh_client" else "host"
        step = SSHCloseStep(step_name="Close", input_mapping={}, output_mapping={})

        output = step._step(mock_runtime, {}, uuid.uuid4())
        assert output["status"] == "closed"
        mock_client.close.assert_called_once()

    def test_close_already_inactive(self, mock_runtime):
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = False
        mock_client.get_transport.return_value = mock_transport

        mock_runtime.get_global.side_effect = lambda name: mock_client if name == "ssh_client" else "host"
        step = SSHCloseStep(step_name="Close", input_mapping={}, output_mapping={})

        output = step._step(mock_runtime, {}, uuid.uuid4())
        assert output["status"] == "closed"
        mock_client.close.assert_not_called()


class TestSSHUploadStep:
    def test_upload_single_file(self, mock_runtime, tmp_path):
        test_file = tmp_path / "binary.bin"
        test_file.write_bytes(b"data")

        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_runtime.get_global.return_value = mock_client

        # Remote file doesn't exist
        mock_sftp.stat.side_effect = FileNotFoundError

        step = SSHUploadStep(
            files=[{"local": str(test_file), "remote": "/tmp/binary.bin"}],
            step_name="Upload",
            input_mapping={},
            output_mapping={},
            skip_if_sha256_match=False,
        )

        with patch.object(step, '_resolve_local', return_value=test_file):
            output = step._step(mock_runtime, {}, uuid.uuid4())

        assert output["passed"] is True
        assert "binary.bin" in output["deployed"]
        mock_sftp.put.assert_called_once()

    def test_skip_when_sha256_matches(self, mock_runtime, tmp_path):
        test_file = tmp_path / "binary.bin"
        test_file.write_bytes(b"data")
        import hashlib
        expected_hash = hashlib.sha256(b"data").hexdigest()

        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_runtime.get_global.return_value = mock_client

        step = SSHUploadStep(
            files=[{"local": str(test_file), "remote": "/tmp/binary.bin"}],
            step_name="Upload",
            input_mapping={},
            output_mapping={},
            skip_if_sha256_match=True,
        )

        with patch.object(step, '_resolve_local', return_value=test_file), \
             patch("pypts.steps._remote_file_exists", return_value=True), \
             patch("pypts.steps._remote_sha256", return_value=expected_hash):
            output = step._step(mock_runtime, {}, uuid.uuid4())

        assert output["passed"] is True
        assert "binary.bin" in output["skipped"]
        assert output["deployed"] == []
        mock_sftp.put.assert_not_called()

    def test_no_ssh_client_raises(self, mock_runtime):
        mock_runtime.get_global.return_value = None
        step = SSHUploadStep(
            files=[{"local": "x", "remote": "/tmp/x"}],
            step_name="Upload",
            input_mapping={},
            output_mapping={},
        )
        with pytest.raises(ValueError, match="ssh_client global is None"):
            step._step(mock_runtime, {}, uuid.uuid4())

    def test_permissions_from_octal_string(self):
        step = SSHUploadStep(
            files=[],
            permissions="0o755",
            step_name="Upload",
            input_mapping={},
            output_mapping={},
        )
        assert step.permissions == 0o755

    def test_missing_local_file_raises(self, mock_runtime, tmp_path):
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_runtime.get_global.return_value = mock_client

        step = SSHUploadStep(
            files=[{"local": "nonexistent.bin", "remote": "/tmp/x"}],
            step_name="Upload",
            input_mapping={},
            output_mapping={},
        )

        nonexistent = tmp_path / "nonexistent.bin"
        with patch.object(step, '_resolve_local', return_value=nonexistent):
            with pytest.raises(FileNotFoundError):
                step._step(mock_runtime, {}, uuid.uuid4())
