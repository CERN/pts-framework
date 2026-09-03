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
because turning the exception into a result *is* its job - and it nets the
output judging too, not only `_step()`: a recipe that declares an output the
step never returns is a failure of that step, not a reason to abandon the
rest of the sequence.

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


#: Longest one value may be where it is rendered into a failure reason. A step
#: is free to return a 40 kB string, and the reason travels into the log, the
#: step table's tooltip and a CSV cell - none of which is improved by it.
MAX_VALUE_CHARS = 80

#: How many failing checks, inputs or outputs one reason lists before it stops
#: and counts the rest. MAX_VALUE_CHARS bounds a single value; this bounds the
#: count, so a step with two hundred outputs cannot turn one INFO line into a
#: ten-kilobyte paragraph in the log, the tooltip, the results panel and a CSV
#: cell all at once.
MAX_LISTED_ITEMS = 8

#: The output types that read a value out of what the step returned. `pass`
#: does not, so a step may declare one without producing anything for it.
READS_A_VALUE = ("passfail", "equals", "range", "global")


def shorten(text: str, limit: int) -> str:
    """`text` cut to `limit` characters, the last three of them `...` when it was."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def cap_list(items: list[str]) -> list[str]:
    """
    `items`, cut to MAX_LISTED_ITEMS with a final phrase counting what was left.

    Cutting whole items rather than characters: a reason that ends mid-value is
    worse than one that says how much it is not showing.
    """
    if len(items) <= MAX_LISTED_ITEMS:
        return items
    remaining = len(items) - MAX_LISTED_ITEMS
    capped = items[:MAX_LISTED_ITEMS]
    capped.append(f"and {remaining} more")
    return capped


def render_value(value: Any) -> str:
    """
    One value as the operator reads it in a failure reason.

    Strings are quoted, so trailing whitespace and an empty answer are visible
    rather than being mistaken for a missing value; everything else is written
    plainly, because `4.2` is what the technician measured and `4.2` is what
    they should see.

    A string is shortened *before* it is quoted, and its two quotes count
    against the budget, so a value that was cut still ends in a quote and the
    result is never longer than MAX_VALUE_CHARS. Quoting first would end a long
    string at `...`, which reads as a cut number rather than as a cut string.
    """
    if isinstance(value, str):
        return "'" + shorten(value, MAX_VALUE_CHARS - 2) + "'"
    return shorten(str(value), MAX_VALUE_CHARS)


def describe_failed_check(output_name: str, output_config: dict[str, Any], value: Any) -> str:
    """
    Why one output check did not pass: what was measured, and what was wanted.

    Args:
        output_name: the key in the step's `outputs` mapping.
        output_config: that key's configuration, which carries the expectation.
        value: what the step actually returned for it.

    Returns:
        A phrase like `voltage = 4.2, expected between 4.9 and 5.1`. No closing
        full stop: the caller joins several of these.
    """
    measured = f"{output_name} = {render_value(value)}"
    match output_config["type"]:
        case "passfail":
            return f"{measured}, expected a pass"
        case "equals":
            return f"{measured}, expected {render_value(output_config['value'])}"
        case "range":
            return f"{measured}, expected between {output_config['min']} and {output_config['max']}"
        case _:
            # Only the three judging types can fail, so nothing should reach
            # here - but a reason that names the value is still better than
            # one that raises while explaining a failure.
            return measured


def exception_headline(exc: BaseException) -> str:
    """
    The exception and its message on one line: `ValueError: no answer`.

    This is the most useful thing that can be said about an unexpected failure
    without showing the operator a stack. It is taken from the exception rather
    than off the end of a formatted traceback, because the last *line* of a
    traceback is only the last line of the message: an exception whose text
    spans lines would lose its type and everything above the last one.

    A message that does span lines is joined with `; ` rather than left to
    break the operator's log line in two.
    """
    lines = "".join(traceback.format_exception_only(exc)).strip().splitlines()
    return "; ".join(line.strip() for line in lines if line.strip())


def describe_values(label: str, values: dict[str, Any]) -> str:
    """`label: name = value, name = value`, or "" when there is nothing to show."""
    if not values:
        return ""
    rendered = [f"{name} = {render_value(value)}" for name, value in values.items()]
    return f"{label}: " + ", ".join(cap_list(rendered))


def build_fail_reason(
    failures: list[str], step_input: dict[str, Any], step_output: dict[str, Any]
) -> str:
    """
    The whole sentence after `FAIL (1.1 s) - `.

    The failing checks first, because that is the question being answered, then
    the inputs the step was given and the outputs it produced - the two things
    a technician needs to tell a bad unit from a bad test setup, and the two
    things they would otherwise have to open the report to find.

    Returns:
        `voltage = 4.2, expected between 4.9 and 5.1; inputs: channel = 1;
        outputs: voltage = 4.2, temperature = 31.5.` Empty when there is
        genuinely nothing to say, so the caller can leave the line at the
        duration rather than printing a bare dash.

        Each of the three groups is capped at MAX_LISTED_ITEMS, so the whole
        sentence stays a sentence however many outputs the step declared.
    """
    parts = cap_list([failure for failure in failures if failure])
    for label, values in (("inputs", step_input), ("outputs", step_output)):
        described = describe_values(label, values)
        if described:
            parts.append(described)
    if not parts:
        return ""
    return "; ".join(parts) + "."


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
        #: The exception and its message on one line, for the operator's ERROR
        #: log line. `error_info` keeps the whole traceback, which belongs at
        #: DEBUG; only set_error() writes this one.
        self.error_summary: str = ""
        self.uuid: uuid.UUID = uuid.uuid4()
        self.subresults: list[StepResult] = []

    def set_result(
        self,
        result_type: ResultType,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        reason: str = "",
    ) -> None:
        """
        Normal completion: the judged verdict plus what went in and came out.

        `reason` is the operator's answer to "why does this say FAIL" - which
        check failed, what was measured, what was expected, and the inputs and
        outputs around it. It is written to `error_info` for the same reason
        set_skip() writes its reason there: that is the field the step table's
        tooltip, the CLI's step line and the report's CSV already read, so one
        sentence reaches all four places and the log.
        """
        self.result = result_type
        self.inputs = inputs
        self.outputs = outputs
        if reason:
            self.error_info = reason

    def set_error(
        self,
        exc: BaseException,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
    ) -> None:
        """
        The step raised: verdict ERROR, the traceback, and the line above it.

        `error_info` keeps the whole traceback, because that is the field the
        step table's tooltip, the CLI's step line and the report's CSV already
        read. `error_summary` is the one sentence the operator gets in the log,
        and it is built from the live exception - see exception_headline().

        `outputs` is what the step had already returned when the failure
        happened, which is empty when `_step()` itself raised and is not when
        the judging did. Judging can fail after a measurement was taken, and
        that measurement is exactly what explains the failure, so it is kept
        rather than dropped.
        """
        self.result = ResultType.ERROR
        self.error_info = "".join(traceback.format_exception(exc))
        self.error_summary = exception_headline(exc)
        self.inputs = inputs
        if outputs:
            self.outputs = dict(outputs)

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
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        skip: bool = False,
        continue_on_error: bool = True,
    ) -> None:
        self.name = step_name
        self.description = description
        # A fresh dict per instance. The old base used mutable defaults, so
        # every step that omitted a mapping shared one dict (F12).
        self.inputs: dict[str, Any] = dict(inputs) if inputs else {}
        self.outputs: dict[str, Any] = dict(outputs) if outputs else {}
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
        `outputs` mapping, or any other value (wrapped as {"output": value};
        None becomes {}). Raise to fail the step - run() turns the exception
        into a StepResult with ResultType.ERROR.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement _step()")

    # --- input resolution ------------------------------------------------------

    def process_inputs(self, runtime: Runtime) -> dict[str, Any]:
        """
        Resolve `inputs` into the dict of values _step() receives.

        An entry that is not a mapping **is** the value: `a: 2`. That is the
        spelling for a literal, which is what most arguments are. The only
        other place a value can come from is `global`, the run's one variable
        scope, and a mapping is how an entry says so.

        There is no type coercion anywhere: '45' stays a string, 45 an int.
        """
        resolved: dict[str, Any] = {}
        for input_name, input_config in self.inputs.items():
            if not isinstance(input_config, dict):
                resolved[input_name] = input_config
                continue
            input_type = input_config.get("type")
            match input_type:
                case "global":
                    resolved[input_name] = runtime.get_global(input_config["global_name"])
                case _:
                    # The old code left the raw config dict in place. A typo'd
                    # type must be an ERROR on this step, not a weird argument.
                    # A literal is written as itself, so a mapping here is
                    # always a configuration and always names its type.
                    raise ValueError(
                        f"Step '{self.name}': unknown input type {input_type!r} "
                        f"for input '{input_name}'. A literal value is written "
                        f"as itself: `{input_name}: <the value>`."
                    )
        return resolved

    # --- output judging and storing --------------------------------------------

    def process_outputs(
        self,
        runtime: Runtime,
        step_output: dict[str, Any],
        failures: list[str] | None = None,
    ) -> ResultType:
        """
        Judge and store the step's outputs; return the verdict.

        Judging entries (`passfail`, `equals`, `range`) assign the verdict;
        `pass` says this output is not a measurement, so the verdict is DONE
        whatever came back; a `global` entry writes the run's one variable
        scope and leaves the verdict alone. With no entry that touches the
        verdict at all, it is DONE.

        When several entries judge, the last one wins - kept as-is from the
        old engine for parity during the port.
        TODO(roadmap): revisit last-wins vs "all checks must pass" (F6).

        Args:
            failures: if given, one sentence is appended for every check that
                did not pass - `read_voltage = 4.2, expected between 4.9 and
                5.1`. An out-parameter rather than a second return value
                because the verdict is this method's contract and the callers
                that only want the verdict, tests included, should not have to
                unpack a tuple to get it. `run()` is the one caller that
                passes a list.

                Every failing check is described, even where last-wins leaves
                the verdict PASS. `run()` only uses the list when the final
                verdict is FAIL, so F6 shows through in the verdict and never
                in a contradictory sentence beside it.
        """
        verdict = ResultType.DONE
        for output_name, output_config in self.outputs.items():
            output_type = output_config["type"]
            if output_type in READS_A_VALUE and output_name not in step_output:
                # A bare KeyError here would reach the operator as
                # `KeyError: 'voltage'`, which does not say whose fault it is.
                returned = ", ".join(step_output)
                if not returned:
                    returned = "nothing"
                raise ValueError(
                    f"Step '{self.name}': the recipe declares output "
                    f"'{output_name}' but the step did not return it. "
                    f"It returned: {returned}."
                )
            passed = True
            match output_type:
                case "pass":
                    verdict = ResultType.DONE
                case "passfail":
                    passed = bool(step_output[output_name])
                    verdict = ResultType.PASS if passed else ResultType.FAIL
                case "equals":
                    passed = step_output[output_name] == output_config["value"]
                    verdict = ResultType.PASS if passed else ResultType.FAIL
                case "range":
                    low = float(output_config["min"])
                    high = float(output_config["max"])
                    passed = low <= float(step_output[output_name]) <= high
                    verdict = ResultType.PASS if passed else ResultType.FAIL
                case "global":
                    runtime.set_global(output_config["global_name"], step_output[output_name])
                case _:
                    raise ValueError(
                        f"Step '{self.name}': unknown output type {output_type!r} "
                        f"for output '{output_name}'"
                    )
            if failures is not None and not passed:
                failures.append(
                    describe_failed_check(
                        output_name, output_config, step_output[output_name]
                    )
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
            except Exception as exc:  # noqa: BLE001 - a failure must become a StepResult
                step_result.set_error(exc, step_input)
            else:
                step_output: dict[str, Any] = {}
                # Judging gets a net of its own. A recipe can declare an output
                # the step never returns, or a `range` over something that is
                # not a number, and neither may leave run(): an exception out
                # of here unwinds run_steps() and run_sequence() all the way to
                # the Sequencer, so SequenceFinished never fires and every
                # later step is abandoned without even the SKIP row that
                # run_steps() exists to give it.
                try:
                    if raw_output is None:
                        step_output = {}
                    elif isinstance(raw_output, dict):
                        step_output = raw_output
                    else:
                        step_output = {"output": raw_output}
                    failures: list[str] = []
                    verdict = self.process_outputs(runtime, step_output, failures)
                    # Only on FAIL: on any other verdict a failing check either
                    # did not decide the outcome (F6, last-wins) or there is
                    # nothing to explain, and a reason beside a PASS would
                    # contradict it.
                    if verdict is ResultType.FAIL:
                        reason = build_fail_reason(failures, step_input, step_output)
                    else:
                        reason = ""
                except (KeyError, ValueError, TypeError) as exc:
                    step_result.set_error(exc, step_input, step_output)
                else:
                    step_result.set_result(verdict, step_input, step_output, reason)

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
        runtime: Runtime,
        steps: list["Step"],
        run_to_end: bool = False,
        phase: str = "Step",
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

        `phase` is only the word the operator's log lines start with, so that a
        teardown step reads as "Teardown step 1/2 'power_off'" rather than as a
        second step 1. It changes nothing about how a step is run.
        """
        step_results: list[StepResult] = []
        skip_reason = ""
        total = len(steps)
        for position, step in enumerate(steps, start=1):
            if not skip_reason and not run_to_end and runtime.should_stop():
                skip_reason = "Not run: the run was stopped by the operator."
                log.debug("The stop flag is set; the remaining steps will be skipped.")

            where = f"{phase} {position}/{total} '{step.name}'"
            # No "started" line for a step that is not going to run: it would
            # promise the operator work that never happens, and the SKIP line
            # right behind it says everything there is to say.
            if not skip_reason and not step.skip:
                log.info("%s started.", where)
            log.debug(
                "Running step '%s' (%s): skip=%s, continue_on_error=%s, skip_reason=%r.",
                step.name,
                type(step).__name__,
                step.skip,
                step.continue_on_error,
                skip_reason,
            )

            began = time.perf_counter()
            step_result = step.run(runtime, skip_reason=skip_reason)
            log_step_outcome(where, step, step_result, time.perf_counter() - began)
            step_results.append(step_result)
            if skip_reason:
                continue

            halting_verdict = step_result.result in (ResultType.ERROR, ResultType.FAIL)
            if not run_to_end and not step.continue_on_error and halting_verdict:
                log.warning(
                    "The sequence stops here: step '%s' came back %s and the recipe "
                    "says not to carry on past it.",
                    step.name,
                    step_result.result.name if step_result.result else "ERROR",
                )
                log.debug("Step '%s' has continue_on_error: false.", step.name)
                skip_reason = f"Not run: the sequence stopped at step '{step.name}'."
        return step_results


#: Verdict -> the word the summary counts it under. Ordered as the operator
#: reads it: what passed first, what went wrong next, what never ran last.
VERDICT_WORDS = (
    (ResultType.PASS, "passed"),
    (ResultType.DONE, "completed"),
    (ResultType.FAIL, "failed"),
    (ResultType.ERROR, "errored"),
    (ResultType.STOP, "stopped"),
    (ResultType.SKIP, "skipped"),
)


def count_verdicts(step_results: list[StepResult]) -> dict[ResultType, int]:
    """
    How many steps ended with each verdict.

    A result that was never set counts as ERROR, the same way to_outcome()
    reads it: a step that finished without a verdict did not work.
    """
    counts = {verdict: 0 for verdict, _word in VERDICT_WORDS}
    for step_result in step_results:
        if step_result.result is None:
            counts[ResultType.ERROR] += 1
        else:
            counts[step_result.result] += 1
    return counts


def describe_counts(counts: dict[ResultType, int]) -> str:
    """
    The counts as the operator reads them: "10 passed, 1 failed, 1 skipped".

    Verdicts nothing ended with are left out - a run with no errors should not
    have to say "0 errored" for the reader to work out that there were none.
    """
    parts = []
    for verdict, word in VERDICT_WORDS:
        if counts[verdict]:
            parts.append(f"{counts[verdict]} {word}")
    if not parts:
        return "no steps"
    return ", ".join(parts)


def log_step_outcome(
    where: str, step: "Step", step_result: StepResult, duration_s: float
) -> None:
    """
    Write the operator's line for one finished step, and the developer's under it.

    Kept out of run_steps() so the policy loop there stays about policy. The
    rules are logging_rules.md sections 2.1 and 7: a FAIL is an ordinary test result
    and logs at INFO, only a step that could not run at all is an ERROR, and
    its traceback stays at DEBUG.

    Args:
        where: the operator's name for the step, e.g. "Step 4/12 'read_voltage'".
        step: the step that ran, for the DEBUG line.
        step_result: what it produced.
        duration_s: how long it took, measured around the whole step.
    """
    if step_result.result is None:
        verdict = ResultType.ERROR
    else:
        verdict = step_result.result

    if verdict is ResultType.SKIP:
        # set_skip() puts the reason in error_info; a step the author marked
        # `skip: true` gives none, and that case has its own sentence.
        reason = step_result.error_info or "marked to skip in the recipe."
        log.info("%s SKIP - %s", where, reason)
    elif verdict is ResultType.ERROR:
        # error_summary is the exception and its message - the 'raw text' half
        # of the operator's sentence. error_info is the whole traceback, and
        # that belongs at DEBUG and nowhere else. A step that finished with no
        # verdict at all is counted ERROR here and has neither.
        log.error(
            "%s could not run (%.1f s): %s",
            where,
            duration_s,
            step_result.error_summary or "no reason was recorded",
        )
        if step_result.error_info:
            log.debug(
                "Traceback for the failure in step '%s':\n%s", step.name, step_result.error_info
            )
    elif verdict is ResultType.FAIL and step_result.error_info:
        log.info("%s FAIL (%.1f s) - %s", where, duration_s, step_result.error_info)
    else:
        log.info("%s %s (%.1f s).", where, verdict.name, duration_s)

    log.debug(
        "Step '%s' (%s) finished as %s in %.3f s; inputs %r, outputs %r.",
        step.name,
        type(step).__name__,
        verdict.name,
        duration_s,
        step_result.inputs,
        step_result.outputs,
    )


def run_sequence(runtime: Runtime, sequence: "Sequence") -> tuple[ResultType, list[StepResult]]:
    """
    Run one sequence: its steps, then - always - its teardown steps.

    This is the sequence *body*, free of any queue or thread, so the future
    SequenceStep can call it for a nested sequence exactly as the Sequencer
    calls it for the top one. Emits SequenceStarted/SequenceFinished; the
    run-level pair (RunStarted/RunFinished) belongs to the Sequencer.

    It is also where the operator's sequence lines are written, because this is
    the only place that knows the step count, the aggregate verdict and the
    wall clock across both lists.
    """
    log.info("Sequence '%s' started: %d steps.", sequence.name, len(sequence.steps))
    log.debug(
        "Sequence '%s' has %d steps and %d teardown steps.",
        sequence.name,
        len(sequence.steps),
        len(sequence.teardown_steps),
    )
    began = time.perf_counter()
    runtime.emit(SequenceStarted(sequence_name=sequence.name))
    step_results: list[StepResult] = []
    try:
        step_results.extend(Step.run_steps(runtime, sequence.steps))
    finally:
        step_results.extend(
            Step.run_steps(
                runtime, sequence.teardown_steps, run_to_end=True, phase="Teardown step"
            )
        )

    result = StepResult.evaluate_multiple_step_results(step_results)
    log.info(
        "Sequence '%s' finished: %s - %s, %.1f s.",
        sequence.name,
        result.name,
        describe_counts(count_verdicts(step_results)),
        time.perf_counter() - began,
    )
    runtime.emit(SequenceFinished(sequence_name=sequence.name, result=result))
    return result, step_results
