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
never run). Three are ported, one of those only partly. Three more are wanted, four are not.

| # | Old class | YAML today | Status | Decision |
|---|---|---|---|---|
| 1 | `WaitStep` | `Wait` | ✅ **done** | — |
| 2 | `PythonModuleStep` | `PythonModule` | 🟡 **partial** | finish the two missing action types |
| 3 | `UserInteractionStep` | — | ❌ missing | **to be implemented** |
| 4 | `UserWriteStep` | — | ❌ missing | **to be implemented** |
| 5 | `UserLoadingStep` | — | ❌ missing | **to be implemented** |
| 6 | `UserRunMethodStep` | — | ❌ missing | **deprecated — to be dropped** |
| 7 | `SSHConnectStep` | — | ❌ missing | **not a step type — moves into the framework** |
| 8 | `SSHCloseStep` | — | ❌ missing | **not a step type — moves into the framework** |
| 9 | `SequenceStep` | — | ❌ missing | **to be dropped** |
| 10 | `IndexedStep` | `Indexed` | ✅ **done, reshaped** | replaced by load-time expansion — §2.9 |

Decisions recorded 2026-09-01. Three types to port, one to finish, four that will never
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

### 2.2 `PythonModuleStep` → `PythonModule` — partial

`python_module_step.py`. The workhorse: load a module, call into it, `input_mapping`
passed as keyword arguments.

- **Ported:** `action_type: method`.
- **Missing:** `read_attribute` (needs input `attribute_name`) and `write_attribute`
  (needs `attribute_name` + `attribute_value`).
- **Deliberately not ported:** the old project-wide `rglob` search for the module file — a
  heuristic with a bare `except` at its heart. Here the recipe says where its code is:
  a path resolved against the recipe's own folder, or a dotted import name.

### 2.3 `UserInteractionStep` — to be implemented

Prompt the operator with a message, an optional image and a list of buttons; the chosen
key comes back as the step's output.

Most of this already exists — **what is missing is the sender**:

| Piece | State |
|---|---|
| `UserPromptRequest` / `UserPromptResponse` | ✅ in `messages/run_events.py`, joined by `request_id` |
| CORE relay, both directions | ✅ `core.py` — request out, answer back to the Sequencer |
| `HmiClient.ask_user()` / `answer_user_prompt()` | ✅ both frontends; the GUI has the prompt page, tested |
| `Sequencer.deliver_response()` | ✅ wakes the waiter by `request_id` |
| `PendingRequests` (`messages/blocking_messages.py`) | ✅ built, and **nothing calls `start()`/`wait()`** |
| a step that asks | ❌ **this type** |

The waiting shape is fixed and must be followed, or the engine deadlocks:

```python
self.pending.start(request_id)                  # register BEFORE sending
runtime.emit(UserPromptRequest(request_id, ...)) # ask
answer = self.pending.wait(request_id)           # blocks the *sequence* thread only
```

The sequence thread blocks; the Sequencer's event loop keeps turning and is what delivers
the answer. A step that waits on the event-loop thread can never be answered.

Open: the step layer reaches CORE through `Runtime.emit` alone and has no handle on
`PendingRequests`. Asking needs a third seam on `Runtime` (an `ask()` callable the
Sequencer fills in) — decide that before writing the first prompting type, because all
three of them need it.

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

## 3. Cross-cutting machinery the ported types need

### 3.1 `continue_on_error` — to be implemented in recipe parsing

**Decision: the parser owns it. Default `True`. A recipe need not mention it.**

So a recipe that says nothing gets "an ERROR in one step does not abandon the rest of the
sequence", and a step or a recipe may say otherwise explicitly.

What has to change, and what it costs:

- `recipe/rules.py` grows the field and its default; `recipe_parser.py` fills it in, so
  every `Step` arrives with the flag resolved and **no step type parses it itself**. The
  old engine had three disagreeing sources of truth for this (§16 F8) — one is the point.
- `Step.run_steps()` (`step.py`) currently **breaks the loop on `ResultType.ERROR`**, the
  old default. Defaulting the flag to `True` inverts that: the loop continues past an
  ERROR unless the step says not to. This is the behaviour change to be aware of — a bad
  step no longer stops the run by itself.
- The teardown loop already runs with `honour_stop=False` and is unaffected.
- Where the flag lives — per step, per sequence, per recipe, or all three — is not settled
  here. The old format accepted it on 8 of the 10 step types and put it on the step.

### 3.2 `critical` — parsed, stored, never consulted

`Step.__init__` takes `critical` and keeps it. Nothing reads it. Decide what it means when
`continue_on_error` lands: the two are the same conversation, and a step that is `critical`
in a recipe whose default is now "continue" is the obvious way to say "except this one".

### 3.3 Dropped with their types

- **`method` input type** — went with `UserRunMethodStep` (§2.6).
- **`indexed: true`** — the old per-input flag is gone; `parameter_sets` replaced it (§2.9).
- **`__result` / implicit `passthrough`** — the structural types' aggregate output. Gone:
  `SequenceStep` was dropped and `Indexed` no longer aggregates anything.

---

## 4. Adding a step type — the three edits

1. The class in `step/<name>_step.py`: subclass `Step`, override `_step()` and nothing else.
   The constructor arguments *are* the type's YAML keys, so an unknown key is a `TypeError`
   at load time.
2. Its entry in `STEP_TYPES` (`step/registry.py`), keyed **lowercase** — the YAML spelling
   is case-insensitive and drops the class's `Step` suffix (`Wait`, not `WaitStep`).
3. Its required and optional fields in `STEP_TYPE_REQUIRED` / `STEP_TYPE_DEFAULTS`
   (`recipe/rules.py`). A unit test pins those keys against the registry's, so a type
   registered in only one of the two places fails the suite.

Then document it in `recipe_guide.md` §10 and update the table in §1 above.

---

## 5. The two naming changes, when reading an old recipe

- YAML names **drop the `Step` suffix**: `Wait`, `PythonModule`.
- They are **genuinely case-insensitive**. The old factory lower-cased eight names in a
  `match` and forgot the two SSH ones, so those only ever worked in exact CamelCase.

---

*Update this file the way the roadmap is updated: in the same change that changes the
module.*
