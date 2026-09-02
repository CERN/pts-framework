# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Step module (src/pypts/step/).

The layer under test is the execution unit: the base Step lifecycle
(resolve inputs -> _step() -> judge outputs -> StepResult), the Runtime it
runs against, the registry that replaced the old eval() factory, and the
ported step types. Everything here drives the code with a bare Runtime() -
no queues, no Sequencer, no threads - because "steps are testable
stand-alone" is a spec requirement, not a convenience. That extends to the
step type that blocks on a person: UserInteractionStep asks through
Runtime.ask, so a test hands it a callable that answers.
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
from pypts.step.step import (
    MAX_VALUE_CHARS,
    Step,
    StepResult,
    build_fail_reason,
    describe_failed_check,
    render_value,
    run_sequence,
)
from pypts.step.user_interaction_step import UserInteractionStep
from pypts.step.user_write_step import UserWriteStep
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

    def __init__(self, name="Main", steps=(), teardown_steps=()):
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
    the one source for what *runs*. They must name the same types, except the
    ones the parser expands away before anything is built."""
    from pypts.recipe.rules import EXPANDED_STEP_TYPES, STEP_TYPE_REQUIRED

    assert set(STEP_TYPE_REQUIRED) - set(EXPANDED_STEP_TYPES) == set(STEP_TYPES)


def test_an_expanded_steptype_never_reaches_the_registry():
    """An Indexed step is gone by build time: it becomes N ordinary steps, and
    nothing downstream may be able to build one."""
    from pypts.recipe.rules import EXPANDED_STEP_TYPES

    for steptype in EXPANDED_STEP_TYPES:
        assert steptype not in STEP_TYPES


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
    one.outputs["__result"] = {"type": "pass"}
    assert two.outputs == {}


# --------------------------------------------------------------------------
# process_inputs
# --------------------------------------------------------------------------


def test_inputs_resolve_literals_and_globals():
    runtime = Runtime(globals={"limit": 9, "target": 45})
    step = ReturnsDict(
        step_name="resolve",
        inputs={
            "value": "3",
            "target": {"type": "global", "global_name": "target"},
            "limit": {"type": "global", "global_name": "limit"},
        },
    )
    assert step.process_inputs(runtime) == {"value": "3", "target": 45, "limit": 9}


def test_a_mapping_input_without_a_type_is_refused():
    """There is no default and no `direct` type any more: a mapping is a
    configuration and says so, and a literal is written as itself. The old
    `{value: 3}` spelling is one of the two ways to get here."""
    step = ReturnsDict(step_name="untyped", inputs={"wait_time": {"value": "3"}})
    with pytest.raises(ValueError, match="written as itself"):
        step.process_inputs(Runtime())


def test_an_unknown_input_type_is_refused():
    """The old code silently left the raw config dict in place."""
    step = ReturnsDict(step_name="bad", inputs={"x": {"type": "telepathy"}})
    with pytest.raises(ValueError, match="telepathy"):
        step.process_inputs(Runtime())


# --------------------------------------------------------------------------
# process_outputs
# --------------------------------------------------------------------------


def judge(outputs, step_output, runtime=None):
    """Run one process_outputs() call with the least ceremony possible."""
    step = ReturnsDict(step_name="judge", outputs=outputs)
    return step.process_outputs(runtime if runtime is not None else Runtime(), step_output)


def test_an_empty_outputs_judges_done():
    assert judge({}, {}) is ResultType.DONE


def test_passfail_equals_and_range_verdicts():
    assert judge({"ok": {"type": "passfail"}}, {"ok": True}) is ResultType.PASS
    assert judge({"ok": {"type": "passfail"}}, {"ok": False}) is ResultType.FAIL
    assert judge({"v": {"type": "equals", "value": "yes"}}, {"v": "yes"}) is ResultType.PASS
    assert judge({"v": {"type": "equals", "value": "yes"}}, {"v": "no"}) is ResultType.FAIL
    assert judge({"v": {"type": "range", "min": "10", "max": "20"}}, {"v": "15"}) is ResultType.PASS
    assert judge({"v": {"type": "range", "min": "10", "max": "20"}}, {"v": "25"}) is ResultType.FAIL


def test_pass_is_done_whatever_came_back():
    """`pass` says this output is not a measurement. It replaced
    `passthrough`, which propagated a ResultType the step returned - a shape
    only the dropped structural step types ever produced."""
    assert judge({"r": {"type": "pass"}}, {"r": ResultType.FAIL}) is ResultType.DONE
    assert judge({"r": {"type": "pass"}}, {"r": "anything at all"}) is ResultType.DONE


def test_a_global_entry_stores_without_judging():
    runtime = Runtime(globals={})
    mapping = {"b": {"type": "global", "global_name": "kept_global"}}
    assert judge(mapping, {"b": 2}, runtime) is ResultType.DONE
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
# Why a step says FAIL
# --------------------------------------------------------------------------


def test_a_failed_check_says_what_was_measured_and_what_was_expected():
    """The three judging types each explain themselves in the operator's words."""
    assert describe_failed_check(
        "voltage", {"type": "range", "min": "4.9", "max": "5.1"}, 4.2
    ) == "voltage = 4.2, expected between 4.9 and 5.1"
    assert describe_failed_check("led_on", {"type": "passfail"}, False) == (
        "led_on = False, expected a pass"
    )
    assert describe_failed_check(
        "serial", {"type": "equals", "value": "XYZ"}, "ABC"
    ) == "serial = 'ABC', expected 'XYZ'"


def test_a_string_value_is_quoted_so_whitespace_is_visible():
    """'ABC ' and 'ABC' are a support call apart; unquoted they look identical."""
    assert render_value("ABC ") == "'ABC '"
    assert render_value("") == "''"
    assert render_value(4.2) == "4.2"


def test_a_huge_value_is_truncated():
    """A step may return 40 kB. The log, a tooltip and a CSV cell are not
    improved by carrying it."""
    rendered = render_value("x" * 500)
    assert len(rendered) == MAX_VALUE_CHARS
    assert rendered.endswith("...")


def test_the_reason_carries_the_failing_check_then_the_inputs_and_outputs():
    reason = build_fail_reason(
        ["voltage = 4.2, expected between 4.9 and 5.1"],
        {"channel": 1},
        {"voltage": 4.2, "temperature": 31.5},
    )
    assert reason == (
        "voltage = 4.2, expected between 4.9 and 5.1; "
        "inputs: channel = 1; "
        "outputs: voltage = 4.2, temperature = 31.5."
    )


def test_a_step_with_no_inputs_says_nothing_about_them():
    reason = build_fail_reason(["v = 1, expected a pass"], {}, {"v": 1})
    assert reason == "v = 1, expected a pass; outputs: v = 1."


def test_a_failing_step_records_the_reason_on_its_result():
    """End to end through run(): the reason is on error_info, so it reaches the
    step table's tooltip, the CLI's step line and the report's CSV as well as
    the log."""
    step = ReturnsDict(
        step_name="read_voltage",
        payload={"voltage": 4.2},
        inputs={"channel": 1},
        outputs={"voltage": {"type": "range", "min": "4.9", "max": "5.1"}},
    )

    result = step.run(Runtime())

    assert result.result is ResultType.FAIL
    assert result.error_info == (
        "voltage = 4.2, expected between 4.9 and 5.1; "
        "inputs: channel = 1; outputs: voltage = 4.2."
    )
    # to_outcome() is the projection the frontend and the Report receive.
    assert result.to_outcome().error_info == result.error_info


def test_a_passing_step_records_no_reason():
    """A reason beside a PASS would contradict it."""
    step = ReturnsDict(
        step_name="ok", payload={"v": 5.0},
        outputs={"v": {"type": "range", "min": "4.9", "max": "5.1"}},
    )

    result = step.run(Runtime())

    assert result.result is ResultType.PASS
    assert result.error_info == ""


def test_last_wins_leaves_no_reason_beside_a_pass():
    """F6 is unchanged: a fail-then-pass mapping still reports PASS. The point
    here is that it does not report PASS with a failure written beside it."""
    step = ReturnsDict(
        step_name="mixed",
        payload={"first": False, "second": True},
        outputs={"first": {"type": "passfail"}, "second": {"type": "passfail"}},
    )

    result = step.run(Runtime())

    assert result.result is ResultType.PASS
    assert result.error_info == ""


def test_process_outputs_collects_every_failing_check():
    """The out-parameter describes them all, even the ones last-wins overrode."""
    failures = []
    step = ReturnsDict(
        step_name="mixed",
        outputs={"first": {"type": "passfail"}, "second": {"type": "passfail"}},
    )

    verdict = step.process_outputs(Runtime(), {"first": False, "second": True}, failures)

    assert verdict is ResultType.PASS
    assert failures == ["first = False, expected a pass"]


# --------------------------------------------------------------------------
# The run() lifecycle
# --------------------------------------------------------------------------


def test_a_step_run_produces_a_result_and_both_events():
    events = []
    runtime = Runtime(emit=events.append)
    step = ReturnsDict(
        step_name="works", payload={"ok": True}, outputs={"ok": {"type": "passfail"}}
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
    # A WaitStep has no inputs - wait_time sits on the step itself -
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
        inputs={"limit": "9"},
        outputs={"ok": {"type": "passfail"}},
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


def fails(step_name="fails", **kwargs):
    """A step that comes back FAIL - a failed measurement, not an exception."""
    return ReturnsDict(
        step_name=step_name,
        payload={"ok": False},
        outputs={"ok": {"type": "passfail"}},
        **kwargs,
    )


def test_an_error_does_not_stop_the_remaining_steps():
    """The continue_on_error: True default (step.md 3.1): one bad step is
    recorded and the sequence carries on, rather than deciding for the rest."""
    steps = [Raises(step_name="fails"), ReturnsDict(step_name="runs anyway", payload={})]
    results = Step.run_steps(Runtime(), steps)
    assert [r.result for r in results] == [ResultType.ERROR, ResultType.DONE]


def test_a_fail_does_not_stop_the_remaining_steps_either():
    """A failed measurement never halts anything by itself - a failing DUT is
    still fully characterised. Only continue_on_error: false changes that."""
    ran = []
    results = Step.run_steps(Runtime(), [fails(), Notes(ran, step_name="two")])
    assert ran == ["two"]
    assert [r.result for r in results] == [ResultType.FAIL, ResultType.DONE]


def test_continue_on_error_false_halts_the_run_on_an_error():
    """"Except this one": the step says so, and the sequence ends there."""
    ran = []
    steps = [
        Raises(step_name="critical", continue_on_error=False),
        Notes(ran, step_name="two"),
        Notes(ran, step_name="three"),
    ]
    results = Step.run_steps(Runtime(), steps)

    assert ran == []
    assert [r.result for r in results] == [ResultType.ERROR, ResultType.SKIP, ResultType.SKIP]


def test_continue_on_error_false_halts_the_run_on_a_fail_too():
    """The decision this change took on F7: with the flag off, either verdict
    halts. The old engine stopped on ERROR only."""
    ran = []
    steps = [fails(step_name="critical", continue_on_error=False), Notes(ran, step_name="two")]
    results = Step.run_steps(Runtime(), steps)

    assert ran == []
    assert [r.result for r in results] == [ResultType.FAIL, ResultType.SKIP]


def test_a_halted_run_says_why_every_remaining_step_was_skipped():
    """The reason rides on the StepOutcome, so the operator reads it in the
    step table's tooltip and in the CSV instead of wondering."""
    steps = [Raises(step_name="critical", continue_on_error=False), Notes([], step_name="two")]
    results = Step.run_steps(Runtime(), steps)
    assert "stopped at step 'critical'" in results[1].error_info


def test_continue_on_error_false_halts_nothing_when_the_step_is_fine():
    """The flag is about ERROR and FAIL. A PASS, a DONE and an author-written
    skip: true all carry on."""
    ran = []
    steps = [
        ReturnsDict(
            step_name="passes",
            payload={"ok": True},
            outputs={"ok": {"type": "passfail"}},
            continue_on_error=False,
        ),
        ReturnsDict(step_name="done", payload={}, continue_on_error=False),
        Notes(ran, step_name="skipped", skip=True, continue_on_error=False),
        Notes(ran, step_name="last"),
    ]
    results = Step.run_steps(Runtime(), steps)

    assert ran == ["last"]
    assert [r.result for r in results] == [
        ResultType.PASS,
        ResultType.DONE,
        ResultType.SKIP,
        ResultType.DONE,
    ]


def test_a_stop_still_ends_a_run_even_though_an_error_does_not():
    """The two are separate branches: continuing past ERROR must not make the
    loop deaf to the operator's Stop. The unrun step is recorded, not dropped."""
    ran = []
    stop_after_first = iter([False, True])
    runtime = Runtime(should_stop=lambda: next(stop_after_first))
    results = Step.run_steps(runtime, [Raises(step_name="fails"), Notes(ran, step_name="two")])
    assert ran == []
    assert [r.result for r in results] == [ResultType.ERROR, ResultType.SKIP]


def test_a_stop_request_is_honoured_between_steps():
    ran = []
    stop_after_first = iter([False, True])
    runtime = Runtime(should_stop=lambda: next(stop_after_first))
    results = Step.run_steps(runtime, [Notes(ran, step_name="one"), Notes(ran, step_name="two")])
    assert ran == ["one"]
    assert [r.result for r in results] == [ResultType.DONE, ResultType.SKIP]
    assert "stopped by the operator" in results[1].error_info


def test_every_step_settles_a_row_however_the_list_ended():
    """The point of recording the remainder rather than dropping it: a frontend
    pre-fills one row per step, so every step must emit its events or a row
    stays pending forever."""
    events = []
    runtime = Runtime(emit=events.append)
    steps = [Raises(step_name="critical", continue_on_error=False), Notes([], step_name="two")]
    Step.run_steps(runtime, steps)

    finished = [event for event in events if isinstance(event, StepFinished)]
    assert [event.outcome.step_name for event in finished] == ["critical", "two"]
    assert [event.outcome.result for event in finished] == [ResultType.ERROR, ResultType.SKIP]


def test_teardown_ignores_a_stop_request():
    """Teardown must run after an abort - it returns the bench to a known state."""
    ran = []
    runtime = Runtime(should_stop=lambda: True)
    Step.run_steps(runtime, [Notes(ran, step_name="cleanup")], run_to_end=True)
    assert ran == ["cleanup"]


def test_teardown_ignores_continue_on_error_too():
    """One failing cleanup step must not skip the rest of the cleanup - that is
    the opposite of what teardown is for."""
    ran = []
    steps = [
        Raises(step_name="bad cleanup", continue_on_error=False),
        Notes(ran, step_name="cleanup"),
    ]
    results = Step.run_steps(Runtime(), steps, run_to_end=True)
    assert ran == ["cleanup"]
    assert [r.result for r in results] == [ResultType.ERROR, ResultType.DONE]


# --------------------------------------------------------------------------
# run_sequence - one sequence, start to finish
# --------------------------------------------------------------------------


def test_run_sequence_reports_and_aggregates():
    events = []
    runtime = Runtime(emit=events.append)
    step = ReturnsDict(
        step_name="works", payload={"ok": True}, outputs={"ok": {"type": "passfail"}}
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


def test_teardown_runs_after_a_step_halts_the_run():
    """A halt ends the *steps*, never the cleanup: teardown is the only block
    guaranteed to run, exactly as it is after an operator Stop."""
    ran = []
    sequence = FakeSequence(
        steps=[
            Raises(step_name="critical", continue_on_error=False),
            Notes(ran, step_name="never"),
        ],
        teardown_steps=[Notes(ran, step_name="cleanup")],
    )
    result, results = run_sequence(Runtime(), sequence)

    assert ran == ["cleanup"]
    assert result is ResultType.ERROR
    assert [r.result for r in results] == [ResultType.ERROR, ResultType.SKIP, ResultType.DONE]


def test_an_empty_sequence_aggregates_to_skip():
    """evaluate_multiple_step_results starts at SKIP - nothing ran, nothing passed."""
    result, results = run_sequence(Runtime(), FakeSequence())
    assert result is ResultType.SKIP
    assert results == []
    assert StepResult.evaluate_multiple_step_results([]) is ResultType.SKIP


def test_a_sequence_writes_the_runs_globals_and_nothing_else():
    """There is one scope. A step storing a value writes the run's globals,
    which outlive the sequence on purpose - the per-sequence frame that used
    to exist was dropped."""
    sequence = FakeSequence(
        steps=[
            ReturnsDict(
                step_name="write",
                payload={"out": 1},
                outputs={"out": {"type": "global", "global_name": "counter"}},
            )
        ],
    )
    runtime = Runtime()
    run_sequence(runtime, sequence)
    assert runtime.globals == {"counter": 1}
    assert not hasattr(runtime, "local_stack")


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
        inputs={"a": 2, "b": 3},
        outputs={"sum": {"type": "equals", "value": 5}},
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


def test_action_type_is_not_a_key_at_all():
    """Dropped outright (2026-09-02), not tolerated: the type calls methods and
    nothing else, so the key that used to select between three actions is now
    an unknown key like any other - a TypeError the recipe layer names."""
    with pytest.raises(TypeError, match="action_type"):
        PythonModuleStep(step_name="old", module="m", method_name="f", action_type="method")


# --------------------------------------------------------------------------
# The indexed step - expanded at load time, one ordinary step per set
# --------------------------------------------------------------------------


def an_indexed_step(**overrides):
    """The shape pythonmodulestep_demo.yml uses, as the parser hands it over."""
    step_data = {
        "steptype": "indexed",
        "step_name": "Add numbers",
        "description": "Ten additions.",
        "template": {
            "steptype": "PythonModule",
            "module": "example_tests.py",
            "method_name": "add",
        },
        "parameter_sets": [
            {"inputs": {"a": 1, "b": 1}, "expect": {"sum": 2}},
            {"inputs": {"a": 2, "b": 3}, "expect": {"sum": 5}},
        ],
    }
    step_data.update(overrides)
    return step_data


def test_an_indexed_step_becomes_one_ordinary_step_per_set():
    """The whole point: N sets in, N plain step mappings out."""
    from pypts.step.indexed_step import expand_indexed_step

    expanded = expand_indexed_step(an_indexed_step())

    assert len(expanded) == 2
    for generated in expanded:
        assert generated["steptype"] == "PythonModule"
        assert generated["method_name"] == "add"
        # Nothing of the indexed step itself survives into what runs.
        assert "template" not in generated
        assert "parameter_sets" not in generated


def test_a_set_parameterizes_the_inputs_and_the_expected_outputs():
    """Both halves: `inputs` are direct values, `expect` are equals checks."""
    from pypts.step.indexed_step import expand_indexed_step

    first, second = expand_indexed_step(an_indexed_step())

    # A set's inputs are direct values, and a direct value is written as
    # itself - the generated step reads as a hand-written one would.
    assert first["inputs"] == {"a": 1, "b": 1}
    assert first["outputs"] == {"sum": {"type": "equals", "value": 2}}
    assert second["outputs"] == {"sum": {"type": "equals", "value": 5}}


def test_generated_steps_are_named_after_their_parameters():
    """A failed row has to explain itself without opening the recipe."""
    from pypts.step.indexed_step import expand_indexed_step

    names = [generated["step_name"] for generated in expand_indexed_step(an_indexed_step())]

    assert names == ["Add numbers [a=1, b=1]", "Add numbers [a=2, b=3]"]


def test_a_set_without_inputs_falls_back_to_its_position():
    """A set that varies only the expectation has no parameters to show."""
    from pypts.step.indexed_step import expand_indexed_step

    step_data = an_indexed_step(
        template={"steptype": "PythonModule", "module": "m.py", "method_name": "f"},
        parameter_sets=[{"expect": {"out": 1}}, {"expect": {"out": 2}}],
    )

    names = [generated["step_name"] for generated in expand_indexed_step(step_data)]

    assert names == ["Add numbers 1/2", "Add numbers 2/2"]


def test_a_set_is_merged_over_what_the_template_shares():
    """The template holds what every case shares; a set says what differs."""
    from pypts.step.indexed_step import expand_indexed_step

    step_data = an_indexed_step(
        template={
            "steptype": "PythonModule",
            "module": "example_tests.py",
            "method_name": "add",
            "inputs": {
                "a": 999,
                "shared": {"type": "global", "global_name": "rig"},
            },
        },
        parameter_sets=[{"inputs": {"a": 1}, "expect": {"sum": 2}}],
    )

    generated = expand_indexed_step(step_data)[0]

    # The set wins where they collide, the template survives where they do not.
    assert generated["inputs"]["a"] == 1
    assert generated["inputs"]["shared"] == {"type": "global", "global_name": "rig"}


def test_the_group_description_is_inherited_when_the_template_has_none():
    from pypts.step.indexed_step import expand_indexed_step

    generated = expand_indexed_step(an_indexed_step())[0]

    assert generated["description"] == "Ten additions."


def test_skipping_an_indexed_step_skips_every_generated_step():
    from pypts.step.indexed_step import expand_indexed_step

    expanded = expand_indexed_step(an_indexed_step(skip=True))

    assert [generated["skip"] for generated in expanded] == [True, True]


def test_an_indexed_step_may_not_carry_an_id():
    """One id would be handed to N steps, and the step table is keyed by id."""
    from pypts.step.indexed_step import check_indexed_step

    problems = check_indexed_step(an_indexed_step(id="12345678-1234-5678-1234-567812345678"))

    assert any("'id'" in problem for problem in problems)


def test_mappings_on_the_indexed_step_itself_are_refused():
    """They would apply to nothing; silently ignoring them would be worse."""
    from pypts.step.indexed_step import check_indexed_step

    problems = check_indexed_step(an_indexed_step(inputs={"a": {"value": 1}}))

    assert any("template" in problem for problem in problems)


def test_an_empty_or_malformed_set_list_is_refused():
    from pypts.step.indexed_step import check_indexed_step

    assert check_indexed_step(an_indexed_step(parameter_sets=[]))
    assert check_indexed_step(an_indexed_step(parameter_sets="not a list"))
    assert check_indexed_step(an_indexed_step(parameter_sets=[{}]))


def test_an_unknown_key_in_a_set_names_what_would_have_worked():
    from pypts.step.indexed_step import check_indexed_step

    problems = check_indexed_step(
        an_indexed_step(parameter_sets=[{"inputs": {"a": 1}, "outputs": {"sum": 2}}])
    )

    assert any("outputs" in problem and "inputs, expect" in problem for problem in problems)


def test_an_indexed_step_cannot_be_the_template_of_another():
    from pypts.step.indexed_step import check_indexed_step

    problems = check_indexed_step(an_indexed_step(template=an_indexed_step()))

    assert any("template" in problem for problem in problems)


def test_expanding_a_broken_indexed_step_raises_rather_than_guessing():
    """The parser validates first; this is the guard for a caller that did not."""
    from pypts.step.indexed_step import expand_indexed_step

    with pytest.raises(ValueError):
        expand_indexed_step(an_indexed_step(parameter_sets=[]))


# --------------------------------------------------------------------------
# UserInteractionStep - the first type that blocks on a person
# --------------------------------------------------------------------------


def make_asker(answer, seen=None):
    """A fake Runtime.ask: records the request it was given, returns `answer`."""

    def ask(request):
        if seen is not None:
            seen.append(request)
        return answer

    return ask


def test_user_interaction_step_asks_and_returns_the_choice():
    seen = []
    step = UserInteractionStep(
        step_name="Check the LED",
        message="Is the red LED lit?",
        options=["Yes", "No"],
        outputs={"output": {"type": "equals", "value": "Yes"}},
    )
    result = step.run(Runtime(ask=make_asker("Yes", seen)))

    assert result.result is ResultType.PASS
    assert result.outputs == {"output": "Yes"}
    assert len(seen) == 1
    assert seen[0].message == "Is the red LED lit?"
    assert seen[0].options == ("Yes", "No")
    assert seen[0].image_path is None


def test_user_interaction_step_stores_the_choice_in_a_global():
    """The answer goes through the ordinary mapping vocabulary, not machinery
    of its own."""
    step = UserInteractionStep(
        step_name="Which port?",
        message="Which port is it on?",
        options=["COM1", "COM2"],
        outputs={"output": {"type": "global", "global_name": "port"}},
    )
    runtime = Runtime(ask=make_asker("COM2"))
    step.run(runtime)
    assert runtime.get_global("port") == "COM2"


def test_user_interaction_step_coerces_non_string_options():
    """`options: [1, 2]` is legal YAML; the message carries strings."""
    seen = []
    step = UserInteractionStep(step_name="pick", message="Pick", options=[1, 2])
    step.run(Runtime(ask=make_asker("1", seen)))
    assert seen[0].options == ("1", "2")


def test_user_interaction_step_refuses_a_prompt_with_no_buttons():
    """With no buttons the operator cannot answer, so it could only time out."""
    with pytest.raises(ValueError, match="at least one button"):
        UserInteractionStep(step_name="unanswerable", message="Well?", options=[])


def test_user_interaction_step_no_answer_is_a_step_error():
    """Timed out or cancelled - one rule, no special cases."""
    step = UserInteractionStep(step_name="ignored", message="Well?", options=["ok"])
    result = step.run(Runtime(ask=make_asker(None)))
    assert result.result is ResultType.ERROR
    assert "cancelled" in result.error_info


def test_user_interaction_step_says_so_when_the_run_was_stopped():
    """Same ERROR verdict, but the text has to be true."""
    step = UserInteractionStep(step_name="aborted", message="Well?", options=["ok"])
    runtime = Runtime(ask=make_asker(None), should_stop=lambda: True)
    result = step.run(runtime)
    assert result.result is ResultType.ERROR
    assert "stopped" in result.error_info


def test_user_interaction_step_declines_when_nothing_can_ask():
    """A bare Runtime has no engine behind it, so ask() returns None."""
    step = UserInteractionStep(step_name="alone", message="Well?", options=["ok"])
    assert step.run(Runtime()).result is ResultType.ERROR


def test_user_interaction_step_resolves_the_image_beside_the_recipe(tmp_path):
    """Absolute, because the HMI is another process and resolves nothing."""
    image = tmp_path / "led.png"
    image.write_bytes(b"not really a png")
    seen = []
    step = UserInteractionStep(
        step_name="Check the LED",
        message="Lit?",
        options=["Yes"],
        image_path="led.png",
    )
    step.run(Runtime(ask=make_asker("Yes", seen), base_dir=str(tmp_path)))
    assert seen[0].image_path == str(image.resolve())


def test_user_interaction_step_missing_image_is_a_step_error(tmp_path):
    """The GUI would silently fall back to the logo, so the step refuses first."""
    seen = []
    step = UserInteractionStep(
        step_name="Check the LED",
        message="Lit?",
        options=["Yes"],
        image_path="no_such_image.png",
    )
    result = step.run(Runtime(ask=make_asker("Yes", seen), base_dir=str(tmp_path)))
    assert result.result is ResultType.ERROR
    assert "no_such_image.png" in result.error_info
    assert seen == [], "nothing should be asked when the image is wrong"


def test_the_registry_builds_a_user_interaction_step():
    step = build_step(
        {
            "steptype": "UserInteraction",
            "step_name": "Check the LED",
            "message": "Lit?",
            "options": ["Yes", "No"],
        }
    )
    assert isinstance(step, UserInteractionStep)
    assert step.options == ("Yes", "No")


# --------------------------------------------------------------------------
# UserWriteStep - the free-text half of the pair
# --------------------------------------------------------------------------


def test_user_write_step_asks_and_returns_the_text():
    seen = []
    step = UserWriteStep(
        step_name="get_serial_number",
        message="Type the serial number",
    )
    result = step.run(Runtime(ask=make_asker("SN-0042", seen)))

    assert result.result is ResultType.DONE
    assert result.outputs == {"output": "SN-0042"}
    assert len(seen) == 1
    assert seen[0].message == "Type the serial number"
    assert seen[0].image_path is None


def test_user_write_step_stores_the_text_in_a_global():
    """The convention the best-practices guide documents: the answer is a global.

    This is also the behaviour the old UserWriteStep got wrong - it overwrote
    the typed text with the literal "wrt" (recipe_guide F14).
    """
    step = UserWriteStep(
        step_name="get_serial_number",
        message="Type the serial number",
        outputs={"output": {"type": "global", "global_name": "serial_number"}},
    )
    runtime = Runtime(ask=make_asker("SN-0042"))
    step.run(runtime)
    assert runtime.get_global("serial_number") == "SN-0042"


def test_user_write_step_judges_the_text_when_the_recipe_asks_it_to():
    step = UserWriteStep(
        step_name="confirm",
        message="Type CONFIRM",
        outputs={"output": {"type": "equals", "value": "CONFIRM"}},
    )
    assert step.run(Runtime(ask=make_asker("CONFIRM"))).result is ResultType.PASS
    assert step.run(Runtime(ask=make_asker("nope"))).result is ResultType.FAIL


def test_user_write_step_no_answer_is_a_step_error():
    """Same one rule as UserInteraction - both go through ask_or_raise."""
    step = UserWriteStep(step_name="ignored", message="Type something")
    result = step.run(Runtime(ask=make_asker(None)))
    assert result.result is ResultType.ERROR
    assert "cancelled" in result.error_info


def test_user_write_step_says_so_when_the_run_was_stopped():
    step = UserWriteStep(step_name="aborted", message="Type something")
    runtime = Runtime(ask=make_asker(None), should_stop=lambda: True)
    result = step.run(runtime)
    assert result.result is ResultType.ERROR
    assert "stopped" in result.error_info


def test_user_write_step_declines_when_nothing_can_ask():
    step = UserWriteStep(step_name="alone", message="Type something")
    assert step.run(Runtime()).result is ResultType.ERROR


def test_user_write_step_resolves_the_image_beside_the_recipe(tmp_path):
    image = tmp_path / "label.png"
    image.write_bytes(b"not really a png")
    seen = []
    step = UserWriteStep(
        step_name="get_serial_number",
        message="Type what is on the label",
        image_path="label.png",
    )
    step.run(Runtime(ask=make_asker("SN-1", seen), base_dir=str(tmp_path)))
    assert seen[0].image_path == str(image.resolve())


def test_user_write_step_missing_image_is_a_step_error(tmp_path):
    seen = []
    step = UserWriteStep(
        step_name="get_serial_number",
        message="Type what is on the label",
        image_path="no_such_image.png",
    )
    result = step.run(Runtime(ask=make_asker("SN-1", seen), base_dir=str(tmp_path)))
    assert result.result is ResultType.ERROR
    assert "no_such_image.png" in result.error_info
    assert seen == [], "nothing should be asked when the image is wrong"


def test_the_registry_builds_a_user_write_step():
    step = build_step(
        {
            "steptype": "UserWrite",
            "step_name": "get_serial_number",
            "message": "Type the serial number",
        }
    )
    assert isinstance(step, UserWriteStep)
    assert step.message == "Type the serial number"


# --------------------------------------------------------------------------
# `inputs` - a bare value is the value
# --------------------------------------------------------------------------


def test_a_bare_input_value_is_the_value():
    """`a: 2` is the spelling for a literal, which is what most arguments are."""
    step = Step(step_name="literals", inputs={"a": 2, "b": "COM3", "c": [1, 2]})

    assert step.process_inputs(Runtime()) == {"a": 2, "b": "COM3", "c": [1, 2]}


def test_a_literal_is_the_only_way_to_write_a_literal():
    """`{value: 2}` and `{type: direct, value: 2}` were a second spelling of
    `a: 2` and are both gone: a mapping is a configuration, and the only
    configuration an input has is `global`."""
    step = Step(step_name="explicit", inputs={"a": {"value": 2}})

    with pytest.raises(ValueError, match="unknown input type"):
        step.process_inputs(Runtime())


def test_a_mapping_input_still_names_where_its_value_comes_from():
    runtime = Runtime(globals={"rig": "bench-2", "port": "COM1"})
    step = Step(
        step_name="mixed",
        inputs={
            "literal": 45,
            "from_global": {"type": "global", "global_name": "rig"},
            "also_global": {"type": "global", "global_name": "port"},
        },
    )

    assert step.process_inputs(runtime) == {
        "literal": 45,
        "from_global": "bench-2",
        "also_global": "COM1",
    }


def test_a_mapping_that_configures_nothing_says_so():
    """The cost of the short spelling: a mapping is always a configuration, so
    an argument whose value is genuinely a dict cannot be written directly.
    The error says so instead of failing obscurely."""
    step = Step(step_name="ambiguous", inputs={"payload": {"foo": 1}})

    with pytest.raises(ValueError, match="written as itself"):
        step.process_inputs(Runtime())


# --------------------------------------------------------------------------
# What is NOT checked when the recipe loads - all of it fails on the bench
# --------------------------------------------------------------------------


def test_an_argument_name_the_function_does_not_take_is_a_step_error(tmp_path):
    """The recipe names the arguments and nothing compares them with the
    signature, so a typo is a TypeError from the call itself. Checking it at
    load time is a roadmap TODO; this pins what happens until then."""
    write_module(tmp_path)
    step = PythonModuleStep(
        step_name="typo",
        module="demo_tests.py",
        method_name="add",
        inputs={"a": 1, "bb": 2},
    )

    result = step.run(Runtime(base_dir=str(tmp_path)))

    assert result.result is ResultType.ERROR
    assert "bb" in result.error_info


def test_too_few_arguments_is_a_step_error(tmp_path):
    """Same story from the other side: the call is what notices."""
    write_module(tmp_path)
    step = PythonModuleStep(
        step_name="short", module="demo_tests.py", method_name="add", inputs={"a": 1}
    )

    result = step.run(Runtime(base_dir=str(tmp_path)))

    assert result.result is ResultType.ERROR
    assert "add()" in result.error_info


def test_a_global_that_was_never_set_is_a_step_error():
    """A typo in `global_name` fails mid-run, not at load time. Making an
    undeclared variable a validation fault is a roadmap TODO (guide P4)."""
    step = Step(step_name="ghost", inputs={"x": {"type": "global", "global_name": "nope"}})

    result = step.run(Runtime())

    assert result.result is ResultType.ERROR
    assert "nope" in result.error_info
