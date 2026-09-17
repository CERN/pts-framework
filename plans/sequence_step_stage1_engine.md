# SequenceStep — Stage 1 (Engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A recipe can call other sequence documents with `steptype: Sequence`, to any depth and any number of times; each call runs as a real group (own verdict, own teardown, own row) through the existing step layer.

**Architecture:** The parser builds a fresh `SequenceStep` + child `Sequence` per call site (new UUIDs), refusing unknown targets, calls to main and recursion. At run time `SequenceStep` runs its child through the existing `run_sequence()`. `Runtime` carries plain nesting state (`group_path`, `depth`, `in_teardown`, `halt_reason`) so halt / stop / pause / teardown rules hold at every depth, and `Step` grows three hooks a container type replaces (`_verdict`, `_skip_contents`, `child_results`).

**Tech Stack:** Python ≥ 3.11, pytest, ruff, mypy, PyYAML.

**Spec:** `plans/sequence_step_design.md` (HTML copy: `resources/internal_reports/sequence_step_design.html`). Read §1–§3 before starting.

## Global Constraints

- **Do not commit.** The user reviews and commits. Never `git checkout` a file to undo work.
- Never modify or delete anything under `src/pypts/old_code/`.
- Logging is `%`-style, never f-strings (ruff `G004`). INFO+ is for the technician; developer detail is DEBUG (`logger/logging_rules.md`).
- Old-school readable Python: `if`/`else` over conditional expressions, named locals over one-liners.
- `ruff check src tests` (line length 100), `mypy`, `pytest tests` must all pass at the end of the stage. Code blocks in this plan are the intended content; re-wrap any line ruff reports as too long.
- New files under `src/pypts/**` and `tests/**` need no SPDX header (`reuse.toml`), but match neighbours and add one.
- YAML key for the called sequence is `sequence_name`; a Sequence step refuses `step_name`, `inputs`, `outputs`, `id`.
- An `Indexed` step whose `template` is a `Sequence` step is refused. No `repeat` key anywhere.
- A group the run never reaches: every row inside it, teardown included, is SKIP and nothing runs.
- `skip: true` on a group: its steps are SKIP, its teardown still runs.
- Totals count real steps only (group rows excluded).
- Stage 1 is transitional: every sequence document is still built as a root; the dropdown, `StartSequence(name)` and the "never called from main" warning are stage 2.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/pypts/step/sequence_step.py` | **Create** | `SequenceStep` class; `SEQUENCE_STEPTYPE`, `is_sequence_step()`, `check_sequence_step()` |
| `src/pypts/step/runtime.py` | Modify | Nesting state + `entering()` context manager |
| `src/pypts/step/step.py` | Modify | Hooks on `Step`; `run()`, `run_steps()`, `run_sequence()` nesting rules; `real_step_results()`; indentation |
| `src/pypts/step/registry.py` | Modify | Register `"sequence": SequenceStep` |
| `src/pypts/step/indexed_step.py` | Modify | Refuse a `Sequence` template |
| `src/pypts/recipe/rules.py` | Modify | `sequence` steptype rules; `UNNAMED_STEP_TYPES` |
| `src/pypts/recipe/validator.py` | Modify | Sequence step shape; no `step_name` requirement for it |
| `src/pypts/recipe/recipe_parser.py` | Modify | Build call tree; refusals; `row_mappings()` |
| `src/pypts/recipe/recipe.py` | Modify | Depth-first summary with `depth` / `is_group` |
| `src/pypts/recipe/step_source.py` | Modify | Fragments follow the call tree |
| `src/pypts/messages/run_events.py` | Modify | `StepSummary.depth`, `StepSummary.is_group`, `StepExecuted.group_path` |
| `src/pypts/sequencer/sequencer.py` | Modify | `RunFinished.outcomes` and run summary count real steps |
| `tests/unit_tests/test_step.py` | Modify | Runtime nesting + SequenceStep behaviour |
| `tests/unit_tests/test_recipe.py` | Modify | Parser tree, refusals, summary, fragments |
| `tests/unit_tests/test_sequencer.py` | Modify | Real-step outcomes through the Sequencer |
| Docs: `step/step.md`, `step/__init__.py`, `recipe/recipe.md`, `messages/messages.md`, `sequencer/sequencer.md`, `pypts_implementation_status.html` | Modify | Same change as the code |

---

### Task 0: Baseline

- [ ] **Step 1: Record the gates before touching anything**

Run: `pytest tests -q` then `ruff check src tests` then `mypy`
Expected: note the pass/skip counts and any pre-existing ruff findings, so a later difference is attributable. Do not fix pre-existing findings.

---

### Task 1: Rules, validator and the Sequence step's shape

**Files:**
- Create: `src/pypts/step/sequence_step.py` (shape helpers only in this task)
- Modify: `src/pypts/recipe/rules.py`, `src/pypts/recipe/validator.py`, `src/pypts/step/indexed_step.py`
- Test: `tests/unit_tests/test_recipe.py`

**Interfaces:**
- Produces: `sequence_step.SEQUENCE_STEPTYPE = "sequence"`, `sequence_step.is_sequence_step(step_data: Any) -> bool`, `sequence_step.check_sequence_step(step_data: dict[str, Any]) -> list[str]`, `rules.UNNAMED_STEP_TYPES: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit_tests/test_recipe.py`:

```python
# --------------------------------------------------------------------------
# Sequence steps - the shape of a call
# --------------------------------------------------------------------------

#: A tiny recipe with one call, for breaking one thing at a time.
ONE_CALL = f"""\
name: One call
version: {CURRENT_VERSION}
main_sequence: Main
---
sequence_name: Main
steps:
  - steptype: Sequence
    sequence_name: Group
---
sequence_name: Group
steps:
  - steptype: Wait
    step_name: Inside
    wait_time: '0'
"""

CALL_LINE = "  - steptype: Sequence\n    sequence_name: Group\n"


@pytest.mark.parametrize(
    ("key", "line"),
    [
        ("step_name", "    step_name: Cycle\n"),
        ("inputs", "    inputs: {a: 1}\n"),
        ("outputs", "    outputs: {x: {type: pass}}\n"),
        ("id", "    id: 00000000-0000-0000-0000-000000000001\n"),
    ],
)
def test_a_sequence_step_may_not_carry_a_step_name_inputs_outputs_or_id(key, line):
    """A call is named after the sequence it calls, shares the run's globals,
    takes its verdict from its steps and gets fresh ids per call."""
    text = ONE_CALL.replace(CALL_LINE, CALL_LINE + line)

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert key in str(error.value)
    assert "Sequence step" in str(error.value)


def test_a_sequence_step_needs_no_step_name_but_needs_a_sequence_name():
    text = ONE_CALL.replace("    sequence_name: Group\n", "")

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    message = str(error.value)
    assert "sequence_name" in message
    assert "step_name" not in message


def test_a_sequence_step_cannot_be_the_template_of_an_indexed_step():
    """A sequence is a group of steps; Indexed parametrizes one step. The two
    do not mix."""
    text = f"""\
name: Mixed
version: {CURRENT_VERSION}
---
sequence_name: Main
steps:
  - steptype: Indexed
    step_name: Repeat the group
    template:
      steptype: Sequence
      sequence_name: Group
    parameter_sets:
      - inputs: {{a: 1}}
---
sequence_name: Group
steps:
  - steptype: Wait
    step_name: Inside
    wait_time: '0'
"""
    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "Sequence step cannot be the 'template'" in str(error.value)
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit_tests/test_recipe.py -k "sequence_step" -v`
Expected: FAIL — `unknown steptype 'Sequence'` and `missing the required key 'step_name'`.

- [ ] **Step 3: Create `src/pypts/step/sequence_step.py` with the shape helpers**

```python
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

from typing import Any

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
    if target is not None:
        if not isinstance(target, str) or not target.strip():
            problems.append("'sequence_name' must be the name of a sequence in this recipe")
    return problems
```

- [ ] **Step 4: Rules** — in `src/pypts/recipe/rules.py`:

After `STEP_REQUIRED` add:

```python
#: Steptypes that take no `step_name`: they are named by something else. A
#: Sequence step is named after the sequence it calls (step/sequence_step.py).
UNNAMED_STEP_TYPES: tuple[str, ...] = ("sequence",)
```

In `STEP_TYPE_REQUIRED` add the entry `"sequence": ("sequence_name",),` (after `"wait"`).

In `STEP_TYPE_DEFAULTS` add, after `"wait": {},`:

```python
    # A Sequence step owns no mappings: a called sequence shares the run's
    # globals and takes its verdict from its own steps.
    "sequence": {},
```

Replace the `parameters / outputs` bullet in the `SEQUENCE_DEFAULTS` comment with:

```python
#:   `parameters` / `outputs`  a declared interface for a called sequence. A
#:                  Sequence step calls another sequence without one: the
#:                  group shares the run's globals (plans/sequence_step_design.md);
```

- [ ] **Step 5: Validator** — in `src/pypts/recipe/validator.py`, add `from pypts.step import indexed_step, sequence_step` (replace the existing `indexed_step` import) and change `validate_step()`:

```python
def validate_step(step_data: Any) -> list[str]:
    """One step mapping: the common mandatory fields, then its type's own."""
    if not isinstance(step_data, dict):
        return ["a step must be a mapping of keys to values"]

    steptype = step_data.get("steptype")
    unnamed = isinstance(steptype, str) and steptype.lower() in rules.UNNAMED_STEP_TYPES

    problems = []
    for field in rules.STEP_REQUIRED:
        if field == "step_name" and unnamed:
            continue
        if step_data.get(field) is None:
            problems.append(f"missing the required key '{field}'")

    if steptype is None:
        return problems
```

(keep the rest of the function as it is up to `problems.extend(_check_mappings(step_data))`), then add after it:

```python
    if sequence_step.is_sequence_step(step_data):
        problems.extend(sequence_step.check_sequence_step(step_data))
```

and in the indexed block change `if isinstance(template, dict):` to:

```python
        # A Sequence template is already refused by check_indexed_step(); probing
        # it as a step would only add a second, less helpful sentence.
        if isinstance(template, dict) and not sequence_step.is_sequence_step(template):
```

- [ ] **Step 6: Indexed refusal** — in `src/pypts/step/indexed_step.py` add `from pypts.step.sequence_step import is_sequence_step` below `from typing import Any`, and in `check_indexed_step()` add a branch after `elif is_indexed_step(template):`:

```python
        elif is_sequence_step(template):
            problems.append(
                f"a Sequence step cannot be the '{TEMPLATE_KEY}': a sequence is a group "
                f"of steps and {INDEXED_STEPTYPE} parametrizes a single step"
            )
```

- [ ] **Step 7: Run the new tests**

Run: `pytest tests/unit_tests/test_recipe.py -k "sequence_step" -v`
Expected: the step_name/inputs/outputs/id and indexed tests PASS. `test_a_sequence_step_needs_no_step_name_but_needs_a_sequence_name` PASSES. Known, temporary: `test_step.py::test_the_rules_and_the_registry_agree_on_the_steptypes` now FAILS (the rules know `sequence`, the registry does not) — Task 3 registers it. A recipe *with* a valid call still fails to build until Tasks 3 and 4.

---

### Task 2: Runtime nesting state and the step loops

**Files:**
- Modify: `src/pypts/step/runtime.py`, `src/pypts/step/step.py`, `src/pypts/messages/run_events.py`
- Test: `tests/unit_tests/test_step.py`

**Interfaces:**
- Produces:
  - `Runtime.group_path: str` (`""` outside any sequence), `Runtime.depth: int`, `Runtime.in_teardown: bool`, `Runtime.halt_reason: str` (`""` = not halted)
  - `Runtime.entering(sequence_name: str) -> contextlib.AbstractContextManager[None]`
  - `Step.contains_steps: bool` (class attribute, `False`), `Step.child_results: list[StepResult]`
  - `Step._verdict(runtime, step_output, failures: list[str] | None) -> ResultType`
  - `Step._skip_contents(runtime, reason: str) -> None`
  - `Step.run_steps(runtime, steps, run_to_end=False, phase="Step", skip_reason="")`
  - `run_sequence(runtime, sequence, skip_reason: str = "") -> tuple[ResultType, list[StepResult]]`
  - `real_step_results(step_results: list[StepResult]) -> list[StepResult]`
  - `StepExecuted.group_path: str = ""`

- [ ] **Step 1: Write the failing tests** — in `tests/unit_tests/test_step.py`, add `import logging` to the imports, add `real_step_results` to the `pypts.step.step` import list, give `FakeSequence` a description:

```python
class FakeSequence:
    """The attributes run_sequence() and SequenceStep read off a Sequence, and nothing else."""

    def __init__(self, name="Main", steps=(), teardown_steps=(), description=""):
        self.name = name
        self.description = description
        self.steps = list(steps)
        self.teardown_steps = list(teardown_steps)
```

and add a helper step plus this section after `test_a_sequence_writes_the_runs_globals_and_nothing_else`:

```python
class SeesTeardown(Step):
    """Records whether it ran inside a teardown list."""

    def __init__(self, seen, **kwargs):
        super().__init__(**kwargs)
        self.seen = seen

    def _step(self, runtime, step_input):
        self.seen.append((self.name, runtime.in_teardown))
        return {}


# --------------------------------------------------------------------------
# Nesting state - what a step list needs to know about where it runs
# --------------------------------------------------------------------------


def test_a_bare_runtime_is_inside_no_sequence():
    runtime = Runtime()
    assert runtime.group_path == ""
    assert runtime.depth == 0
    assert runtime.in_teardown is False
    assert runtime.halt_reason == ""


def test_entering_a_sequence_extends_the_path_and_the_depth():
    """The run's first sequence is depth 0; every sequence it calls is one deeper."""
    runtime = Runtime()
    with runtime.entering("Main"):
        assert (runtime.group_path, runtime.depth) == ("Main", 0)
        with runtime.entering("PowerCycle"):
            assert (runtime.group_path, runtime.depth) == ("Main/PowerCycle", 1)
        assert (runtime.group_path, runtime.depth) == ("Main", 0)
    assert (runtime.group_path, runtime.depth) == ("", 0)


def test_entering_restores_the_context_when_the_block_raises():
    runtime = Runtime()
    with pytest.raises(RuntimeError), runtime.entering("Main"):
        raise RuntimeError("boom")
    assert (runtime.group_path, runtime.depth) == ("", 0)


def test_a_step_record_says_which_sequence_it_ran_in():
    events = []
    runtime = Runtime(emit=events.append)
    sequence = FakeSequence(name="Main", steps=[ReturnsDict(step_name="one", payload={})])
    run_sequence(runtime, sequence)

    executed = [event for event in events if isinstance(event, StepExecuted)]
    assert executed[0].group_path == "Main"


def test_a_halt_is_seen_by_every_later_step_list_sharing_the_runtime():
    """A halt inside a group must end the run, not just the group's list."""
    ran = []
    runtime = Runtime()
    Step.run_steps(runtime, [Raises(step_name="critical", continue_on_error=False)])
    results = Step.run_steps(runtime, [Notes(ran, step_name="later")])

    assert ran == []
    assert results[0].result is ResultType.SKIP
    assert "stopped at step 'critical'" in results[0].error_info


def test_a_halt_never_reaches_a_teardown_list():
    ran = []
    runtime = Runtime()
    runtime.halt_reason = "Not run: the sequence stopped at step 'critical'."
    Step.run_steps(runtime, [Notes(ran, step_name="cleanup")], run_to_end=True)
    assert ran == ["cleanup"]


def test_a_skip_reason_given_up_front_records_every_step_skip():
    ran = []
    results = Step.run_steps(
        Runtime(),
        [Notes(ran, step_name="one"), Notes(ran, step_name="two")],
        skip_reason="Not run: because.",
    )
    assert ran == []
    assert [r.result for r in results] == [ResultType.SKIP, ResultType.SKIP]
    assert [r.error_info for r in results] == ["Not run: because.", "Not run: because."]


def test_teardown_state_is_set_while_teardown_runs_and_restored_after():
    seen = []
    runtime = Runtime()
    sequence = FakeSequence(
        steps=[SeesTeardown(seen, step_name="main")],
        teardown_steps=[SeesTeardown(seen, step_name="cleanup")],
    )
    run_sequence(runtime, sequence)

    assert seen == [("main", False), ("cleanup", True)]
    assert runtime.in_teardown is False


def test_a_sequence_run_inside_teardown_runs_to_the_end():
    """A group called from teardown inherits run-to-end: Stop does not skip it."""
    ran = []
    runtime = Runtime(should_stop=lambda: True)
    runtime.in_teardown = True
    run_sequence(runtime, FakeSequence(steps=[Notes(ran, step_name="inside teardown")]))
    assert ran == ["inside teardown"]


def test_only_the_runs_first_sequence_drops_a_pending_pause():
    """A pause pressed during a group's last step still holds before main's next step."""
    happened = []
    runtime = Runtime(drop_pending_pause=lambda: happened.append("drop"))
    inner = FakeSequence(name="Inner", steps=[Notes(happened, step_name="inner")])
    with runtime.entering("Main"):
        run_sequence(runtime, inner)
    assert happened == ["inner"]


def test_lines_inside_a_called_sequence_are_indented(caplog):
    runtime = Runtime()
    with caplog.at_level(logging.INFO), runtime.entering("Main"):
        run_sequence(
            runtime, FakeSequence(name="Inner", steps=[ReturnsDict(step_name="one", payload={})])
        )
    messages = [record.getMessage() for record in caplog.records]

    assert "  Sequence 'Inner' started: 1 steps." in messages
    assert any(message.startswith("  Step 1/1 'one' DONE") for message in messages)
    assert any(message.startswith("  Sequence 'Inner' finished: DONE") for message in messages)


def test_real_step_results_of_plain_steps_are_the_steps_themselves():
    results = Step.run_steps(Runtime(), [Notes([], step_name="a"), Notes([], step_name="b")])
    assert real_step_results(results) == results
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit_tests/test_step.py -k "runtime or entering or halt or skip_reason or teardown_state or inside_teardown or pending_pause or indented or real_step or record_says" -v`
Expected: FAIL — `AttributeError: 'Runtime' object has no attribute 'group_path'`, `unexpected keyword argument 'skip_reason'`, `cannot import name 'real_step_results'`.

- [ ] **Step 3: `StepExecuted.group_path`** — in `src/pypts/messages/run_events.py`, add to `StepExecuted` after `duration_s: float`:

```python
    #: Where the step ran: the sequence names from the run's first sequence down,
    #: joined with "/" - `Main/PowerCycle`. What the Report's group_path column
    #: will carry (stage 3).
    group_path: str = ""
```

and to the docstring's last paragraph append: `` `group_path` names the sequence the step ran in, and every sequence around it. ``

- [ ] **Step 4: Runtime state** — in `src/pypts/step/runtime.py`:

Add imports:

```python
from collections.abc import Callable, Iterator
from contextlib import contextmanager
```

At the end of `Runtime.__init__` add:

```python
        # --- where the step lists are running: plain state, not seams --------
        #: The sequence names from the run's first sequence down to the one
        #: running now, joined with "/": `Main/PowerCycle`. Empty outside any
        #: sequence. Set by entering(); rides on every StepExecuted.
        self.group_path = ""
        #: How deep the running sequence is called: 0 for the run's first
        #: sequence, 1 for a sequence it calls. Indents the operator's lines.
        self.depth = 0
        #: True while a teardown list runs, at any depth. A sequence called from
        #: teardown inherits it, so everything in it runs to the end.
        self.in_teardown = False
        #: Why the rest of the run is skipped after a `continue_on_error: false`
        #: step came back ERROR or FAIL; empty while nothing has halted. Shared
        #: by every step list of the run, so a halt inside a called sequence
        #: ends the whole run and not only the list it happened in.
        self.halt_reason = ""
```

After the globals methods add:

```python
    # --- nesting ----------------------------------------------------------------

    @contextmanager
    def entering(self, sequence_name: str) -> Iterator[None]:
        """
        Run the block inside `sequence_name`: path extended, one level deeper.

        The first sequence of a run starts the path and stays at depth 0; a
        sequence entered inside another is one level deeper. Both are restored
        when the block ends, however it ends.
        """
        outer_path = self.group_path
        outer_depth = self.depth
        if outer_path:
            self.group_path = f"{outer_path}/{sequence_name}"
            self.depth = outer_depth + 1
        else:
            self.group_path = sequence_name
        try:
            yield
        finally:
            self.group_path = outer_path
            self.depth = outer_depth
```

Update the class docstring to `"""One variable scope, the five seams to the Sequencer, and where the step lists are running."""` and add to the module docstring, after the paragraph about `globals`:

```
Beside the seams, four plain attributes say where the step lists are running,
because a sequence may call another (step/sequence_step.py): `group_path` and
`depth` (set by `entering()`), `in_teardown`, and `halt_reason`, which is how a
`continue_on_error: false` halt inside a called sequence ends the whole run.
```

- [ ] **Step 5: `Step` hooks** — in `src/pypts/step/step.py`, class `Step`:

Directly under the class docstring add:

```python
    #: True for a step type that runs other steps - a Sequence step. The step
    #: loops read it: a group is never held before (the hold lands before its
    #: first step), and `skip: true` enters it so its teardown still runs.
    contains_steps: bool = False
```

At the end of `__init__` add:

```python
        #: The results of the steps this step ran, for a type that contains
        #: steps; always empty for any other. run() copies it to subresults.
        self.child_results: list[StepResult] = []
```

After `_step()` add:

```python
    def _verdict(
        self, runtime: Runtime, step_output: dict[str, Any], failures: list[str] | None
    ) -> ResultType:
        """
        The verdict for what _step() returned.

        Every ordinary type judges its `outputs` mapping. A type that contains
        steps replaces this: its verdict is its steps' verdict.
        """
        return self.process_outputs(runtime, step_output, failures)

    def _skip_contents(self, runtime: Runtime, reason: str) -> None:
        """
        Settle the rows of whatever this step contains, when the run never reaches it.

        Nothing to do for an ordinary step. A type that contains steps records
        every one of them SKIP here, so their pre-filled rows do not stay pending.
        """
```

- [ ] **Step 6: `run()`** — replace the skip branch and the verdict call, and pass the path:

Replace

```python
        if self.skip or skip_reason:
            step_result.set_skip(skip_reason)
        else:
```

with

```python
        if skip_reason:
            step_result.set_skip(skip_reason)
            self._skip_contents(runtime, skip_reason)
        elif self.skip and not self.contains_steps:
            step_result.set_skip()
        else:
```

Replace `verdict = self.process_outputs(runtime, step_output, failures)` with `verdict = self._verdict(runtime, step_output, failures)`.

After the whole if/else, before `duration_s = ...`, add:

```python
        step_result.subresults = list(self.child_results)
```

In the `StepExecuted(...)` call add `group_path=runtime.group_path,` after `duration_s=duration_s,`.

Update the `run()` docstring's second paragraph: `A non-empty skip_reason forces the SKIP branch ...` gains the sentence `` A step that contains steps settles their rows too, through _skip_contents(). `skip: true` on such a step enters it instead, so its teardown still runs. ``

Update `StepResult`'s docstring sentence about `subresults` to: `` `subresults` holds the results of the steps a Sequence step ran; empty for every other step. ``

- [ ] **Step 7: `run_steps()`** — replace the signature and the loop body up to `step_results.append(step_result)` and the halt block:

```python
    @staticmethod
    def run_steps(
        runtime: Runtime,
        steps: list["Step"],
        run_to_end: bool = False,
        phase: str = "Step",
        skip_reason: str = "",
    ) -> list[StepResult]:
```

Add to the docstring's policy list:

```
        - a halt is `runtime.halt_reason`, shared by every list of the run, so
          a halt inside a called sequence skips the rest of every list around
          it too. Teardown lists (`run_to_end`) never see it,
        - a step that contains steps is never held before: the hold lands
          before the first step inside it,
        - a `skip_reason` given up front records every step SKIP with it -
          a group marked `skip: true`, or one the run never reached.
```

Loop:

```python
        step_results: list[StepResult] = []
        indent = "  " * runtime.depth
        total = len(steps)
        for position, step in enumerate(steps, start=1):
            if not skip_reason and not run_to_end and runtime.halt_reason:
                skip_reason = runtime.halt_reason
            if not skip_reason and not run_to_end and not step.contains_steps:
                # Before the stop check, not after it: a Stop pressed while
                # the run is held ends the hold, and must then be seen here.
                runtime.hold_if_paused(step.name, position, total)
            if not skip_reason and not run_to_end and runtime.should_stop():
                skip_reason = "Not run: the run was stopped by the operator."
                log.debug("The stop flag is set; the remaining steps will be skipped.")

            where = f"{indent}{phase} {position}/{total} '{step.name}'"
```

(the rest of the loop is unchanged up to the halt block, which becomes:)

```python
            halting_verdict = step_result.result in (ResultType.ERROR, ResultType.FAIL)
            if not run_to_end and not step.continue_on_error and halting_verdict:
                log.warning(
                    "%sThe sequence stops here: step '%s' came back %s and the recipe "
                    "says not to carry on past it.",
                    indent,
                    step.name,
                    step_result.result.name if step_result.result else "ERROR",
                )
                log.debug("Step '%s' has continue_on_error: false.", step.name)
                runtime.halt_reason = f"Not run: the sequence stopped at step '{step.name}'."
                skip_reason = runtime.halt_reason
        return step_results
```

- [ ] **Step 8: real steps and counting** — after `count_verdicts()` add:

```python
def real_step_results(step_results: list[StepResult]) -> list[StepResult]:
    """
    Every step that did work of its own, at every depth, in execution order.

    A group is replaced by the steps it ran, so a total counts real steps and
    never the rows that only stand for a group.
    """
    real: list[StepResult] = []
    for step_result in step_results:
        if step_result.step.contains_steps:
            real.extend(real_step_results(step_result.subresults))
        else:
            real.append(step_result)
    return real
```

In `log_step_outcome()` change `elif verdict is ResultType.ERROR:` to:

```python
    elif verdict is ResultType.ERROR and (not step.contains_steps or step_result.error_summary):
        # A group that ERRORs did run: the step inside it that could not run has
        # already written its own ERROR line. Only a group whose own machinery
        # raised carries an error_summary of its own.
```

(the body of that branch is unchanged).

- [ ] **Step 9: `run_sequence()`** — replace the function:

```python
def run_sequence(
    runtime: Runtime, sequence: "Sequence", skip_reason: str = ""
) -> tuple[ResultType, list[StepResult]]:
    """
    Run one sequence: its steps, then - always - its teardown steps.

    This is the sequence *body*, free of any queue or thread: the Sequencer
    calls it for the run's first sequence and SequenceStep calls it for every
    sequence a recipe calls. Emits SequenceStarted/SequenceFinished; the
    run-level pair (RunStarted/RunFinished) belongs to the Sequencer.

    It is also where the operator's sequence lines are written, because this is
    the only place that knows the step count, the aggregate verdict and the
    wall clock across both lists. Lines inside a called sequence are indented.

    Args:
        skip_reason: records every main step SKIP with this reason and still
            runs the teardown - a Sequence step marked `skip: true`.
    """
    with runtime.entering(sequence.name):
        indent = "  " * runtime.depth
        log.info("%sSequence '%s' started: %d steps.", indent, sequence.name, len(sequence.steps))
        log.debug(
            "Sequence '%s' (%s) has %d steps and %d teardown steps.",
            sequence.name,
            runtime.group_path,
            len(sequence.steps),
            len(sequence.teardown_steps),
        )
        began = time.perf_counter()
        runtime.emit(SequenceStarted(sequence_name=sequence.name))
        step_results: list[StepResult] = []
        try:
            # Inside a teardown list everything runs to the end, however deep.
            step_results.extend(
                Step.run_steps(
                    runtime,
                    sequence.steps,
                    run_to_end=runtime.in_teardown,
                    skip_reason=skip_reason,
                )
            )
        finally:
            # The run's main steps are over only when its first sequence's are:
            # a Pause pressed during a called sequence's last step still holds
            # before the next step of the sequence that called it.
            if runtime.depth == 0:
                runtime.drop_pending_pause()
            outer_in_teardown = runtime.in_teardown
            runtime.in_teardown = True
            try:
                step_results.extend(
                    Step.run_steps(
                        runtime, sequence.teardown_steps, run_to_end=True, phase="Teardown step"
                    )
                )
            finally:
                runtime.in_teardown = outer_in_teardown

        result = StepResult.evaluate_multiple_step_results(step_results)
        log.info(
            "%sSequence '%s' finished: %s - %s, %.1f s.",
            indent,
            sequence.name,
            result.name,
            describe_counts(count_verdicts(real_step_results(step_results))),
            time.perf_counter() - began,
        )
        runtime.emit(SequenceFinished(sequence_name=sequence.name, result=result))
    return result, step_results
```

- [ ] **Step 10: Run the new tests and the whole step suite**

Run: `pytest tests/unit_tests/test_step.py -v`
Expected: all PASS, including every pre-existing halt / stop / pause / teardown test.

---

### Task 3: `SequenceStep` and its behaviour

**Files:**
- Modify: `src/pypts/step/sequence_step.py`, `src/pypts/step/registry.py`
- Test: `tests/unit_tests/test_step.py`

**Interfaces:**
- Consumes: everything Task 2 produced.
- Produces: `SequenceStep(sequence_name: str, sequence: Sequence, description: str = "", skip: bool = False, continue_on_error: bool = True)`; `.name` is `sequence.name`; `.sequence`; `contains_steps = True`. Registry key `"sequence"`.

- [ ] **Step 1: Write the failing tests** — in `tests/unit_tests/test_step.py` add `from pypts.step.sequence_step import SequenceStep`, `count_verdicts` to the `pypts.step.step` import, and this section after the Task 2 section:

```python
# --------------------------------------------------------------------------
# SequenceStep - a called sequence runs as one group
# --------------------------------------------------------------------------


def group(name, steps=(), teardown_steps=(), description="", **kwargs):
    """What the parser builds for one call: a SequenceStep over its own copy."""
    sequence = FakeSequence(
        name=name, steps=steps, teardown_steps=teardown_steps, description=description
    )
    return SequenceStep(sequence_name=name.lower(), sequence=sequence, **kwargs)


def test_a_sequence_step_is_named_after_the_sequence_and_borrows_its_description():
    step = group("PowerCycle", description="Off and on again.")
    assert step.name == "PowerCycle"
    assert step.description == "Off and on again."
    assert step.contains_steps is True


def test_a_description_on_the_call_wins_over_the_sequences():
    sequence = FakeSequence(name="PowerCycle", description="Off and on again.")
    step = SequenceStep(sequence_name="PowerCycle", sequence=sequence, description="Before cal.")
    assert step.description == "Before cal."


@pytest.mark.parametrize("key", ["step_name", "inputs", "outputs", "id"])
def test_a_sequence_step_refuses_the_keys_a_call_cannot_carry(key):
    with pytest.raises(TypeError):
        SequenceStep(sequence_name="G", sequence=FakeSequence(name="G"), **{key: "x"})


def test_the_registry_builds_a_sequence_step():
    step = build_step(
        {"steptype": "Sequence", "sequence_name": "g", "sequence": FakeSequence(name="G")}
    )
    assert isinstance(step, SequenceStep)
    assert step.name == "G"


def test_a_group_reports_as_one_row_around_its_own_steps():
    events = []
    runtime = Runtime(emit=events.append)
    step = group(
        "G",
        steps=[ReturnsDict(step_name="inner", payload={})],
        teardown_steps=[ReturnsDict(step_name="cleanup", payload={})],
    )
    Step.run_steps(runtime, [step])

    order = []
    for event in events:
        if isinstance(event, StepStarted):
            order.append(("started", event.step_name))
        elif isinstance(event, StepFinished):
            order.append(("finished", event.outcome.step_name))
    assert order == [
        ("started", "G"),
        ("started", "inner"),
        ("finished", "inner"),
        ("started", "cleanup"),
        ("finished", "cleanup"),
        ("finished", "G"),
    ]


def test_a_group_verdict_is_the_worst_of_its_steps_including_teardown():
    passes = ReturnsDict(
        step_name="ok", payload={"ok": True}, outputs={"ok": {"type": "passfail"}}
    )
    step = group("G", steps=[passes], teardown_steps=[Raises(step_name="bad cleanup")])
    results = Step.run_steps(Runtime(), [step])

    assert results[0].result is ResultType.ERROR
    assert [r.result for r in results[0].subresults] == [ResultType.PASS, ResultType.ERROR]


def test_a_failing_group_says_which_step_failed():
    results = Step.run_steps(Runtime(), [group("G", steps=[fails("measure_v")])])
    assert results[0].result is ResultType.FAIL
    assert "'measure_v' FAIL" in results[0].error_info


def test_a_halt_inside_a_group_ends_the_run_and_every_teardown_still_runs():
    ran = []
    inner = group(
        "PowerCycle",
        steps=[fails("measure_v", continue_on_error=False), Notes(ran, step_name="check_i")],
        teardown_steps=[Notes(ran, step_name="power_on")],
    )
    main = FakeSequence(
        steps=[inner, Notes(ran, step_name="final_check")],
        teardown_steps=[Notes(ran, step_name="main cleanup")],
    )
    result, results = run_sequence(Runtime(), main)

    assert ran == ["power_on", "main cleanup"]
    assert result is ResultType.FAIL
    assert [r.result for r in results] == [ResultType.FAIL, ResultType.SKIP, ResultType.DONE]
    assert [r.result for r in results[0].subresults] == [
        ResultType.FAIL,
        ResultType.SKIP,
        ResultType.DONE,
    ]
    assert "stopped at step 'measure_v'" in results[1].error_info


def test_continue_on_error_false_on_a_group_halts_on_the_groups_verdict():
    ran = []
    halting_group = group("G", steps=[fails("x")], continue_on_error=False)
    results = Step.run_steps(Runtime(), [halting_group, Notes(ran, step_name="later")])

    assert ran == []
    assert "stopped at step 'G'" in results[1].error_info


def test_a_stop_inside_a_group_skips_the_rest_everywhere_and_runs_every_teardown():
    ran = []
    stopped = {"value": False}

    class PressesStop(Step):
        def _step(self, runtime, step_input):
            stopped["value"] = True
            return {}

    inner = group(
        "G",
        steps=[PressesStop(step_name="presses stop"), Notes(ran, step_name="inner two")],
        teardown_steps=[Notes(ran, step_name="inner cleanup")],
    )
    main = FakeSequence(
        steps=[inner, Notes(ran, step_name="outer two")],
        teardown_steps=[Notes(ran, step_name="outer cleanup")],
    )
    run_sequence(Runtime(should_stop=lambda: stopped["value"]), main)

    assert ran == ["inner cleanup", "outer cleanup"]


def test_the_run_is_held_before_steps_inside_a_group_but_not_before_the_group():
    holds = []
    runtime = Runtime(hold_if_paused=lambda step_name, position, total: holds.append(step_name))
    inner = group(
        "G", steps=[Notes([], step_name="inner")], teardown_steps=[Notes([], step_name="c")]
    )
    main = FakeSequence(steps=[Notes([], step_name="one"), inner])
    run_sequence(runtime, main)
    assert holds == ["one", "inner"]


def test_a_pending_pause_lapses_only_when_the_runs_main_steps_end():
    happened = []
    runtime = Runtime(drop_pending_pause=lambda: happened.append("drop"))
    main = FakeSequence(
        steps=[
            group(
                "G",
                steps=[Notes(happened, step_name="inner")],
                teardown_steps=[Notes(happened, step_name="inner cleanup")],
            )
        ],
        teardown_steps=[Notes(happened, step_name="outer cleanup")],
    )
    run_sequence(runtime, main)
    assert happened == ["inner", "inner cleanup", "drop", "outer cleanup"]


def test_a_group_called_from_teardown_runs_to_the_end_and_is_never_held():
    ran = []
    holds = []
    runtime = Runtime(
        should_stop=lambda: True,
        hold_if_paused=lambda step_name, position, total: holds.append(step_name),
    )
    main = FakeSequence(
        steps=[Notes(ran, step_name="main")],
        teardown_steps=[
            group(
                "Shutdown",
                steps=[
                    Raises(step_name="bad", continue_on_error=False),
                    Notes(ran, step_name="after bad"),
                ],
            )
        ],
    )
    run_sequence(runtime, main)

    assert ran == ["after bad"]
    assert holds == ["main"]


def test_skip_true_on_a_group_skips_its_steps_but_runs_its_teardown():
    ran = []
    step = group(
        "G",
        steps=[Notes(ran, step_name="inner")],
        teardown_steps=[Notes(ran, step_name="cleanup")],
        skip=True,
    )
    results = Step.run_steps(Runtime(), [step])

    assert ran == ["cleanup"]
    assert results[0].result is ResultType.DONE
    assert [r.result for r in results[0].subresults] == [ResultType.SKIP, ResultType.DONE]
    assert "marked to skip" in results[0].subresults[0].error_info


def test_a_group_the_run_never_reaches_settles_every_row_and_runs_nothing():
    ran = []
    events = []
    nested = group("Nested", steps=[Notes(ran, step_name="deep")])
    steps = [
        Raises(step_name="critical", continue_on_error=False),
        group(
            "G",
            steps=[Notes(ran, step_name="inner"), nested],
            teardown_steps=[Notes(ran, step_name="cleanup")],
        ),
    ]
    Step.run_steps(Runtime(emit=events.append), steps)

    finished = [event.outcome for event in events if isinstance(event, StepFinished)]
    assert ran == []
    assert [outcome.step_name for outcome in finished] == [
        "critical",
        "inner",
        "deep",
        "Nested",
        "cleanup",
        "G",
    ]
    assert all(outcome.result is ResultType.SKIP for outcome in finished[1:])


def test_rows_inside_a_group_say_where_they_ran():
    events = []
    main = FakeSequence(
        name="Main", steps=[group("G", steps=[ReturnsDict(step_name="inner", payload={})])]
    )
    run_sequence(Runtime(emit=events.append), main)

    paths = {e.outcome.step_name: e.group_path for e in events if isinstance(e, StepExecuted)}
    assert paths == {"inner": "Main/G", "G": "Main"}


def test_totals_count_the_steps_inside_groups_and_not_the_groups():
    steps = [
        group("G", steps=[Notes([], step_name="a"), fails("b")]),
        Notes([], step_name="c"),
    ]
    results = Step.run_steps(Runtime(), steps)
    real = real_step_results(results)

    assert [r.step.name for r in real] == ["a", "b", "c"]
    counts = count_verdicts(real)
    assert counts[ResultType.DONE] == 2
    assert counts[ResultType.FAIL] == 1


def test_a_group_line_never_says_the_group_could_not_run(caplog):
    with caplog.at_level(logging.INFO):
        Step.run_steps(Runtime(), [group("G", steps=[Raises(step_name="inner")])])
    messages = [record.getMessage() for record in caplog.records]

    assert any("'inner' could not run" in message for message in messages)
    assert not any("'G' could not run" in message for message in messages)
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit_tests/test_step.py -k "group or sequence_step" -v`
Expected: FAIL — `cannot import name 'SequenceStep'`.

- [ ] **Step 3: The class** — append to `src/pypts/step/sequence_step.py`, and extend its imports:

```python
from typing import TYPE_CHECKING, Any

from pypts.messages.common_messages import ResultType
from pypts.step.runtime import Runtime
from pypts.step.step import Step, StepResult, real_step_results, run_sequence

if TYPE_CHECKING:
    from pypts.recipe.recipe import Sequence
```

```python
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
```

- [ ] **Step 4: Register it** — in `src/pypts/step/registry.py` add `from pypts.step.sequence_step import SequenceStep` (alphabetical, after `python_module_step`) and the entry `"sequence": SequenceStep,` after `"wait": WaitStep,`. Update the comment above `STEP_TYPES` only if it lists types (it does not).

- [ ] **Step 5: Run the step suite**

Run: `pytest tests/unit_tests/test_step.py -v`
Expected: all PASS, including `test_the_rules_and_the_registry_agree_on_the_steptypes`.

---

### Task 4: The parser builds the call tree

**Files:**
- Modify: `src/pypts/recipe/recipe_parser.py`, `src/pypts/recipe/recipe.py`, `src/pypts/recipe/step_source.py`, `src/pypts/messages/run_events.py`
- Test: `tests/unit_tests/test_recipe.py`

**Interfaces:**
- Consumes: `SequenceStep`, `sequence_step.is_sequence_step`, registry `"sequence"`.
- Produces: `StepSummary.depth: int = 0`, `StepSummary.is_group: bool = False`; `Sequence.summary_rows(depth: int) -> list[StepSummary]`; `recipe_parser.row_mappings(document, documents, chain=()) -> list[dict[str, Any]]` where `documents: dict[str, dict[str, Any]]` is keyed by lowercased sequence name and holds normalized documents.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit_tests/test_recipe.py`; add `from pypts.step.sequence_step import SequenceStep` to the imports:

```python
# --------------------------------------------------------------------------
# Sequence steps - the call tree built when the recipe loads
# --------------------------------------------------------------------------

NESTED = f"""\
name: Nested demo
version: {CURRENT_VERSION}
main_sequence: Main
---
sequence_name: Main
steps:
  - steptype: Sequence
    sequence_name: PowerCycle
  - steptype: Wait
    step_name: Between
    wait_time: '0'
  - steptype: SEQUENCE
    sequence_name: powercycle
teardown_steps:
  - steptype: Sequence
    sequence_name: Shutdown
---
sequence_name: PowerCycle
description: Power the DUT off and on again.
steps:
  - steptype: Wait
    step_name: Power off
    wait_time: '0'
  - steptype: Sequence
    sequence_name: Settle
teardown_steps:
  - steptype: Wait
    step_name: Power on
    wait_time: '0'
---
sequence_name: Settle
steps:
  - steptype: Wait
    step_name: Settle wait
    wait_time: '0'
---
sequence_name: Shutdown
steps:
  - steptype: Wait
    step_name: Everything off
    wait_time: '0'
"""

SETTLE_BODY = "    step_name: Settle wait\n    wait_time: '0'\n"
SHUTDOWN_BODY = "    step_name: Everything off\n    wait_time: '0'\n"


def main_rows(recipe):
    for summary in recipe.to_summary():
        if summary.sequence_name == "Main":
            return summary.steps
    raise AssertionError("no Main summary")


def test_every_call_holds_its_own_copy_of_the_called_sequence():
    main = Recipe.from_yaml_text(NESTED).sequences["Main"]
    first, between, second = main.steps

    assert isinstance(first, SequenceStep)
    assert isinstance(second, SequenceStep)
    assert (first.name, between.name, second.name) == ("PowerCycle", "Between", "PowerCycle")
    assert first.description == "Power the DUT off and on again."
    assert [step.name for step in first.sequence.steps] == ["Power off", "Settle"]
    assert first.sequence is not second.sequence
    assert not {s.id for s in first.sequence.steps} & {s.id for s in second.sequence.steps}


def test_a_sequence_may_be_called_from_teardown():
    main = Recipe.from_yaml_text(NESTED).sequences["Main"]
    shutdown = main.teardown_steps[0]
    assert isinstance(shutdown, SequenceStep)
    assert [step.name for step in shutdown.sequence.steps] == ["Everything off"]


def test_calling_the_same_sequence_many_times_is_not_a_cycle():
    calls = "  - steptype: Sequence\n    sequence_name: Group\n" * 45
    text = ONE_CALL.replace(CALL_LINE, calls)
    main = Recipe.from_yaml_text(text).sequences["Main"]

    assert len(main.steps) == 45
    inner_ids = [step.sequence.steps[0].id for step in main.steps]
    assert len(set(inner_ids)) == 45


def test_the_summary_lists_the_call_tree_depth_first():
    recipe = Recipe.from_yaml_text(NESTED)
    rows = main_rows(recipe)

    assert [(row.step_name, row.depth, row.is_group) for row in rows] == [
        ("PowerCycle", 0, True),
        ("Power off", 1, False),
        ("Settle", 1, True),
        ("Settle wait", 2, False),
        ("Power on", 1, False),
        ("Between", 0, False),
        ("PowerCycle", 0, True),
        ("Power off", 1, False),
        ("Settle", 1, True),
        ("Settle wait", 2, False),
        ("Power on", 1, False),
        ("Shutdown", 0, True),
        ("Everything off", 1, False),
    ]
    assert len({row.step_id for row in rows}) == len(rows)


def test_calling_a_sequence_that_does_not_exist_is_refused():
    text = NESTED.replace("    sequence_name: Shutdown\n", "    sequence_name: Shutdwn\n")

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    message = str(error.value)
    assert "no sequence called 'Shutdwn'" in message
    assert "PowerCycle" in message


def test_the_main_sequence_cannot_be_called():
    call = "  - steptype: Sequence\n    sequence_name: Main\n"
    text = NESTED.replace(SETTLE_BODY, SETTLE_BODY + call)

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "main sequence" in str(error.value)


def test_a_sequence_that_ends_up_calling_itself_is_refused_with_the_chain():
    call = "  - steptype: Sequence\n    sequence_name: PowerCycle\n"
    text = NESTED.replace(SETTLE_BODY, SETTLE_BODY + call)

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "Main -> PowerCycle -> Settle -> PowerCycle" in str(error.value)


def test_a_sequence_that_calls_itself_directly_is_refused():
    call = "  - steptype: Sequence\n    sequence_name: Shutdown\n"
    text = NESTED.replace(SHUTDOWN_BODY, SHUTDOWN_BODY + call)

    with pytest.raises(RecipeError) as error:
        Recipe.from_yaml_text(text)

    assert "Shutdown -> Shutdown" in str(error.value)


def test_an_indexed_step_inside_a_called_sequence_is_expanded_as_usual():
    indexed = """\
  - steptype: Indexed
    step_name: Add numbers
    template:
      steptype: PythonModule
      module: example_tests.py
      method_name: add
    parameter_sets:
      - inputs: {a: 1, b: 1}
      - inputs: {a: 2, b: 3}
"""
    text = NESTED.replace(SETTLE_BODY, SETTLE_BODY + indexed)
    first = Recipe.from_yaml_text(text).sequences["Main"].steps[0]
    settle = first.sequence.steps[1]

    assert [step.name for step in settle.sequence.steps] == [
        "Settle wait",
        "Add numbers [a=1, b=1]",
        "Add numbers [a=2, b=3]",
    ]


def test_a_called_sequence_adds_a_fragment_for_every_row_it_adds(tmp_path):
    path = tmp_path / "nested.yml"
    path.write_text(NESTED, encoding="utf-8")

    fragments = step_source.step_yaml_by_sequence(str(path))
    rows = main_rows(Recipe.from_file(str(path)))

    assert len(fragments["Main"]) == len(rows)
    assert "sequence_name: PowerCycle" in fragments["Main"][0]
    assert "Settle wait" in fragments["Main"][3]
    assert "Everything off" in fragments["Main"][-1]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit_tests/test_recipe.py -k "call or called or summary_lists or main_sequence_cannot or itself" -v`
Expected: FAIL — `unexpected keyword argument 'sequence_name'` / `missing 'sequence'` from the registry, `StepSummary` has no `depth`.

- [ ] **Step 3: `StepSummary` fields** — in `src/pypts/messages/run_events.py`, add to `StepSummary` after `description: str`:

```python
    #: How deep the row sits in the call tree: 0 for a step of the sequence
    #: itself, 1 for a step of a sequence it calls, and so on.
    depth: int = 0
    #: True for a row that stands for a called sequence (a Sequence step); its
    #: steps follow it, one level deeper.
    is_group: bool = False
```

and to its docstring: `` Rows are in run order, depth-first: a called sequence's row is followed by its own rows. ``

- [ ] **Step 4: `Sequence` summary** — in `src/pypts/recipe/recipe.py` add `from pypts.step.sequence_step import SequenceStep` and replace `to_summary()`:

```python
    def to_summary(self) -> SequenceSummary:
        """
        The pickle-safe projection a frontend receives, mirroring
        StepResult.to_outcome(). One row per step that will emit events during
        a run - which includes the teardown steps, at the end, and every step
        of every sequence it calls, right after the row of the call.
        """
        return SequenceSummary(sequence_name=self.name, steps=tuple(self.summary_rows(0)))

    def summary_rows(self, depth: int) -> list[StepSummary]:
        """This sequence's rows at `depth`, each call followed by its own rows."""
        rows = []
        for step in self.steps + self.teardown_steps:
            is_group = isinstance(step, SequenceStep)
            rows.append(
                StepSummary(
                    step_id=step.id,
                    step_name=step.name,
                    description=step.description,
                    depth=depth,
                    is_group=is_group,
                )
            )
            if isinstance(step, SequenceStep):
                rows.extend(step.sequence.summary_rows(depth + 1))
        return rows
```

- [ ] **Step 5: Parser** — in `src/pypts/recipe/recipe_parser.py`:

Add `from pypts.step import indexed_step, sequence_step` (replacing the `indexed_step` import).

In the module docstring's pipeline, change the `build` line to:

```
    build                      Recipe -> Sequences -> Steps (via the step registry);
                               a Sequence step gets a fresh copy of the sequence
                               it calls, built the same way
```

Replace the block in `parse_recipe()` from `# Sequence names keep their case ...` down to `main_sequence = found[0]` with:

```python
    # Sequence names keep their case but must be unique without it, so a
    # case-insensitive lookup - main_sequence, or a Sequence step's
    # sequence_name - can never be ambiguous.
    documents: dict[str, dict[str, Any]] = {}
    for document in sequence_documents:
        name = str(document["sequence_name"])
        if name.lower() in documents:
            raise RecipeError(f"Recipe '{file_name}': duplicate sequence name '{name}'")
        documents[name.lower()] = document
    if not documents:
        raise RecipeError(f"Recipe '{file_name}' contains no sequence documents")

    # An omitted main_sequence means the first sequence in the file.
    names = [str(document["sequence_name"]) for document in sequence_documents]
    requested = str(header["main_sequence"] or names[0])
    main_document = documents.get(requested.lower())
    if main_document is None:
        raise RecipeError(
            f"Recipe '{file_name}': main_sequence '{requested}' does not exist. "
            f"Sequences: {', '.join(names)}"
        )
    main_sequence = str(main_document["sequence_name"])

    # Every document is built, each as the root of its own call tree. Only
    # main will be runnable (stage 2); until then the others stay selectable.
    sequences: dict[str, Sequence] = {}
    for document in sequence_documents:
        sequence = _build_sequence(document, documents, main_sequence, ())
        sequences[sequence.name] = sequence
```

Replace `_build_sequence()` with:

```python
def _build_sequence(
    document: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    main_sequence: str,
    calling: tuple[str, ...],
) -> Sequence:
    """
    Build one Sequence from one normalized, validated YAML document.

    Args:
        documents: every sequence document of the recipe, keyed by lowercased name.
        main_sequence: the main sequence's name, which no Sequence step may call.
        calling: the sequences whose Sequence steps led here, outermost first -
            what a cycle is detected and described with.
    """
    document = apply_defaults(document, SEQUENCE_DEFAULTS)
    name = document["sequence_name"]
    chain = calling + (str(name),)
    steps = _build_steps(name, list(document["steps"]), documents, main_sequence, chain)
    teardown_steps = _build_steps(
        name, list(document["teardown_steps"]), documents, main_sequence, chain
    )
    return Sequence(
        name=name,
        description=document["description"],
        steps=steps,
        teardown_steps=teardown_steps,
    )


def _build_steps(
    sequence_name: str,
    step_datas: list[Any],
    documents: dict[str, dict[str, Any]],
    main_sequence: str,
    chain: tuple[str, ...],
) -> list[Step]:
    """One step list: Indexed steps expanded, every call given its own sequence."""
    built = []
    expanded = _expand_indexed_steps(sequence_name, step_datas)
    for position, step_data in enumerate(expanded, start=1):
        if sequence_step.is_sequence_step(step_data):
            step_data = dict(step_data)
            step_data["sequence"] = _called_sequence(
                sequence_name, position, step_data, documents, main_sequence, chain
            )
        built.append(_build_step_or_refuse(sequence_name, position, step_data))
    return built


def _called_sequence(
    sequence_name: str,
    position: int,
    step_data: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    main_sequence: str,
    chain: tuple[str, ...],
) -> Sequence:
    """
    A fresh copy of the sequence one Sequence step calls.

    Fresh on every call, so two calls never share a Step object or a UUID - the
    step table and the report tell rows apart by id. Refused: a name no sequence
    has, the main sequence, and a call that would lead back to a sequence
    already on the way here, which would never end. Calling one sequence many
    times one after another is not that.
    """
    target = str(step_data["sequence_name"])
    where = f"Sequence '{sequence_name}', step {position} ('{target}')"
    document = documents.get(target.lower())
    if document is None:
        known = ", ".join(str(d["sequence_name"]) for d in documents.values())
        raise RecipeError(f"{where}: there is no sequence called '{target}'. Sequences: {known}")
    if target.lower() == main_sequence.lower():
        raise RecipeError(
            f"{where}: '{main_sequence}' is the main sequence. It runs the recipe and "
            f"cannot be called from another sequence."
        )
    called_name = str(document["sequence_name"])
    if called_name.lower() in {name.lower() for name in chain}:
        path = " -> ".join(chain + (called_name,))
        raise RecipeError(f"{where}: calling '{called_name}' here would never end: {path}")
    return _build_sequence(document, documents, main_sequence, chain)


def row_mappings(
    document: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    chain: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """
    Every step mapping one sequence's step table shows, in row order.

    The order of Sequence.to_summary(): steps then teardown steps, Indexed
    steps expanded, and each Sequence step followed by the rows of the sequence
    it calls. step_source.py renders these; a test pins the two orders together.
    A name that does not resolve, or a call back into the chain, adds no rows -
    the parser has already refused such a recipe.
    """
    document = apply_defaults(document, SEQUENCE_DEFAULTS)
    name = str(document["sequence_name"])
    chain = chain + (name,)
    rows: list[dict[str, Any]] = []
    for list_name in ("steps", "teardown_steps"):
        for step_data in _expand_indexed_steps(name, list(document[list_name])):
            rows.append(step_data)
            if not sequence_step.is_sequence_step(step_data):
                continue
            called = documents.get(str(step_data.get("sequence_name")).lower())
            if called is None:
                continue
            called_name = str(called["sequence_name"])
            if called_name.lower() in {one.lower() for one in chain}:
                continue
            rows.extend(row_mappings(called, documents, chain))
    return rows
```

In `_build_step_or_refuse()` replace `step_name = step_data.get("step_name", "<unnamed>")` with:

```python
    # A Sequence step has no step_name; it is named after the sequence it calls.
    step_name = step_data.get("step_name") or step_data.get("sequence_name") or "<unnamed>"
```

- [ ] **Step 6: step_source follows the tree** — in `src/pypts/recipe/step_source.py`, add `from pypts.recipe.recipe import RecipeError`, remove the now-unused `SEQUENCE_DEFAULTS` import, update the module docstring's ordering paragraph to say *"steps, then teardown_steps, each expanded, and every Sequence step followed by the rows of the sequence it calls - `recipe_parser.row_mappings()`, which is that order"*, and replace the loop in `step_yaml_by_sequence()` and `_one_sequence()`:

```python
    # Document 1 is the header; it has no steps. Every sequence document is
    # needed by name first, because a Sequence step's rows are another's.
    by_name: dict[str, dict[str, Any]] = {}
    for document in documents[1:]:
        if not isinstance(document, dict):
            continue
        normalized = recipe_parser.normalize_sequence(document)
        name = str(normalized.get("sequence_name") or "")
        if name and name.lower() not in by_name:
            by_name[name.lower()] = normalized

    fragments: dict[str, tuple[str, ...]] = {}
    for document in by_name.values():
        name = str(document["sequence_name"])
        try:
            rows = recipe_parser.row_mappings(document, by_name)
            rendered = tuple(_render(step_data) for step_data in rows)
        except (RecipeError, KeyError, ValueError, TypeError, yaml.YAMLError) as error:
            log.debug("No step YAML for sequence '%s' of '%s': %s", name, path, error)
            continue
        fragments[name] = rendered
    return fragments
```

Delete `_one_sequence()`.

- [ ] **Step 7: Run the recipe suite**

Run: `pytest tests/unit_tests/test_recipe.py -v`
Expected: all PASS, including the pre-existing duplicate-name, missing-main, Indexed and fragment tests (their error texts are unchanged).

---

### Task 5: The Sequencer counts real steps

**Files:**
- Modify: `src/pypts/sequencer/sequencer.py`
- Test: `tests/unit_tests/test_sequencer.py`

**Interfaces:**
- Consumes: `real_step_results()`.
- Produces: `RunFinished.outcomes` = every real step at every depth, in execution order.

- [ ] **Step 1: Write the failing test** — append after `test_sequence_result_is_sent_once_at_the_end` in `tests/unit_tests/test_sequencer.py`:

```python
#: Main calls a group of two waits between two waits of its own.
GROUPED_RECIPE = f"""\
name: Grouped
version: {CURRENT_VERSION}
main_sequence: Main
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Before
    wait_time: '0'
  - steptype: Sequence
    sequence_name: Group
  - steptype: Wait
    step_name: After
    wait_time: '0'
---
sequence_name: Group
steps:
  - steptype: Wait
    step_name: Inside one
    wait_time: '0'
  - steptype: Wait
    step_name: Inside two
    wait_time: '0'
"""


def test_run_finished_carries_every_real_step_and_no_group_rows(sequencer):
    instance, outbox, inbox = sequencer
    load_wait_recipe(instance, inbox, GROUPED_RECIPE)

    instance.execute_sequence("Main")

    messages = drain(outbox)
    finished = [m for m in messages if isinstance(m, StepFinished)]
    run_finished = [m for m in messages if isinstance(m, RunFinished)]
    assert [m.outcome.step_name for m in finished] == [
        "Before",
        "Inside one",
        "Inside two",
        "Group",
        "After",
    ]
    assert run_finished[0].result is ResultType.DONE
    assert [o.step_name for o in run_finished[0].outcomes] == [
        "Before",
        "Inside one",
        "Inside two",
        "After",
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/unit_tests/test_sequencer.py::test_run_finished_carries_every_real_step_and_no_group_rows -v`
Expected: FAIL — outcomes are `["Before", "Group", "After"]`.

- [ ] **Step 3: Implement** — in `src/pypts/sequencer/sequencer.py` change the import to `from pypts.step.step import StepResult, count_verdicts, describe_counts, real_step_results`, and in `execute_sequence()` replace the `RunFinished` send and the summary call:

```python
        if self.stop_requested:
            result = ResultType.STOP
        # Totals count real steps: a called sequence's row only stands for the
        # steps inside it, which are listed themselves.
        real_results = real_step_results(step_results)
        self.core.send(
            RunFinished(result=result, outcomes=tuple(r.to_outcome() for r in real_results))
        )
        self.log_run_summary(sequence_name, result, real_results, time.perf_counter() - run_began)
```

In `log_run_summary()`'s docstring change `step_results: every step that produced one, in order.` to `step_results: every real step that produced one, at every depth, in order.`

- [ ] **Step 4: Run the Sequencer suite**

Run: `pytest tests/unit_tests/test_sequencer.py -v`
Expected: all PASS.

---

### Task 6: Documentation for stage 1 and the gates

**Files:**
- Modify: `src/pypts/step/step.md`, `src/pypts/step/__init__.py`, `src/pypts/step/step.py` (module docstring), `src/pypts/recipe/recipe.md`, `src/pypts/messages/messages.md`, `src/pypts/sequencer/sequencer.md`, `pypts_implementation_status.html`

- [ ] **Step 1: `step.md`**
  - §1 table row 9: `| 9 | SequenceStep | Sequence | ✅ **engine done (stage 1)** | reversed 2026-09-16 — §2.8 |`; the sentence under the table: six ported → seven, "four types will never appear" → three.
  - Replace §2.8 entirely with a section **"2.8 `SequenceStep` → `Sequence` — reversed 2026-09-16, engine done"** covering: the decision reversal and why (group tests inside the one executable main sequence); the YAML (`steptype: Sequence`, `sequence_name`; refused `step_name`/`inputs`/`outputs`/`id`); fresh copy per call built by the parser and the three refusals (unknown, main, recursion — with chain) plus Indexed-template refusal; runtime (verdict incl. teardown, `skip: true` keeps teardown, never-reached group all SKIP, halt ends the run with teardowns innermost first and never STOP, pause before steps at any depth and lapsing only at depth 0, teardown inherited); `Runtime` nesting state; totals count real steps; stage 1 transitional notes; pointer to `plans/sequence_step_design.md`.
  - §3.1: add a bullet — *the halt is `runtime.halt_reason`, shared by every list of the run, so a halt inside a called sequence ends the run.*
  - §3.3: remove "`SequenceStep` was dropped" from the `__result`/`passthrough` bullet (it stays gone: a group's verdict comes from `_verdict()`, not an output).
  - §3.5: replace "With `SequenceStep` dropped (§2.8) the stack never held more than one frame either" with "A called sequence shares the same globals (§2.8)".
  - §3.7: pause holds before a step at any depth, never before a group row; `drop_pending_pause()` only at depth 0.
  - §4 rule: *"subclass `Step`, override `_step()` and nothing else — except a type that contains steps (`contains_steps = True`), which also replaces `_verdict()` and `_skip_contents()` and fills `child_results` (§2.8)."*
- [ ] **Step 2: `step/__init__.py` and `step.py` module docstrings** — add `sequence_step.py  SequenceStep: call another sequence of the recipe as a group` to the file table; replace "SequenceStep are dropped" and "when SequenceStep lands" wording with the current state; in `step.py`'s module docstring change "A subclass overrides `_step()` and nothing else ... a future SequenceStep" to the §4 rule above.
- [ ] **Step 3: `recipe/recipe.md`** — Key types: `Sequence.to_summary()` is depth-first over calls, rows carry `depth`/`is_group`; add a "Sequence steps" subsection (fresh copy per call, refusals, every document built as a root until stage 2, `row_mappings()` shared with `step_source.py`); remove the "Known gaps" bullet about `parameters`/`outputs` subsequence calling.
- [ ] **Step 4: `messages/messages.md`** — the `StepSummary` row gains `depth`, `is_group`; the `StepExecuted` row gains `group_path`.
- [ ] **Step 5: `sequencer/sequencer.md`** — `RunFinished.outcomes` and the run summary count real steps (a group row is not counted); a pause holds before a step inside a called sequence too.
- [ ] **Step 6: Roadmap** — in `pypts_implementation_status.html`, mark `TODO stage 1` `[x]` with `DONE 2026-09-17` and a one-line summary; in the step-types table's `SequenceStep` row write "engine done (stage 1)"; in the "Consequences" list, replace the `StepResult.subresults has no writer left` item with a note that `SequenceStep` writes it.
- [ ] **Step 7: Quality gates**

Run: `pytest tests` — Expected: baseline passes + the new tests, 0 failures.
Run: `ruff check src tests` — Expected: no findings beyond the baseline.
Run: `mypy` — Expected: clean.
If a gate fails, fix the cause (do not add `noqa` for a rule that is off, do not silence a rule without a reason on the same line).

- [ ] **Step 8: Report** — tell the user what changed, the gate numbers against the baseline, and what stage 1 deliberately leaves for stage 2–5 (dropdown, `StartSequence(name)`, never-called warning, GUI indentation, report `group_path` column, verificator/Creator — the Creator's "add Sequence step" menu entry exists but writes a `step_name` the parser refuses until stage 4).
