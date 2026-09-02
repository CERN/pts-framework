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
never run). Five are ported. One more is wanted, four are not.

| # | Old class | YAML today | Status | Decision |
|---|---|---|---|---|
| 1 | `WaitStep` | `Wait` | ✅ **done** | — |
| 2 | `PythonModuleStep` | `PythonModule` | ✅ **done** | methods only; the attribute actions are dropped |
| 3 | `UserInteractionStep` | `UserInteraction` | ✅ **done** | the first type that blocks on a person |
| 4 | `UserWriteStep` | `UserWrite` | ✅ **done, one mode of two** | the `wrt` text dialog; the `ID` serial-port mode is dropped — §2.4 |
| 5 | `UserLoadingStep` | — | ❌ missing | **to be implemented** |
| 6 | `UserRunMethodStep` | — | ❌ missing | **deprecated — to be dropped** |
| 7 | `SSHConnectStep` | — | ❌ missing | **not a step type — moves into the framework** |
| 8 | `SSHCloseStep` | — | ❌ missing | **not a step type — moves into the framework** |
| 9 | `SequenceStep` | — | ❌ missing | **to be dropped** |
| 10 | `IndexedStep` | `Indexed` | ✅ **done, reshaped** | replaced by load-time expansion — §2.9 |

Decisions recorded 2026-09-01; `UserWrite` landed 2026-09-02. One type left to port, four that will never
appear in `STEP_TYPES` — plus `Indexed`, which is in the rules but never in the registry
because it is gone before anything is built.

---

## 2. What each one is, and what its port needs

### 2.1 `WaitStep` → `Wait` — done

`wait_step.py`. Sleeps. The one deliberate change from the old type: `wait_time` is a
**direct field on the step**, not an `inputs` entry — a fixed wait has no inputs to
resolve and no outputs to judge, so it carries neither mapping. Returns `{}`, so the
verdict is always `DONE`.

Known gap: the sleep is one `time.sleep()`, so it does not honour `runtime.should_stop()`.
The framework contract only promises a stop at the next *step* boundary, so this is a
courtesy, not a defect — but a 60 s wait delays an abort by up to 60 s.

### 2.2 `PythonModuleStep` → `PythonModule` — done

`python_module_step.py`. The workhorse: load a module, call into it, `inputs`
passed as keyword arguments.

- **Calling a method is the whole type.** `read_attribute` and `write_attribute` are
  **dropped** (decision 2026-09-01), not deferred: a recipe that needs an attribute writes
  a one-line getter or setter beside it and calls that, which keeps one way of reaching
  Python code instead of three.
- **`action_type` is gone** (2026-09-02). It selected between the three actions and two of
  them no longer exist, so the key selected nothing. It was kept for a while as a tolerated
  no-op so the unported example recipes would still load; that is not a reason to carry a
  key. A recipe that still writes it now gets a `RecipeError` naming it, like any unknown
  key.
- **Also dropped:** the old project-wide `rglob` search for the module file — a heuristic
  with a bare `except` at its heart. Here the recipe says where its code is: a path
  resolved against the recipe's own folder, or a dotted import name.

### 2.3 `UserInteractionStep` → `UserInteraction` — done

`user_interaction_step.py`. Prompt the operator with a message, an optional image and a
list of buttons; the chosen key comes back as the step's output. Demo:
`resources/recipes/userinteractionstep_demo.yml` (GUI mode — the CLI declines every
question).

**The question sits directly on the step**, the way a Wait's `wait_time` does and not the
way a PythonModule's `inputs` entries do. Only the *answer* goes through a mapping:

```yaml
- steptype: UserInteraction
  step_name: Check the LED
  message: Is the red LED lit?
  options: [Yes, No]
  image_path: led.png        # optional, resolved against the recipe's folder
  outputs:
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
loop would block the very loop that has to wake it. `UserWriteStep` uses the same seam,
and `UserLoadingStep` will.

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

### 2.4 `UserWriteStep` → `UserWrite` — done

`user_write_step.py`. Ask the operator to type a line of text; what they typed is the
step's output. The free-text half of the pair whose other half is `UserInteraction`,
and it shares that type's shape exactly — `message` and `image_path` directly on the
step, only the answer through a mapping. Demo:
`resources/recipes/Development_recipes/userwritestep_demo.yml` (GUI mode — the CLI
declines every question).

```yaml
- steptype: UserWrite
  step_name: get_serial_number
  message: Scan or type the serial number of the unit under test.
  image_path: label_location.png     # optional, resolved against the recipe's folder
  outputs:
    output: {type: global, global_name: serial_number}
```

**What the two prompting types share lives in `operator_prompt.py`**, as two plain
functions rather than a base class, so §4's rule still holds — a step type subclasses
`Step`, overrides `_step()` and nothing else. `resolve_image_path()` is the absolute-path
rule of §2.3; `ask_or_raise()` is its "not answering is an ERROR" rule. Both types call
both, so neither can drift.

**There is no `allow_empty` field.** The GUI keeps OK disabled while the field is empty
(`interaction_panel.set_text_prompt`), so the only answers that exist are some text and
Cancel. One less key in every recipe that wants the obvious behaviour.

**The old type's two modes, and what became of them:**

- **`wrt`** — the text dialog. This is the port. The old engine's defect (the typed
  text immediately overwritten by the literal string `"wrt"` when `process_outputs`
  ran — recipe_guide §16 F14) cannot recur: there is no button whose label competes
  with the answer, because there are no buttons.
- **`ID`** — the serial-port dialog (port, baudrate, `*IDN?`). **Dropped**
  (decision 2026-09-02). It is instrument identification over RS-232, not a person
  typing, and it belongs where the rest of the instrument access is going: a
  `PythonModule` step calling a driver that returns the IDN string, which the recipe
  stores in a global exactly as it stores the serial number. The old type also
  required the globals `cancel_key`, `wrt_key` and `ID_key` to name its own buttons —
  a convention that goes with it.

**The framework asks for nothing in particular.** `SerialNumberRequest` /
`SerialNumberResponse` and the GUI's serial page are **deleted** (2026-09-02). They
meant the engine itself believed every unit under test has a serial number and went
and fetched it. Asking is the recipe's job; the framework supplies the prompt and the
global scope. What is left of the coupling is one recipe-header field —
`report_metadata`, defaulting to `("serial_number",)` — which names the globals the
Report stamps on every row of `report.csv`, shows in `report.html`'s header, appends
to the run folder's name and puts in the GUI's top bar. The convention itself lives in
`resources/roadmap/best_practices.md`: a step named `get_serial_number` writing the
`serial_number` global.

### 2.5 `UserLoadingStep` — to be implemented

The operator picks a file; the path is stored per `file_save_location`.

This is the one that carries a **real design problem**, not just work. The old dialog
pushed a *second* value onto the same response queue — the button first, the chosen path
after it. Nothing in the new message layer models that: a request has exactly one
response, joined by `request_id`. Each follow-up has to become **its own request/response
pair** (recorded as a roadmap §1.1 TODO). Settle that before implementing.

Also from the old type: `type: local` in `file_save_location` still wrote a **global**
(§16 F15). Moot now — `local` no longer exists (§3.5), there is one scope.

### 2.6 `UserRunMethodStep` — deprecated, to be dropped

Prompt the operator, then call a method on a module when a chosen button matched
`trigger_response`. **Dropped: a `UserInteractionStep` followed by a `PythonModuleStep`
says the same thing in a recipe, in two lines instead of one type.**

Consequence: the `method` **input type** (identical to `direct`, used only to carry
`method_name` here) is dropped with it and stays out of `process_inputs()`.

### 2.7 `SSHConnectStep` / `SSHCloseStep` — not step types; move into the framework

Open a paramiko session and close it. Both read **globals only** — `host`, `user`,
`password`, `private_key`, `port` — never the step's own arguments — and `SSHConnectStep` published
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
- Refused, rather than silently ignored: `id`, `inputs` and `outputs` on the
  `Indexed` step itself (they would apply to nothing, or to N steps at once), an `Indexed`
  step as its own `template`, an empty `parameter_sets`, and an unknown key in a set.
  `skip: true` on it skips every generated step.

**The cost, and it is the real one:** N is fixed when the recipe loads. "Run once per
device the previous step found" is not expressible and would need a runtime construct.
Also gone with the old wrapper: the group-level aggregate verdict (`max()` over
iterations) — each generated step now stands on its own, and the sequence verdict
aggregates them like any other steps. F25 (the wrapper's `outputs` discarded) cannot
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
- **The operator's step lines are written here**, in `run_steps()` and `log_step_outcome()`,
  because this is the only place that knows a step's position in its list, its verdict and
  how long it took: `Step 4/12 'read_voltage' FAIL (1.1 s).` The `phase` argument is only the
  word those lines start with, so a teardown step reads `Teardown step 1/2 'power_off'`
  rather than as a second step 1; it changes nothing about how a step is run. A `FAIL` logs
  at INFO - a failing DUT is a test result, not a software fault - and only a step that could
  not run at all writes an `ERROR`. `logger/logger.md` is the authority on all of this.
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
- **`__result` and the `passthrough` output type** — the structural types' aggregate
  output, propagated as the step's own verdict. Gone: `SequenceStep` was dropped and
  `Indexed` no longer aggregates anything, so nothing produced a `ResultType` to
  propagate. `pass` took its place in the vocabulary — same idea of an output that is
  not a measurement, without the propagation (§3.4).

### 3.4 `inputs` and `outputs` — done

The two mappings every step type may carry. They were `input_mapping` and
`output_mapping`; the names are now **`inputs` and `outputs`** (2026-09-02), because the
`_mapping` suffix named the implementation and the shorter word names the thing.

**A bare value under `inputs` is the value.** That is the whole of the second change:

```yaml
inputs:
  a: 2                                  # a literal - the common case
  b: {type: global, global_name: port}  # the only other place a value comes from
outputs:
  sum: {type: equals, value: 5}
```

**There is no `direct` type and no `value` key on an input** (dropped 2026-09-02, with
the rest of the second spellings): `{value: 2}` and `{type: direct, value: 2}` said what
`a: 2` says, and one way is enough. So an input entry is a literal or a mapping, and a
mapping can only be `global` — which is why it must name its type: there is no default
left to fall back to. `value` is still an `equals` entry's key on the **outputs** side;
that is a different thing and it stays.

The `outputs` vocabulary is `passfail`, `equals`, `range` (they judge), `pass` (this
output is not a measurement — the verdict is DONE whatever came back) and `global`
(store it, leave the verdict alone).

Two consequences worth knowing:

- **`Indexed` generates the short form.** `_generated_step()` writes `inputs: {a: 1}`
  rather than a configuration mapping, so a generated step's YAML fragment in the hover
  panel reads exactly like a hand-written one.
- **A mapping is always a configuration**, so an argument whose value is genuinely a dict
  cannot be written directly. Both the validator and `process_inputs()` say so in as many
  words. It is the one thing the short spelling costs, and it is stated rather than
  discovered.

**Checked when the recipe loads** (§3.5's removal is why): every `inputs`/`outputs`
entry names a `type` the engine knows, and carries the keys that type needs. A typo -
or the dropped `local` - is a `RecipeError` naming the step and the entry, instead of
a run that dies at step nine. The vocabulary is `rules.INPUT_TYPES` /
`rules.OUTPUT_TYPES`.

**What is still not checked when a recipe loads:** that `method_name` exists on the
module, that the argument names match its signature, and that a `global_name` a step reads
was ever written. All three fail as a `StepResult(ERROR)` on the bench, with tests in
`test_step.py` pinning that. Moving them to load time is a roadmap TODO.

### 3.5 One variable scope — done

**`globals` is the only scope, and it lasts the whole run.** The per-sequence `locals`
frame was dropped (2026-09-02) along with the `local` input and output types, the
`locals:` sequence key, and `Runtime`'s `local_stack` / `push_locals` / `pop_locals` /
`get_local` / `set_local`.

The reason it went: a local was **global in reach and merely shorter-lived**. Every step
in the running sequence could read and write it exactly as it could a global; all the
scope bought was that the value vanished when the sequence ended. That is a distinction a
recipe author had to think about on every stored value, for no protection — two names for
one idea. With `SequenceStep` dropped (§2.8) the stack never held more than one frame
either, so the machinery was carrying a case that could not arise.

What is left is deliberately two things and not three: **`globals` for anything that
outlives a step**, and a step's own **`inputs`/`outputs`** for everything else. A step
that wants a value from an earlier one names a global; a step that only needs a value for
itself takes it as an input.

The cost, stated plainly: a global written by one sequence is visible to the next, and
nothing clears it between sequences of the same run. Nothing in the old `locals` gave
real isolation either — F16 was exactly a re-run seeing the previous run's writes — but
if isolation is ever wanted it has to be designed, not inherited.

---

## 4. Adding a step type — the three edits

1. The class in `step/<name>_step.py`: subclass `Step`, override `_step()` and nothing else.
   A type that has to ask the operator something calls `runtime.ask(request)` from inside
   `_step()` — never a queue, never `PendingRequests` directly (§2.3) — and reaches for
   `operator_prompt.ask_or_raise()` and `resolve_image_path()` rather than repeating them
   (§2.4).
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
