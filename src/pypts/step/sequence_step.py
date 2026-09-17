# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Sequence step: call another sequence of the same recipe as a group.

    - steptype: Sequence
      sequence_name: PowerCycle

A recipe has one executable sequence, `main_sequence`. Every other sequence
document is a group of steps that main - or another group - calls with a
Sequence step, to any depth and as many times as it likes. The call is named
after the sequence it calls, so it carries no `step_name`; a called sequence
shares the run's globals, so it carries no `inputs`; its verdict is its steps'
verdict, so it carries no `outputs`; and every call gets fresh step ids, so it
carries no `id`.

The parser builds a fresh copy of the called sequence for every call
(recipe_parser._build_steps), so two calls of one group never share a Step
object or a UUID. At run time the step runs its copy through run_sequence(),
the same body the Sequencer runs for main - see plans/sequence_step_design.md.
"""

from typing import TYPE_CHECKING, Any

from pypts.messages.common_messages import ResultType
from pypts.step.runtime import Runtime
from pypts.step.step import Step, StepResult, real_step_results, run_sequence

if TYPE_CHECKING:
    from pypts.recipe.recipe import Sequence

#: The steptype, lowercase as the registry and the rules spell them.
SEQUENCE_STEPTYPE = "sequence"

#: The keys a Sequence step refuses, each with the sentence the author reads.
REFUSED_KEYS: dict[str, str] = {
    "step_name": (
        "a Sequence step is named after the sequence it calls and cannot carry 'step_name'"
    ),
    "inputs": (
        "a Sequence step cannot carry 'inputs': a called sequence shares the run's globals"
    ),
    "outputs": (
        "a Sequence step cannot carry 'outputs': its verdict is the verdict of its steps"
    ),
    "id": "a Sequence step cannot carry an 'id': every call gets ids of its own",
}


def is_sequence_step(step_data: Any) -> bool:
    """Whether this step mapping calls another sequence."""
    if not isinstance(step_data, dict):
        return False
    steptype = step_data.get("steptype")
    return isinstance(steptype, str) and steptype.lower() == SEQUENCE_STEPTYPE


def check_sequence_step(step_data: dict[str, Any]) -> list[str]:
    """
    Everything about a Sequence step's own shape, as a list of problems.

    Whether the named sequence exists, is not the main sequence and does not
    end up calling itself needs the whole file, so the parser checks that.
    """
    problems = []
    for key, reason in REFUSED_KEYS.items():
        if step_data.get(key) is not None:
            problems.append(reason)

    target = step_data.get("sequence_name")
    # Absent is the required-field check's to report; present must name a sequence.
    names_nothing = not isinstance(target, str) or not target.strip()
    if target is not None and names_nothing:
        problems.append("'sequence_name' must be the name of a sequence in this recipe")
    return problems


class SequenceStep(Step):
    """
    One call of another sequence: its steps and teardown, run as one group.

    A real step with a real row. Its verdict is the worst of everything it
    ran, teardown included - the same rule a sequence aggregates by. Only
    `_step()`, `_verdict()` and `_skip_contents()` are its own; the lifecycle
    - events, skip, the error net - is Step.run(), unchanged.
    """

    contains_steps = True

    def __init__(
        self,
        sequence_name: str,
        sequence: "Sequence",
        description: str = "",
        skip: bool = False,
        continue_on_error: bool = True,
    ) -> None:
        if not description:
            description = sequence.description
        super().__init__(
            step_name=sequence.name,
            description=description,
            skip=skip,
            continue_on_error=continue_on_error,
        )
        #: As the recipe wrote it; `name` is the called sequence's own spelling.
        self.sequence_name = sequence_name
        #: This call's own copy - no other call shares a Step or a UUID with it.
        self.sequence = sequence

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        """Run the called sequence; `skip: true` skips its steps and keeps its teardown."""
        self.child_results = []
        skip_reason = ""
        if self.skip:
            skip_reason = f"Not run: the sequence '{self.name}' is marked to skip in the recipe."
        _result, self.child_results = run_sequence(runtime, self.sequence, skip_reason=skip_reason)
        return None

    def _verdict(
        self, runtime: Runtime, step_output: dict[str, Any], failures: list[str] | None
    ) -> ResultType:
        """The worst of what ran; each failing step inside is named for the operator."""
        if failures is not None:
            for inner in real_step_results(self.child_results):
                if inner.result in (ResultType.FAIL, ResultType.ERROR):
                    failures.append(f"'{inner.step.name}' {inner.result.name}")
        return StepResult.evaluate_multiple_step_results(self.child_results)

    def _skip_contents(self, runtime: Runtime, reason: str) -> None:
        """
        The run never reached this call: every row inside it is SKIP.

        Its teardown is not run either - nothing in the sequence was set up.
        """
        with runtime.entering(self.sequence.name):
            results = Step.run_steps(runtime, self.sequence.steps, skip_reason=reason)
            results += Step.run_steps(
                runtime, self.sequence.teardown_steps, phase="Teardown step", skip_reason=reason
            )
        self.child_results = results
