<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The step layer — the type catalogue and the port status

The module context file for `src/pypts/step/`. `__init__.py` says how the layer *works*
(the lifecycle, the Runtime seams, the emission model); this file says **which step types
the old engine had, which of them exist here, and which are never coming** — with the
decision behind each, so the state of the port can be read off one table instead of
re-derived from `old_code/steps.py` every time.

The roadmap stays the authority on status and phase and wins where they overlap.
`resources/roadmap/recipe_guide.md` §10 is the reference for what each old type *did*, in
recipe terms, and is worth reading before porting one.

---

## 1. The catalogue

Ten classes existed in `old_code/steps.py` (the whole file is commented out — it is read,
never run). Four are ported. Two more are wanted, four are not.

| # | Old class | YAML today | Status | Decision |
|---|---|---|---|---|
| 1 | `WaitStep` | `Wait` | ✅ **done** | — |
| 2 | `PythonModuleStep` | `PythonModule` | ✅ **done** | methods only; the attribute actions are dropped |
| 3 | `UserInteractionStep` | `UserInteraction` | ✅ **done** | the first type that blocks on a person |
| 4 | `UserWriteStep` | — | ❌ missing | **to be implemented** |
| 5 | `UserLoadingStep` | — | ❌ missing | **to be implemented** |
| 6 | `UserRunMethodStep` | — | ❌ missing | **deprecated — to be dropped** |
| 7 | `SSHConnectStep` | — | ❌ missing | **not a step type — moves into the framework** |
| 8 | `SSHCloseStep` | — | ❌ missing | **not a step type — moves into the framework** |
| 9 | `SequenceStep` | — | ❌ missing | **to be dropped** |
| 10 | `IndexedStep` | `Indexed` | ✅ **done, reshaped** | replaced by load-time expansion — §2.9 |

Decisions recorded 2026-09-01. Two types left to port, four that will never
appear in `STEP_TYPES` — plus `Indexed`, which is in the rules but never in the registry
because it is gone before anything is built.

---

## 2. What each one is, and what its port needs

### 2.1 `WaitStep` → `Wait` — done

`wait_step.py`. Sleeps. The one deliberate change from the old type: `wait_time` is a
**direct field on the step**, not an `input_mapping` entry — a fixed wait has no inputs to
resolve and no outputs to judge, so it carries neither mapping. Returns `{}`, so the
verdict is always `DONE`.

Known gap: the sleep is one `time.sleep()`, so it does not honour `runtime.should_stop()`.
The framework contract only promises a stop at the next *step* boundary, so this is a
courtesy, not a defect — but a 60 s wait delays an abort by up to 60 s.

### 2.2 `PythonModuleStep` → `PythonModule` — done

`python_module_step.py`. The workhorse: load a module, call into it, `input_mapping`
passed as keyword arguments.

- **Calling a method is the whole type.** `read_attribute` and `write_attribute` are
  **dropped** (decision 2026-09-01), not deferred: a recipe that needs an attribute writes
  a one-line getter or setter beside it and calls that, which keeps one way of reaching
  Python code instead of three.
- `action_type` survives as a **tolerated no-op** — one legal value, `method`, selecting
  nothing. It is accepted only because the unported example recipes still spell it on every
  step; anything else is refused with an error saying so. It is in neither
  `STEP_TYPE_REQUIRED` nor `STEP_TYPE_DEFAULTS`, so no new recipe needs it, and it goes when
  those recipes are ported.
- **Also dropped:** the old project-wide `rglob` search for the module file — a heuristic
  with a bare `except` at its heart. Here the recipe says where its code is: a path
  resolved against the recipe's own folder, or a dotted import name.

### 2.3 `UserInteractionStep` → `UserInteraction` — done

`user_interaction_step.py`. Prompt the operator with a message, an optional image and a
list of buttons; the chosen key comes back as the step's output. Demo:
`resources/recipes/userinteractionstep_demo.yml` (GUI mode — the CLI declines every
question).

**The question sits directly on the step**, the way a Wait's `wait_time` does and not the
way a PythonModule's `input_mapping` does. Only the *answer* goes through a mapping:

```yaml
- steptype: UserInteraction
  step_name: Check the LED
  message: Is the red LED lit?
  options: [Yes, No]
  image_path: led.png        # optional, resolved against the recipe's folder
  output_mapping:
    output: {type: equals, value: Yes}
```

The step returns the chosen string, which `Step.run()` wraps as `{"output": choice}` — so
`equals` judges it, `local`/`global` store it, and no output type was added for it.

**The `ask` seam.** The step layer reached CORE through `Runtime.emit` alone, which is
one-way. `Runtime` now carries a third seam, `ask`, which the Sequencer fills with
`ask_operator()` — the one place that knows the ordering:

```python
def ask_operator(self, request):            # sequencer.py
    self.pending.start(request.request_id)  # register BEFORE sending
    self.core.send(request)
    return self.pending.wait(request.request_id, should_abort=lambda: self.stop_requested)
```

A step just calls `runtime.ask(request)` and cannot get it wrong. The rule that stays
load-bearing: **`ask` may only be called from the sequence thread.** The answer is
delivered by `deliver_response()` on the *event loop* thread, so a caller on the event
loop would block the very loop that has to wake it. `UserWriteStep` and `UserLoadingStep`
use the same seam.

**Waiting is a poll, not one long sleep.** `PendingRequests.wait()` surfaces every
`POLL_INTERVAL_S` (100 ms) to look at `should_abort`. Without it, pressing Stop with a
question on screen would hang for the whole 300 s timeout: `should_stop` is only read
*between* steps, and the GUI's own escape hatch — cancelling open prompts on
`RunFinished` — cannot fire until the blocked step returns. The loop lives inside
`wait()` because the slot is registered once and cancelled once; a caller looping on short
waits of its own would cancel its own request on the first empty turn.

**Not answering is an ERROR.** One rule, no special cases: the timeout ran out, the
operator pressed Cancel, or the run was stopped. The exception text distinguishes them
because that is worth reading; the verdict does not change. `Step.run_steps` carries on to
the next step (§3.1), so one unanswered question does not throw the rest of the sequence
away.

**Two things the step refuses at load time**, rather than letting them fail quietly:

- `options: []` — with no buttons the operator cannot answer, so the step could only ever
  time out;
- an `image_path` that does not exist — the GUI's handling of a bad path is to fall back
  to the idle logo (`interaction_panel._refresh_visual`), which would leave the operator
  looking at the wrong picture with nothing said about it. The check happens before the
  request is sent, and the resolved path is made **absolute** because the HMI is another
  process and resolves nothing.

**The Cancel button is the GUI's, not the recipe's.** Every prompt grows one beyond the
recipe's own options (`interaction_panel.CANCEL_LABEL`), so an operator is never stuck in
front of a question they cannot answer. It emits `cancelled`, not `response_given`, so a
recipe that happens to offer its own "Cancel" option stays distinct from it; the signal
lands on `CenterContent.cancel_pending()`, which is the same decline path `RunFinished`
and a superseding prompt already used.

Not carried over from the old type: `trigger_response` / `module` / `action_type` /
`method_name` (that was `UserRunMethodStep` behaviour — §2.6), and the `cancel_key`
global convention.

### 2.4 `UserWriteStep` — to be implemented

Two modes in the old type, selected by which button the operator pressed:

- **`wrt`** — a text dialog; the typed string is stored in the variable named by
  `output_mapping.output`. Broken in the old engine: the text was immediately overwritten
  by the literal string `"wrt"` when `process_outputs` ran (recipe_guide §16 F14). The port
  fixes this by construction — do not reproduce it.
- **`ID`** — a serial-port dialog (port, baudrate, `*IDN?`), writing the hard-coded locals
  `serial_ID`, `serialport`, `baudrate`.

`SerialNumberRequest` / `SerialNumberResponse` and the GUI's serial page already exist for
the second mode. The old type also required the globals `cancel_key`, `wrt_key`, `ID_key`
to name its own buttons — that convention is not worth keeping.

### 2.5 `UserLoadingStep` — to be implemented

The operator picks a file; the path is stored per `file_save_location`.

This is the one that carries a **real design problem**, not just work. The old dialog
pushed a *second* value onto the same response queue — the button first, the chosen path
after it. Nothing in the new message layer models that: a request has exactly one
response, joined by `request_id`. Each follow-up has to become **its own request/response
pair** (recorded as a roadmap §1.1 TODO). Settle that before implementing.

Also from the old type: `type: local` in `file_save_location` still wrote a **global**
(§16 F15). Not a behaviour to port.

### 2.6 `UserRunMethodStep` — deprecated, to be dropped

Prompt the operator, then call a method on a module when a chosen button matched
`trigger_response`. **Dropped: a `UserInteractionStep` followed by a `PythonModuleStep`
says the same thing in a recipe, in two lines instead of one type.**

Consequence: the `method` **input type** (identical to `direct`, used only to carry
`method_name` here) is dropped with it and stays out of `process_inputs()`.

### 2.7 `SSHConnectStep` / `SSHCloseStep` — not step types; move into the framework

Open a paramiko session and close it. Both read **globals only** — `host`, `user`,
`password`, `private_key`, `port` — never `input_mapping`, and `SSHConnectStep` published
the live client as the global `ssh_client` for later steps to take as an input.

**Decision: SSH belongs to the framework, not to the recipe.** A connection is
infrastructure the framework owns and manages; making the operator write a connect step
and remember a matching close step in `teardown_steps` is the old design's workaround for
not having anywhere else to put it. So: no `SSHConnect` / `SSHClose` entries in
`STEP_TYPES`.

Open for the implementation session:

- **Where it lands** — `hardware_layer/hal.py` is the obvious candidate (it is an empty
  stub today), but a plain framework service is also defensible. Not decided.
- **Credentials** — they move into the Config Handler. A plaintext SSH password currently
  sits in `resources/recipes/comprehensive_recipe.yml:20` (§16 F22).
- **Lifecycle** — whatever owns the session has to close it on abort and on shutdown, which
  is exactly what the old `teardown_steps` rule was standing in for.
- **A live paramiko client cannot cross a process boundary.** It works today because the
  whole engine is one process; nothing about it may ever be put on the HMI link.

### 2.8 `SequenceStep` — to be dropped

Run another sequence as a single step. **Dropped.**

Note what this leaves behind, so it is not mistaken for an oversight:

- `step.step.run_sequence()` is deliberately free of threads and queues, and the emission
  model (a step emits its own events through `Runtime.emit`) was designed so a nested
  sequence would report through the channel it already holds. That shape is still correct
  for the top-level sequence; it simply has no second caller now.
- `StepResult.subresults` was kept for this and for `IndexedStep`. With both dropped,
  **nothing writes it** — drop the attribute too when the decision is implemented, or the
  next reader will assume nesting is coming.
- The old engine wrapped `main_sequence` in a synthetic `SequenceStep`. The new Sequencer
  calls the sequence body directly instead, so nothing depends on it.
- The old type was itself unfinished: sub-sequences were parsed and then never referenced
  again (recipe_guide §12).

### 2.9 `IndexedStep` → `Indexed` — done, in a different shape

The requirement was kept, the mechanism replaced: **run the same step N times with
different parameters**, and parameterize the *expected result* with them.

`indexed_step.py`. `steptype: Indexed` is the only steptype that **never reaches the
registry and never runs** — the parser expands it into one ordinary step mapping per
parameter set, and everything downstream deals with plain steps:

```yaml
- steptype: Indexed
  step_name: Add numbers
  template:
    steptype: PythonModule
    module: example_tests.py
    method_name: add
  parameter_sets:
    - inputs: {a: 1, b: 1}
      expect: {sum: 2}
    - inputs: {a: 2, b: 3}
      expect: {sum: 5}
```

- **Row-wise sets, not the old column-wise `indexed: true` lists.** One set is one
  coherent case, so the old "iterate to the length of the shortest list, silently
  truncating" cannot happen.
- `inputs` are direct values; `expect` are `equals` checks. Terse on purpose — a set is a
  test case and should read like a table row. Anything needing `range`, `passfail`,
  `local` or `global` goes on the `template`, which takes the full mapping vocabulary;
  set entries are merged over it, key by key.
- Generated steps are named after their parameters — `Add numbers [a=2, b=3]` — so a
  failed row explains itself without opening the recipe. A set with no `inputs` falls back
  to `Add numbers 1/10`.
- Each generated step gets **its own UUID**, so the step table pre-fills with N rows, the
  CSV gets N rows, and **no new message type was needed** — nothing in the message layer,
  the Sequencer or either frontend knows the steptype exists.
- Refused, rather than silently ignored: `id`, `input_mapping` and `output_mapping` on the
  `Indexed` step itself (they would apply to nothing, or to N steps at once), an `Indexed`
  step as its own `template`, an empty `parameter_sets`, and an unknown key in a set.
  `skip: true` on it skips every generated step.

**The cost, and it is the real one:** N is fixed when the recipe loads. "Run once per
device the previous step found" is not expressible and would need a runtime construct.
Also gone with the old wrapper: the group-level aggregate verdict (`max()` over
iterations) — each generated step now stands on its own, and the sequence verdict
aggregates them like any other steps. F25 (the wrapper's `output_mapping` discarded) cannot
recur, because there is no wrapper.

Where the rules live: `STEP_TYPE_REQUIRED["indexed"]` in `recipe/rules.py`, listed in
`EXPANDED_STEP_TYPES` so the registry-vs-rules pinning test knows it is parse-time only;
the shape checks in `indexed_step.check_indexed_step()`, called by `recipe/validator.py`,
which also validates the `template` as the step it will become; the expansion itself in
`recipe_parser._expand_indexed_steps()`, between defaults and build.

---

## 3. Cross-cutting machinery

### 3.1 `continue_on_error` — done

**Written on a step, and nowhere else. Default `True`. A recipe need not mention it.**

```yaml
- steptype: PythonModule
  step_name: Power up the DUT
  module: bench.py
  method_name: power_on
  continue_on_error: false     # if this errors or fails, the run ends here
```

Two halves, landed in two changes:

**The default** (2026-09-01, with the `UserInteraction` port that needed it):
`Step.run_steps()` does not end the sequence on `ResultType.ERROR`. A failing step is
recorded and the sequence carries on, and the run still ends ERROR through the ordinary
aggregate rather than by abandoning what was left. One bad step does not decide for the
other nineteen — which is exactly what an unanswered prompt in the middle of a long recipe
must not do.

**The flag** (2026-09-01). `continue_on_error: false` on a step means: when *that* step
comes back `ERROR` **or** `FAIL`, the run ends there. Four things about it are decisions,
not details:

- **A `FAIL` halts too, not only an `ERROR`.** This is the answer to §16 **F7** — *"should a
  FAIL stop a sequence? Today only ERROR does"* — which the old engine left open and
  undocumented. The default is unchanged by it: a failing measurement still never halts
  anything on its own, because a failing DUT should still be fully characterised. The flag
  is the only thing that makes a FAIL matter to control flow.
- **Per step and nowhere else.** No header field, no `globals.continue_on_error`. Those two
  were F1 (the header form was inert, and four of five example recipes used it) and F8 (the
  global form overrode everything and otherwise leaked forward from whichever step last
  wrote it). One place to write it, one place to read it.
- **Every step that never ran is recorded `SKIP`**, with a reason on its `error_info` —
  `"Not run: the sequence stopped at step 'X'."`. `run_steps()` runs the remainder through
  `Step.run(runtime, skip_reason=…)`, which takes the same branch `skip: true` takes: the
  body is not entered, but the full `StepStarted`/`StepFinished`/`StepExecuted` trio is
  emitted. So the step table settles every pre-filled row and the CSV has a row per step,
  however the run ended. `SKIP` is the lowest `ResultType`, so this cannot change what the
  sequence aggregates to. **The operator's Stop does the same**, for the same reason, with
  its own reason text — before this, both simply dropped the remaining steps and left their
  rows pending forever.
- **Ignored in teardown.** `run_sequence()` passes `run_to_end=True`, which disables both
  early exits: cleanup runs after an abort *and* after a halt, and one failing cleanup step
  does not skip the rest of the cleanup. That parameter replaced `honour_stop` — one name
  for one concept, rather than two booleans always set together.

**A halt is not a Stop.** It deliberately never touches the Sequencer's `stop_requested`,
so `execute_sequence()`'s `if self.stop_requested: result = ResultType.STOP` does not fire
and `RunFinished` carries the real aggregate — `ERROR` or `FAIL`. Borrowing that flag would
leave the operator unable to tell "I pressed Stop" from "a critical step failed".
`test_a_step_that_halts_the_run_reports_error_not_stop` pins it.

On an `Indexed` step the flag goes on the **wrapper**, where it carries to every generated
row exactly as `skip` does (`indexed_step._generated_step`).

### 3.2 `critical` — dropped

`Step.__init__` took `critical` and kept it; nothing ever read it. It is **gone**
(2026-09-01), removed in the change that implemented `continue_on_error`.

It only made sense in the old engine's shape. There `continue_on_error` lived on the
*runtime* — effectively run-wide — and `critical` was the per-step override of it:

| old `continue_on_error` (run-wide) | old `critical` (per step) | on ERROR |
|---|---|---|
| false | false | stop |
| false | true | stop |
| true | false | continue |
| true | true | **stop** |

Two knobs because one was global and one was local. With `continue_on_error` itself per
step there is no global setting left for `critical` to override, so `critical: true` and
`continue_on_error: false` became one statement spelled two ways.

A recipe that still writes `critical:` gets a `TypeError` from the constructor, which
`recipe_parser._build_step_or_refuse()` turns into a `RecipeError` naming the sequence, the
step and the key. Loud, and the fix is a rename.

### 3.3 Dropped with their types

- **`method` input type** — went with `UserRunMethodStep` (§2.6).
- **`indexed: true`** — the old per-input flag is gone; `parameter_sets` replaced it (§2.9).
- **`__result` / implicit `passthrough`** — the structural types' aggregate output. Gone:
  `SequenceStep` was dropped and `Indexed` no longer aggregates anything.

---

## 4. Adding a step type — the three edits

1. The class in `step/<name>_step.py`: subclass `Step`, override `_step()` and nothing else.
   A type that has to ask the operator something calls `runtime.ask(request)` from inside
   `_step()` — never a queue, never `PendingRequests` directly (§2.3).
   The constructor arguments *are* the type's YAML keys, so an unknown key is a `TypeError`
   at load time.
2. Its entry in `STEP_TYPES` (`step/registry.py`), keyed **lowercase** — the YAML spelling
   is case-insensitive and drops the class's `Step` suffix (`Wait`, not `WaitStep`).
3. Its required and optional fields in `STEP_TYPE_REQUIRED` / `STEP_TYPE_DEFAULTS`
   (`recipe/rules.py`). A unit test pins those keys against the registry's, so a type
   registered in only one of the two places fails the suite.

**Only what is genuinely the type's own goes in `STEP_TYPE_DEFAULTS`.** The fields every
step accepts whatever its type — `description`, `skip`, `continue_on_error` — are the
common arguments of `Step.__init__` and are declared once, in `STEP_COMMON_DEFAULTS`. A new
type gets them for free and must not repeat them; the old format's per-type
`continue_on_error` is why putting it on the wrong one of the ten types was a load-time
`TypeError` (§16 F9).

Then document it in `recipe_guide.md` §10 and update the table in §1 above.

---

## 5. The two naming changes, when reading an old recipe

- YAML names **drop the `Step` suffix**: `Wait`, `PythonModule`.
- They are **genuinely case-insensitive**. The old factory lower-cased eight names in a
  `match` and forgot the two SSH ones, so those only ever worked in exact CamelCase.

---

*Update this file the way the roadmap is updated: in the same change that changes the
module.*
