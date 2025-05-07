import pytest
import uuid
from unittest.mock import MagicMock
from pypts.steps import Step, PythonModuleStep, IndexedStep, UserInteractionStep, WaitStep, SequenceStep

# === Minimal mock Runtime class ===
class MockRuntime:
    def __init__(self):
        self.recipe_name = "TestRecipe"
        self.recipe_file_name = "test_file.py"
        self.serial_number = "123456"
        self.current_sequence_name = "main"
        self.pypts_version = "0.1"
        self.report_queue = MagicMock()
        self._results = []

    def append_result(self, parent_step, result):
        self._results.append(result)

    def send_event(self, *args, **kwargs):
        pass

    def get_local(self, name):
        return f"local-{name}"

    def get_global(self, name):
        return f"global-{name}"

    def set_local(self, name, value):
        pass

    def set_global(self, name, value):
        pass

# === Simple test step subclass ===
class DummyStep(Step):
    def _step(self, runtime, input, parent_step):
        return {"dummy_output": 42}


def test_step_initialization():
    step = Step(step_name="Test Step")
    assert step.name == "Test Step"
    assert isinstance(step.id, uuid.UUID)
    assert not step.skip

def test_step_skip_flag():
    step = Step(step_name="Skip Step", skip=True)
    assert step.is_skipped()

def test_check_indexing_true():
    step = Step(step_name="Indexing Step", input_mapping={"in1": {"indexed": True}})
    assert step.check_indexing()

def test_check_indexing_false():
    step = Step(step_name="Non-Indexed Step", input_mapping={"in1": {"indexed": False}})
    assert not step.check_indexing()

def test_process_inputs_direct():
    step = Step(step_name="Direct Input", input_mapping={"foo": {"value": 123}})
    runtime = MockRuntime()
    inputs = step.process_inputs(runtime)
    assert inputs["foo"] == 123

def test_process_inputs_local_global():
    step = Step(
        step_name="Input Map",
        input_mapping={
            "x": {"type": "local", "local_name": "foo"},
            "y": {"type": "global", "global_name": "bar"},
        },
    )
    runtime = MockRuntime()
    inputs = step.process_inputs(runtime)
    assert inputs["x"] == "local-foo"
    assert inputs["y"] == "global-bar"

def test_indexed_step_creation():
    base_step = DummyStep(step_name="Inner", input_mapping={"a": {"indexed": True}})
    indexed_step = IndexedStep(base_step, step_name="Indexed")
    assert indexed_step.template_step.name == "Inner"
    assert isinstance(indexed_step, Step)
    assert indexed_step.name == "Indexed"
