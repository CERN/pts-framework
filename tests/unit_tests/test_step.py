# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Step module (src/pypts/step/).

The layer under test is the execution unit: the base Step lifecycle
(resolve inputs -> _step() -> judge outputs -> StepResult), the Runtime it
runs against, the registry that replaced the old eval() factory, and the
one ported step type (WaitStep). Everything here drives the code with a
bare Runtime() - no queues, no Sequencer, no threads - because "steps are
testable stand-alone" is a spec requirement, not a convenience.
"""

import uuid

import pytest

from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import (
    SequenceFinished,
    SequenceStarted,
    StepExecuted,
    StepFinished,
    StepStarted,
)
from pypts.step.python_module_step import PythonModuleStep
from pypts.step.registry import STEP_TYPES, build_step
from pypts.step.runtime import Runtime
from pypts.step.step import Step, StepResult, run_sequence
from pypts.step.wait_step import WaitStep


class ReturnsDict(Step):
    """A minimal concrete step: returns whatever it was told to."""

    def __init__(self, payload=None, **kwargs):
        super().__init__(**kwargs)
        self.payload = payload

    def _step(self, runtime, step_input):
        return self.payload


class Raises(Step):
    """A step whose work fails - the ERROR path."""

    def _step(self, runtime, step_input):
        raise RuntimeError("the hardware is on fire")


class Notes(Step):
    """A step that records its own name, so a test can assert on ordering."""

    def __init__(self, ran, **kwargs):
        super().__init__(**kwargs)
        self.ran = ran

    def _step(self, runtime, step_input):
        self.ran.append(self.name)
        return {}


class FakeSequence:
    """The four attributes run_sequence() reads off a Sequence, and nothing else."""

    def __init__(self, name="Main", locals=None, steps=(), teardown_steps=()):
        self.name = name
        self.locals = locals if locals is not None else {}
        self.steps = list(steps)
        self.teardown_steps = list(teardown_steps)


# --------------------------------------------------------------------------
# The registry - the eval() replacement
# --------------------------------------------------------------------------


def test_step_type_is_resolved_without_eval():
    """old_code builds steps with eval() over the steptype string.

    That is arbitrary code execution driven by a recipe file. The registry
    is a plain dict lookup: nothing a recipe writes is ever executed.
    """
    step = build_step({"steptype": "Wait", "step_name": "pause", "wait_time": "0"})
    assert isinstance(step, WaitStep)
    assert step.name == "pause"


def test_steptype_matching_is_case_insensitive():
    """The old factory lower-cased eight of ten types and forgot the SSH two."""
    step = build_step({"steptype": "wait", "step_name": "pause", "wait_time": "0"})
    assert isinstance(step, WaitStep)


def test_build_step_does_not_mutate_the_callers_dict():
    """The old factory removed "steptype" from the YAML-loaded dict in place."""
    step_data = {"steptype": "Wait", "step_name": "pause", "wait_time": "0"}
    build_step(step_data)
    assert step_data == {"steptype": "Wait", "step_name": "pause", "wait_time": "0"}


def test_unknown_steptype_raises_a_clear_error_listing_available_types():
    with pytest.raises(ValueError, match="PythonModulStep") as excinfo:
        build_step({"steptype": "PythonModulStep", "step_name": "typo"})
    assert "pythonmodule" in str(excinfo.value)


def test_the_rules_and_the_registry_agree_on_the_steptypes():
    """rules.py is the one source for what each type requires; the registry is
    the one source for what exists. They must name the same types."""
    from pypts.recipe.rules import STEP_TYPE_REQUIRED

    assert set(STEP_TYPE_REQUIRED) == set(STEP_TYPES)


# --------------------------------------------------------------------------
# Step identity
# --------------------------------------------------------------------------


def test_step_ids_are_stable_and_unique():
    """An explicit id survives; absent ids never collide."""
    fixed = "12345678-1234-5678-1234-567812345678"
    with_id = ReturnsDict(step_name="a", id=fixed)
    assert with_id.id == uuid.UUID(fixed)

    one = ReturnsDict(step_name="b")
    two = ReturnsDict(step_name="c")
    assert one.id != two.id


def test_mappings_are_not_shared_between_steps():
    """The old base had mutable-default mappings - one dict for every step (F12)."""
    one = ReturnsDict(step_name="a")
    two = ReturnsDict(step_name="b")
    one.output_mapping["__result"] = {"type": "passthrough"}
    assert two.output_mapping == {}


# --------------------------------------------------------------------------
# process_inputs
# --------------------------------------------------------------------------


def test_inputs_resolve_direct_local_and_global():
    runtime = Runtime(globals={"limit": 9})
    runtime.push_locals({"target": 45})
    step = ReturnsDict(
        step_name="resolve",
        input_mapping={
            "value": {"type": "direct", "value": "3"},
            "target": {"type": "local", "local_name": "target"},
            "limit": {"type": "global", "global_name": "limit"},
        },
    )
    assert step.process_inputs(runtime) == {"value": "3", "target": 45, "limit": 9}


def test_an_input_without_a_type_defaults_to_direct():
    """simple_recipe.yml writes wait_time with only a value key - no type."""
    step = ReturnsDict(step_name="untyped", input_mapping={"wait_time": {"value": "3"}})
    assert step.process_inputs(Runtime()) == {"wait_time": "3"}


def test_an_unknown_input_type_is_refused():
    """The old code silently left the raw config dict in place."""
    step = ReturnsDict(step_name="bad", input_mapping={"x": {"type": "telepathy"}})
    with pytest.raises(ValueError, match="telepathy"):
        step.process_inputs(Runtime())


# --------------------------------------------------------------------------
# process_outputs
# --------------------------------------------------------------------------


def judge(output_mapping, step_output, runtime=None):
    """Run one process_outputs() call with the least ceremony possible."""
    step = ReturnsDict(step_name="judge", output_mapping=output_mapping)
    return step.process_outputs(runtime if runtime is not None else Runtime(), step_output)


def test_an_empty_output_mapping_judges_done():
    assert judge({}, {}) is ResultType.DONE


def test_passfail_equals_and_range_verdicts():
    assert judge({"ok": {"type": "passfail"}}, {"ok": True}) is ResultType.PASS
    assert judge({"ok": {"type": "passfail"}}, {"ok": False}) is ResultType.FAIL
    assert judge({"v": {"type": "equals", "value": "yes"}}, {"v": "yes"}) is ResultType.PASS
    assert judge({"v": {"type": "equals", "value": "yes"}}, {"v": "no"}) is ResultType.FAIL
    assert judge({"v": {"type": "range", "min": "10", "max": "20"}}, {"v": "15"}) is ResultType.PASS
    assert judge({"v": {"type": "range", "min": "10", "max": "20"}}, {"v": "25"}) is ResultType.FAIL


def test_passthrough_propagates_a_result():
    assert judge({"r": {"type": "passthrough"}}, {"r": ResultType.STOP}) is ResultType.STOP


def test_local_and_global_entries_store_without_judging():
    runtime = Runtime(globals={})
    runtime.push_locals({})
    mapping = {
        "a": {"type": "local", "local_name": "kept_local"},
        "b": {"type": "global", "global_name": "kept_global"},
    }
    assert judge(mapping, {"a": 1, "b": 2}, runtime) is ResultType.DONE
    assert runtime.get_local("kept_local") == 1
    assert runtime.get_global("kept_global") == 2


def test_the_last_judging_entry_wins():
    """Documented behaviour, kept from the old engine for parity (F6).

    A fail-then-pass mapping reports PASS. Revisiting this (all checks must
    pass) is a recorded roadmap TODO - this test pins the current contract.
    """
    mapping = {
        "first": {"type": "passfail"},
        "second": {"type": "passfail"},
    }
    assert judge(mapping, {"first": False, "second": True}) is ResultType.PASS


def test_an_unknown_output_type_is_refused():
    with pytest.raises(ValueError, match="telepathy"):
        judge({"x": {"type": "telepathy"}}, {"x": 1})


# --------------------------------------------------------------------------
# The run() lifecycle
# --------------------------------------------------------------------------


def test_a_step_run_produces_a_result_and_both_events():
    events = []
    runtime = Runtime(emit=events.append)
    step = ReturnsDict(
        step_name="works", payload={"ok": True}, output_mapping={"ok": {"type": "passfail"}}
    )

    result = step.run(runtime)

    assert result.result is ResultType.PASS
    assert result.outputs == {"ok": True}
    # The rich StepExecuted for the Report follows; its own test is below.
    assert events[:2] == [
        StepStarted(step_id=step.id, step_name="works"),
        StepFinished(outcome=result.to_outcome()),
    ]


def test_a_step_run_emits_the_rich_record_for_the_report():
    """StepExecuted carries what the CSV needs: type, data, and timing.

    Emitted last, after StepFinished - the frontend's flat event is not held
    up by the record keeping.
    """
    events = []
    runtime = Runtime(emit=events.append)
    step = WaitStep(step_name="pause", wait_time="0.05")

    result = step.run(runtime)

    executed = [event for event in events if isinstance(event, StepExecuted)]
    assert len(executed) == 1
    record = executed[0]
    assert events[-1] is record
    assert record.outcome == result.to_outcome()
    assert record.step_type == "WaitStep"
    # A WaitStep has no input_mapping - wait_time sits on the step itself -
    # so its resolved inputs are legitimately empty.
    assert record.inputs == result.inputs == {}
    assert record.outputs == result.outputs
    assert record.duration_s >= 0.05
    assert record.started_at > 0


def test_the_rich_record_carries_the_resolved_inputs_and_outputs():
    events = []
    runtime = Runtime(emit=events.append)
    step = ReturnsDict(
        step_name="works",
        payload={"ok": True},
        input_mapping={"limit": {"type": "direct", "value": "9"}},
        output_mapping={"ok": {"type": "passfail"}},
    )

    step.run(runtime)

    record = events[-1]
    assert isinstance(record, StepExecuted)
    assert record.inputs == {"limit": "9"}
    assert record.outputs == {"ok": True}


def test_a_non_dict_return_is_wrapped_and_none_becomes_empty():
    wrapped = ReturnsDict(step_name="scalar", payload=42).run(Runtime())
    assert wrapped.outputs == {"output": 42}
    empty = ReturnsDict(step_name="nothing", payload=None).run(Runtime())
    assert empty.outputs == {}


def test_step_result_captures_errors_with_traceback():
    result = Raises(step_name="burns").run(Runtime())
    assert result.result is ResultType.ERROR
    assert "the hardware is on fire" in result.error_info
    assert "Traceback" in result.error_info


def test_a_skipped_step_is_not_executed():
    step = Raises(step_name="never", skip=True)
    result = step.run(Runtime())
    assert result.result is ResultType.SKIP
    assert result.error_info == ""


def test_a_step_outcome_is_the_pickle_safe_projection():
    result = ReturnsDict(step_name="works", payload=None).run(Runtime())
    outcome = result.to_outcome()
    assert outcome == StepOutcome(
        step_id=result.step.id, step_name="works", result=ResultType.DONE, error_info=""
    )


def test_steps_are_testable_standalone_with_a_fake_context():
    """"Tests executable stand-alone" is an explicit requirement in the spec."""
    step = WaitStep(step_name="pause", wait_time="0")
    result = step.run(Runtime())
    assert result.result is ResultType.DONE


def test_a_negative_wait_time_is_an_error():
    step = WaitStep(step_name="pause", wait_time="-1")
    result = step.run(Runtime())
    assert result.result is ResultType.ERROR


# --------------------------------------------------------------------------
# run_steps - the sequence-body policy
# --------------------------------------------------------------------------


def test_run_steps_runs_in_order():
    ran = []
    steps = [
        Notes(ran, step_name="one"),
        Notes(ran, step_name="two"),
        Notes(ran, step_name="three"),
    ]
    results = Step.run_steps(Runtime(), steps)
    assert ran == ["one", "two", "three"]
    assert len(results) == 3


def test_an_error_stops_the_remaining_steps():
    steps = [Raises(step_name="fails"), ReturnsDict(step_name="never", payload={})]
    results = Step.run_steps(Runtime(), steps)
    assert [r.result for r in results] == [ResultType.ERROR]


def test_a_stop_request_is_honoured_between_steps():
    ran = []
    stop_after_first = iter([False, True])
    runtime = Runtime(should_stop=lambda: next(stop_after_first))
    results = Step.run_steps(runtime, [Notes(ran, step_name="one"), Notes(ran, step_name="two")])
    assert ran == ["one"]
    assert len(results) == 1


def test_teardown_ignores_a_stop_request():
    """Teardown must run after an abort - it returns the bench to a known state."""
    ran = []
    runtime = Runtime(should_stop=lambda: True)
    Step.run_steps(runtime, [Notes(ran, step_name="cleanup")], honour_stop=False)
    assert ran == ["cleanup"]


# --------------------------------------------------------------------------
# run_sequence - one sequence, start to finish
# --------------------------------------------------------------------------


def test_run_sequence_reports_and_aggregates():
    events = []
    runtime = Runtime(emit=events.append)
    step = ReturnsDict(
        step_name="works", payload={"ok": True}, output_mapping={"ok": {"type": "passfail"}}
    )

    result, results = run_sequence(runtime, FakeSequence(steps=[step]))

    assert result is ResultType.PASS
    assert [r.result for r in results] == [ResultType.PASS]
    assert events[0] == SequenceStarted(sequence_name="Main")
    assert events[-1] == SequenceFinished(sequence_name="Main", result=ResultType.PASS)


def test_teardown_runs_even_when_a_step_errors():
    ran = []
    sequence = FakeSequence(
        steps=[Raises(step_name="fails")], teardown_steps=[Notes(ran, step_name="cleanup")]
    )
    result, results = run_sequence(Runtime(), sequence)

    assert ran == ["cleanup"]
    assert result is ResultType.ERROR
    assert len(results) == 2


def test_an_empty_sequence_aggregates_to_skip():
    """evaluate_multiple_step_results starts at SKIP - nothing ran, nothing passed."""
    result, results = run_sequence(Runtime(), FakeSequence())
    assert result is ResultType.SKIP
    assert results == []
    assert StepResult.evaluate_multiple_step_results([]) is ResultType.SKIP


def test_sequence_locals_do_not_leak_between_runs():
    """The old engine pushed the parsed dict by reference (F16) - a re-run saw
    the previous run's writes. run_sequence() pushes a copy."""
    sequence = FakeSequence(
        locals={"counter": 0},
        steps=[
            ReturnsDict(
                step_name="write",
                payload={"out": 1},
                output_mapping={"out": {"type": "local", "local_name": "counter"}},
            )
        ],
    )
    runtime = Runtime()
    run_sequence(runtime, sequence)
    assert sequence.locals == {"counter": 0}
    assert runtime.local_stack == []


# --------------------------------------------------------------------------
# PythonModuleStep - the minimal port: call one function, kwargs in, dict out
# --------------------------------------------------------------------------


def write_module(tmp_path, name="demo_tests.py"):
    module_file = tmp_path / name
    module_file.write_text(
        "def add(a, b):\n"
        "    return {'sum': a + b}\n"
        "\n"
        "def flag():\n"
        "    return True\n",
        encoding="utf-8",
    )
    return module_file


def test_python_module_step_calls_a_function_with_resolved_inputs(tmp_path):
    write_module(tmp_path)
    step = PythonModuleStep(
        step_name="add",
        module="demo_tests.py",
        method_name="add",
        input_mapping={"a": {"value": 2}, "b": {"value": 3}},
        output_mapping={"sum": {"type": "equals", "value": 5}},
    )
    result = step.run(Runtime(base_dir=str(tmp_path)))
    assert result.result is ResultType.PASS
    assert result.outputs == {"sum": 5}


def test_python_module_step_module_name_needs_no_py_suffix(tmp_path):
    """The old recipes spell both `example_tests` and `example_tests.py`."""
    write_module(tmp_path)
    step = PythonModuleStep(step_name="flag", module="demo_tests", method_name="flag")
    result = step.run(Runtime(base_dir=str(tmp_path)))
    assert result.result is ResultType.DONE
    assert result.outputs == {"output": True}


def test_python_module_step_imports_a_dotted_module_name():
    """No file by that name -> a plain import, so stdlib/installed code works."""
    step = PythonModuleStep(step_name="machine", module="platform", method_name="machine")
    result = step.run(Runtime())
    assert result.result is ResultType.DONE
    assert isinstance(result.outputs["output"], str)


def test_python_module_step_missing_module_is_a_step_error():
    step = PythonModuleStep(
        step_name="ghost", module="no_such_module_anywhere", method_name="f"
    )
    result = step.run(Runtime())
    assert result.result is ResultType.ERROR
    assert "no_such_module_anywhere" in result.error_info


def test_python_module_step_missing_function_is_a_step_error(tmp_path):
    write_module(tmp_path)
    step = PythonModuleStep(step_name="typo", module="demo_tests.py", method_name="addd")
    result = step.run(Runtime(base_dir=str(tmp_path)))
    assert result.result is ResultType.ERROR
    assert "addd" in result.error_info


def test_python_module_step_requires_a_method_name():
    with pytest.raises(ValueError, match="method_name"):
        PythonModuleStep(step_name="nameless", module="demo_tests.py")


def test_python_module_step_refuses_unported_action_types():
    with pytest.raises(ValueError, match="read_attribute"):
        PythonModuleStep(
            step_name="attr", module="m", method_name="f", action_type="read_attribute"
        )
