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

`continue_on_error` is a common field of every step, default True: an ERROR
or a FAIL is recorded and the sequence carries on. A step that says False
ends the run when it errors or fails, and every step after it is recorded
SKIP - see run_steps(). Per step and nowhere else: the old engine had three
disagreeing sources of truth for it (F8), and its per-step `critical`
override is dropped with them (step.md 3.2).

Deliberately absent, recorded in the roadmap: the `method` input type
(returns with PythonModuleStep).
"""

import time
import traceback
import uuid
from typing import TYPE_CHECKING, Any

from pypts.logger.log import log
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

    def set_skip(self, reason: str = "") -> None:
        """
        Verdict SKIP, with an optional reason.

        Two things end up here: a step the author marked `skip: true`, which
        gives no reason, and a step that never ran because the sequence ended
        before it (run_steps), which says so. The reason travels on the
        StepOutcome, so the operator reads it in the step table's tooltip and
        in the report's CSV rather than wondering why a row says SKIP.
        """
        self.result = ResultType.SKIP
        self.error_info = reason

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
        continue_on_error: bool = True,
    ) -> None:
        self.name = step_name
        self.description = description
        # A fresh dict per instance. The old base used mutable defaults, so
        # every step that omitted a mapping shared one dict (F12).
        self.input_mapping: dict[str, Any] = dict(input_mapping) if input_mapping else {}
        self.output_mapping: dict[str, Any] = dict(output_mapping) if output_mapping else {}
        self.skip = skip
        #: False means an ERROR or a FAIL on *this* step ends the run. The
        #: default carries on to the next step, so one bad step does not
        #: decide for the other nineteen. The old `critical` field said the
        #: same thing and is dropped - step.md 3.2.
        self.continue_on_error = continue_on_error
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

    def run(self, runtime: Runtime, skip_reason: str = "") -> StepResult:
        """
        Run this step start to finish; always return a StepResult.

        Emits StepStarted before the work and StepFinished after it, through
        the Runtime - so the same events flow whether the step runs at the
        top of a sequence or (later) nested inside one. A StepExecuted with
        the rich record for the Report follows last, so the frontend's flat
        event is never held up by the record keeping.

        A non-empty `skip_reason` forces the SKIP branch: the step's body is
        not entered, but it still emits the full trio, so a step the sequence
        never reached settles its row in the step table and gets its row in
        the CSV instead of staying pending forever. run_steps() is the only
        caller that passes it.
        """
        step_result = StepResult(self)
        runtime.emit(StepStarted(step_id=self.id, step_name=self.name))
        started_at = time.time()
        work_began = time.perf_counter()

        if self.skip or skip_reason:
            step_result.set_skip(skip_reason)
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
        runtime: Runtime, steps: list["Step"], run_to_end: bool = False
    ) -> list[StepResult]:
        """
        Run a list of steps in order; return one result per step, always.

        The policy:
        - an ERROR or a FAIL is recorded and the sequence carries on. This is
          the `continue_on_error: True` default: one bad step does not decide
          for the other nineteen,
        - a step that says `continue_on_error: false` ends the run when it
          errors *or* fails. Per step and nowhere else - there is no recipe-
          level and no `globals` form of the flag, which is what F1 and F8
          were,
        - the stop flag is checked *between* steps, never inside one, so a
          step can leave its hardware in a known state. It stays a separate
          branch from the verdict, so Stop still ends a run at once even
          though an ERROR on its own does not,
        - **whichever of the two ends the list early, every remaining step is
          run with a skip_reason** rather than dropped. It emits its events
          and comes back SKIP, so the step table settles every row and the
          report has a row per step no matter how the run ended. SKIP is the
          lowest ResultType, so this cannot change what the sequence
          aggregates to,
        - `run_to_end=True` disables both early exits. Teardown callers pass
          it: cleanup runs after an abort and after a halt, and one failing
          cleanup step does not skip the rest of the cleanup - which is the
          opposite of what teardown is for.
        """
        step_results: list[StepResult] = []
        skip_reason = ""
        for step in steps:
            if not skip_reason and not run_to_end and runtime.should_stop():
                skip_reason = "Not run: the run was stopped by the operator."

            step_result = step.run(runtime, skip_reason=skip_reason)
            step_results.append(step_result)
            if skip_reason:
                continue

            halting_verdict = step_result.result in (ResultType.ERROR, ResultType.FAIL)
            if not run_to_end and not step.continue_on_error and halting_verdict:
                log.warning(
                    "Step '%s' ended the run: %s, and it is marked continue_on_error: false.",
                    step.name,
                    step_result.result,
                )
                skip_reason = f"Not run: the sequence stopped at step '{step.name}'."
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
        step_results.extend(Step.run_steps(runtime, sequence.teardown_steps, run_to_end=True))
        runtime.pop_locals()

    result = StepResult.evaluate_multiple_step_results(step_results)
    runtime.emit(SequenceFinished(sequence_name=sequence.name, result=result))
    return result, step_results
