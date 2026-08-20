# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The base Step, its StepResult, and the two loops that run steps.

The lifecycle every step shares, owned by the base class and ported from
old_code/recipe.py:

    resolve inputs  ->  _step()  ->  judge outputs  ->  StepResult

A subclass overrides `_step()` and nothing else. `run()` turns whatever
happens in there - a return value, an exception - into a StepResult, and
emits StepStarted/StepFinished through the Runtime as it goes, so a nested
sequence (a future SequenceStep) reports through the same channel it
already holds.

This layer is `@report_and_reraise()` territory in spirit: a step failure
must become data (`StepResult` with ResultType.ERROR and the traceback),
never a silent continue. `run()` is the one place that catches broadly,
because turning the exception into a result *is* its job.

Deliberately absent, recorded in the roadmap: the continue_on_error policy
(the old engine had three disagreeing sources of truth for it - F8), the
`method` input type (returns with PythonModuleStep), and per-step `critical`
handling (parsed and stored, not yet consulted).
"""

import time
import traceback
import uuid
from typing import TYPE_CHECKING, Any

from pypts.messages.common_messages import ResultType, StepOutcome
from pypts.messages.run_events import (
    SequenceFinished,
    SequenceStarted,
    StepExecuted,
    StepFinished,
    StepStarted,
)
from pypts.step.runtime import Runtime

if TYPE_CHECKING:
    from pypts.recipe.recipe import Sequence


class StepResult:
    """
    What one step execution produced: verdict, data, and the error if any.

    This is the rich, engine-internal object - it holds the live Step and
    must never cross the HMI process boundary. `to_outcome()` is the
    pickle-safe projection that does.

    `subresults` is kept for the nesting that SequenceStep and IndexedStep
    bring later; nothing writes it yet.
    """

    def __init__(self, step: "Step") -> None:
        self.step = step
        self.result: ResultType | None = None
        self.inputs: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {}
        self.error_info: str = ""
        self.uuid: uuid.UUID = uuid.uuid4()
        self.subresults: list[StepResult] = []

    def set_result(
        self, result_type: ResultType, inputs: dict[str, Any], outputs: dict[str, Any]
    ) -> None:
        """Normal completion: the judged verdict plus what went in and came out."""
        self.result = result_type
        self.inputs = inputs
        self.outputs = outputs

    def set_error(self, error_info: str, inputs: dict[str, Any]) -> None:
        """The step raised: verdict ERROR, keep the traceback text."""
        self.result = ResultType.ERROR
        self.error_info = error_info
        self.inputs = inputs

    def set_skip(self) -> None:
        self.result = ResultType.SKIP

    def set_stop(self, reason: str = "Stopped by user") -> None:
        self.result = ResultType.STOP
        self.error_info = reason

    def to_outcome(self) -> StepOutcome:
        """The pickle-safe projection a frontend receives."""
        result = self.result if self.result is not None else ResultType.ERROR
        return StepOutcome(
            step_id=self.step.id,
            step_name=self.step.name,
            result=result,
            error_info=self.error_info,
        )

    @staticmethod
    def evaluate_multiple_step_results(step_results: list["StepResult"]) -> ResultType:
        """A group aggregates to its highest member; nothing ran means SKIP."""
        aggregate = ResultType.SKIP
        for step_result in step_results:
            if step_result.result is not None and step_result.result > aggregate:
                aggregate = step_result.result
        return aggregate


class Step:
    """
    One unit of work in a sequence.

    The constructor arguments are exactly the step's common YAML keys - a
    recipe's step mapping is splatted into it by the registry, so an unknown
    key is a TypeError at load time, not a surprise at run time.
    """

    def __init__(
        self,
        step_name: str,
        id: str = "",
        description: str = "",
        input_mapping: dict[str, Any] | None = None,
        output_mapping: dict[str, Any] | None = None,
        skip: bool = False,
        critical: bool = False,
    ) -> None:
        self.name = step_name
        self.description = description
        # A fresh dict per instance. The old base used mutable defaults, so
        # every step that omitted a mapping shared one dict (F12).
        self.input_mapping: dict[str, Any] = dict(input_mapping) if input_mapping else {}
        self.output_mapping: dict[str, Any] = dict(output_mapping) if output_mapping else {}
        self.skip = skip
        self.critical = critical
        # The typed events (StepStarted.step_id: UUID) force a real UUID here.
        # The old code accepted any string; a stable-string-id policy is a
        # recorded roadmap TODO for when the Report and the Creator need one.
        self.id: uuid.UUID = uuid.UUID(id) if id else uuid.uuid4()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    # --- the extension point ---------------------------------------------------

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        """
        Do the work. Overridden by every step type; the base has no work.

        Returns the step's raw output: a dict judged key by key against the
        output_mapping, or any other value (wrapped as {"output": value};
        None becomes {}). Raise to fail the step - run() turns the exception
        into a StepResult with ResultType.ERROR.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement _step()")

    # --- input resolution ------------------------------------------------------

    def process_inputs(self, runtime: Runtime) -> dict[str, Any]:
        """
        Resolve the input_mapping into the dict of values _step() receives.

        Each entry names where its value comes from: `direct` (a literal in
        the recipe - the default when `type` is absent), `local` or `global`.
        There is no type coercion anywhere: '45' stays a string, 45 an int.
        """
        resolved: dict[str, Any] = {}
        for input_name, input_config in self.input_mapping.items():
            input_type = input_config.get("type", "direct")
            match input_type:
                case "direct":
                    resolved[input_name] = input_config["value"]
                case "local":
                    resolved[input_name] = runtime.get_local(input_config["local_name"])
                case "global":
                    resolved[input_name] = runtime.get_global(input_config["global_name"])
                case _:
                    # The old code left the raw config dict in place. A typo'd
                    # type must be an ERROR on this step, not a weird argument.
                    raise ValueError(
                        f"Step '{self.name}': unknown input type {input_type!r} "
                        f"for input '{input_name}'"
                    )
        return resolved

    # --- output judging and storing --------------------------------------------

    def process_outputs(self, runtime: Runtime, step_output: dict[str, Any]) -> ResultType:
        """
        Judge and store the step's outputs; return the verdict.

        Judging entries (`passthrough`, `passfail`, `equals`, `range`) assign
        the verdict; storing entries (`local`, `global`) write a variable and
        leave it alone. With no judging entry at all the verdict is DONE.

        When several entries judge, the last one wins - kept as-is from the
        old engine for parity during the port.
        TODO(roadmap): revisit last-wins vs "all checks must pass" (F6).
        """
        verdict = ResultType.DONE
        for output_name, output_config in self.output_mapping.items():
            output_type = output_config["type"]
            match output_type:
                case "passthrough":
                    verdict = step_output[output_name]
                case "passfail":
                    verdict = ResultType.PASS if step_output[output_name] else ResultType.FAIL
                case "equals":
                    matches = step_output[output_name] == output_config["value"]
                    verdict = ResultType.PASS if matches else ResultType.FAIL
                case "range":
                    low = float(output_config["min"])
                    high = float(output_config["max"])
                    in_range = low <= float(step_output[output_name]) <= high
                    verdict = ResultType.PASS if in_range else ResultType.FAIL
                case "local":
                    runtime.set_local(output_config["local_name"], step_output[output_name])
                case "global":
                    runtime.set_global(output_config["global_name"], step_output[output_name])
                case _:
                    raise ValueError(
                        f"Step '{self.name}': unknown output type {output_type!r} "
                        f"for output '{output_name}'"
                    )
        return verdict

    # --- the lifecycle ---------------------------------------------------------

    def run(self, runtime: Runtime) -> StepResult:
        """
        Run this step start to finish; always return a StepResult.

        Emits StepStarted before the work and StepFinished after it, through
        the Runtime - so the same events flow whether the step runs at the
        top of a sequence or (later) nested inside one. A StepExecuted with
        the rich record for the Report follows last, so the frontend's flat
        event is never held up by the record keeping.
        """
        step_result = StepResult(self)
        runtime.emit(StepStarted(step_id=self.id, step_name=self.name))
        started_at = time.time()
        work_began = time.perf_counter()

        if self.skip:
            step_result.set_skip()
        else:
            step_input: dict[str, Any] = {}
            try:
                step_input = self.process_inputs(runtime)
                raw_output = self._step(runtime, step_input)
            except Exception:  # noqa: BLE001 - a step failure must become a StepResult
                step_result.set_error(traceback.format_exc(), step_input)
            else:
                if raw_output is None:
                    step_output: dict[str, Any] = {}
                elif isinstance(raw_output, dict):
                    step_output = raw_output
                else:
                    step_output = {"output": raw_output}
                verdict = self.process_outputs(runtime, step_output)
                step_result.set_result(verdict, step_input, step_output)

        duration_s = time.perf_counter() - work_began
        runtime.emit(StepFinished(outcome=step_result.to_outcome()))
        runtime.emit(
            StepExecuted(
                outcome=step_result.to_outcome(),
                step_type=type(self).__name__,
                # Copies: the message is a fact, and the result's dicts live on.
                inputs=dict(step_result.inputs),
                outputs=dict(step_result.outputs),
                started_at=started_at,
                duration_s=duration_s,
            )
        )
        return step_result

    @staticmethod
    def run_steps(
        runtime: Runtime, steps: list["Step"], honour_stop: bool = True
    ) -> list[StepResult]:
        """
        Run a list of steps in order; return their results.

        The policy, deliberately minimal for now:
        - a step ERROR abandons the remaining steps (the old default;
          continue_on_error is a recorded roadmap TODO),
        - the stop flag is checked *between* steps, never inside one, so a
          step can leave its hardware in a known state,
        - teardown callers pass honour_stop=False: cleanup runs even after
          an abort - it is what returns the bench to a known state.
        """
        step_results: list[StepResult] = []
        for step in steps:
            if honour_stop and runtime.should_stop():
                break
            step_result = step.run(runtime)
            step_results.append(step_result)
            if step_result.result is ResultType.ERROR:
                break
        return step_results


def run_sequence(runtime: Runtime, sequence: "Sequence") -> tuple[ResultType, list[StepResult]]:
    """
    Run one sequence: its steps, then - always - its teardown steps.

    This is the sequence *body*, free of any queue or thread, so the future
    SequenceStep can call it for a nested sequence exactly as the Sequencer
    calls it for the top one. Emits SequenceStarted/SequenceFinished; the
    run-level pair (RunStarted/RunFinished) belongs to the Sequencer.

    The sequence's parsed locals are pushed as a *copy*: the old engine
    pushed the dict by reference, so a re-run started from the previous
    run's writes (F16).
    """
    runtime.emit(SequenceStarted(sequence_name=sequence.name))
    runtime.push_locals(dict(sequence.locals))
    step_results: list[StepResult] = []
    try:
        step_results.extend(Step.run_steps(runtime, sequence.steps))
    finally:
        step_results.extend(Step.run_steps(runtime, sequence.teardown_steps, honour_stop=False))
        runtime.pop_locals()

    result = StepResult.evaluate_multiple_step_results(step_results)
    runtime.emit(SequenceFinished(sequence_name=sequence.name, result=result))
    return result, step_results
