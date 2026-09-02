<!-- SPDX-FileCopyrightText: 2025 CERN <home.cern> -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# PyPTS Recipe Guide

**Purpose.** One document that describes what a recipe *is*, what the old engine *actually
does* with it (not what the docs claim), where the three existing rule sets disagree, and
what the new framework should adopt. Written to serve two jobs:

1. **Review the recipe rules** — §16 is the findings list, each item with file:line evidence.
2. **Build recipes up for the new framework** — §17 is the proposed format and the open
   questions that need your decision.

**Status of the sources this is derived from (read 2026-08-11, branch `architecture_refactor`):**

| Source | Path | Authority |
|---|---|---|
| Old engine — loader & execution | `src/pypts/old_code/recipe.py` (fully commented out) | **behavioural source of truth** |
| Old engine — step types | `src/pypts/old_code/steps.py` (fully commented out) | **behavioural source of truth** |
| GUI side of user interaction | `src/pypts/old_code/gui.py` (commented out) | button/response semantics |
| Report consumption | `src/pypts/old_code/report.py` (commented out) | CSV columns |
| Validation rules | `src/pypts/helper_applications/recipe_verificator/{recipe_rules,verify_recipe}.py` | **live code** (import currently broken) |
| A *third* rule set | `src/pypts/helper_applications/recipe_creator/recipe_creator.py:795-800` | live code, disagrees with the above |
| Written spec | `docs/source/yaml_format.rst` | aspirational — diverges from code in ≥6 places |
| Examples | `resources/recipes/*.yml`, `resources/example_commented_recipes/` | mixed quality; not runnable (§16 F24) |
| New framework | `recipe/recipe.py` (0 bytes), `step/__init__.py` (0 bytes), `sequencer.run_sequence()` = `pass` | nothing ported yet |

Throughout: **[CODE]** = verified behaviour of the old engine, **[DOC]** = claim in
`yaml_format.rst`, **[VAL]** = what the verificator enforces, **[PROPOSAL]** = my suggestion
for the new framework, not implemented anywhere.

---

## 1. The model in 30 seconds

A recipe is a **multi-document YAML file**:

```
document 1        recipe header   — name, version, main_sequence, globals
document 2..N     sequences       — each: locals + setup_steps / steps / teardown_steps
```

A **sequence** is an ordered list of **steps**. A **step** has a `steptype` (which Python class
runs it), an `input_mapping` (where its arguments come from: literal / local / global), and an
`output_mapping` (what to do with what it returned: store it, or judge it PASS/FAIL).

Two variable scopes: **globals** (whole recipe, one flat dict) and **locals** (one dict per
sequence, pushed/popped on a stack). Steps never talk to each other directly — they
communicate exclusively by writing and reading these variables.

Every step produces a `StepResult` with one `ResultType`. Results form a tree (a step can have
sub-results), and a parent's result is the **maximum severity** of its children.

```
Recipe
└── Sequence "Main"                       locals pushed
    ├── setup_steps   ─┐
    ├── steps          ├─ all executed as one flat list  (see §9 — surprising)
    └── teardown_steps ─┘ always executed, even after failure
```

---

## 2. File anatomy

```yaml
# SPDX headers (required by REUSE for every file in the repo)
name: My Recipe                 # <- document 1 begins; MUST be the first key (§16 F5)
version: 0.1.0
...
---                             # <- YAML document separator
sequence_name: Main             # <- document 2; MUST be the first key
...
---
sequence_name: Subsequence      # <- document 3
...
```

- Loaded with `yaml.safe_load_all` → **document order is significant**: doc 1 is the header,
  every following doc is a sequence, keyed by its `sequence_name`
  (`old_code/recipe.py:396-425`).
- A sequence document without `sequence_name` is **logged and silently skipped**
  (`recipe.py:417-419`) — the recipe still loads, and the missing sequence only fails later
  when something references it.
- Duplicate `sequence_name` → last one silently wins (dict assignment, `recipe.py:422`).
- Extension must be `.yml` or `.yaml` for the bulk validator to pick it up
  (`verify_recipe.py:101`).

---

## 3. Document 1 — the recipe header

### 3.1 Field reference

| Field | Type | Required by loader | Required by [VAL] | Actually used? |
|---|---|---|---|---|
| `name` | str | **yes** (`recipe.py:400`) | no — but must be the *first key* (`verify_recipe.py:170`) | report metadata, GUI title |
| `description` | str | **yes** | yes | GUI, `pre_run_recipe` event |
| `version` | str | **yes** | yes | report metadata |
| `globals` | dict | **yes** | yes | the global variable store |
| `main_sequence` | str | **yes** in practice (`recipe.py:428`, plain indexing → `KeyError`), but *absent* from the checked list | yes | the sequence that runs; **overrides the caller's choice** (§16 F3) |
| `test_package` | str | no (`.get(..., None)`) | no | Python package root for `PythonModuleStep` module resolution |
| `recipe_version` | str | no | no | **never read by any code** (§16 F2) |
| `continue_on_error` | bool | no | no | **never read at this level** (§16 F1) — only `globals.continue_on_error` is |
| `tags` | dict | — | — | commented out in the loader (`recipe.py:433`) |

### 3.2 `globals`

A flat `name: value` dict. Read with `runtime.get_global(name)` which is a **bare dict index**
(`recipe.py:292`) — a missing global raises `KeyError`, which surfaces as `ResultType.ERROR`
on the step that touched it. There is no default, no declaration check, no type.

Two globals are special:

- `serial_number` — **injected by the engine** at run start (`recipe.py:482-485`), either from
  the caller or by prompting the operator. Do not declare it; do rely on it.
  **Ported deliberately differently** (2026-09-02): the new engine injects nothing and asks
  nothing. A recipe captures it with a `UserWrite` step named `get_serial_number` and stores
  it in the `serial_number` global itself; the header's `report_metadata` is what makes the
  Report pick it up. See `best_practices.md` §1 and `step/step.md` §2.4 — the convention is
  kept, the injection is not.
- `continue_on_error` — if present, it is re-read before every step-boundary decision and
  **overrides all step-level settings** (`recipe.py:777`). See §9.

Several step types additionally *require* specific globals to exist — see the cheat sheet in §13.

### 3.3 `test_package` and module resolution

When `test_package` is set, `PythonModuleStep` resolves `module:` as a **package resource**
rather than a file path (`steps.py:303-377`):

```
root       = get_package_root(test_package)     if set, else get_project_root()
module     = find_resource_path(module, root)   recursive glob, skips EXCLUDE_DIRS
full name  = test_package + folder + stem       (or the site-packages path if importable)
import_module(full_name)
```

Practical rules:
- `module: example_tests.py` and `module: example_tests` both work (suffix is optional).
- Directory prefixes are unnecessary — resolution is a recursive search under the root.
- Every directory in the chain needs `__init__.py`.
- Resolution is **search-based, so an ambiguous filename resolves to whichever the glob hits
  first**. Unique module names are effectively mandatory.

---

## 4. Document 2..N — a sequence

```yaml
sequence_name: Main            # MUST be the first key [VAL]
description: What it does
parameters: {}                 # see below — parsed, never used
locals:                        # sequence-scoped variables
  target_value: '45'
outputs: {}                    # parsed, never used
setup_steps: []
steps: []
teardown_steps: []
```

All seven keys are read with plain indexing in `Sequence.__init__`
(`recipe.py:562-577`) → **every one is mandatory**; a missing key is a `KeyError` at load
time, and a `null` value (e.g. `locals:` with nothing after it) is a `TypeError` on first use.
[VAL] catches the null case as a fault, which is the one place validation earns its keep.

| Field | Type per [VAL] | Type per [DOC] | Reality |
|---|---|---|---|
| `parameters` | `dict` | `[]` list (`yaml_format.rst:118`) | **contradiction** — and irrelevant, the field is never read (§16 F16) |
| `outputs` | `dict` | `[]` list (`yaml_format.rst:119`) | same; the draft `subsequence_executions_draft.yml` uses a list |
| `locals` | `dict` | dict | consistent |
| `setup_steps` / `steps` / `teardown_steps` | `list` | list | consistent |

**Local scope semantics** (`recipe.py:273-289`):
- `push_locals(self.locals)` pushes **the parsed dict itself, not a copy** → mutations survive
  the sequence, so running the same sequence twice starts from the first run's end state
  (§16 F16).
- `get_local`/`set_local` only ever touch `local_stack[-1]` → a subsequence **cannot** see its
  caller's locals. That is correct isolation, and it is the only isolation there is.

---

## 5. A step — common fields

```yaml
- steptype: PythonModuleStep     # required, selects the class
  step_name: Measure 3V3 rail    # required, shown in GUI + report
  description: ...               # required by [VAL], optional in code
  id: my-stable-id               # optional; defaults to a fresh uuid4
  skip: false                    # optional
  critical: false                # optional
  continue_on_error: false       # optional — but NOT accepted by every steptype (§16 F9)
  input_mapping: {}
  output_mapping: {}
  # ... steptype-specific fields
```

- The **leading `-` is structural**: `steps` is a YAML list. Omitting it is the single most
  common recipe error, which is why `yaml_format.rst` warns about it twice.
- `steptype` matching is **case-insensitive for 8 of the 10 types and case-sensitive for the
  two SSH ones** (`recipe.py:809-819`) — see §16 F10. Use the exact CamelCase spelling always.
- Construction is `eval(step_type + "(**step_data)")` (`recipe.py:826`). Consequences:
  - **any unknown key in the step dict is a `TypeError`** at load time, because the step
    classes take fixed keyword arguments;
  - an unknown `steptype` is a raw `NameError`;
  - a recipe file can execute arbitrary Python (§16 F11).
- `skip: true` → the step is not executed at all; inputs are never resolved; result is `SKIP`.
- `critical` and `continue_on_error` are explained in §9.

---

## 6. `input_mapping` — where arguments come from

Each key is an **argument name the step expects**; each value is a small dict describing the
source (`recipe.py:636-665`).

| `type` | Extra keys | Behaviour |
|---|---|---|
| `direct` (default when `type` is omitted) | `value` | literal value from the YAML |
| `local` | `local_name` | reads `local_stack[-1][local_name]` — `KeyError` if undeclared |
| `global` | `global_name` | reads `globals[global_name]` — `KeyError` if undeclared |
| `method` | `value` | **identical to `direct`** (`recipe.py:661-663`); used only for `method_name` in `UserRunMethodStep` |
| any + `indexed: true` | — | turns the whole step into an `IndexedStep` — see §11 |

Two behaviours worth knowing:

- **`global_name` wins over `type`.** `if input_config.get("global_name", False)` is checked
  *before* the `match` (`recipe.py:644-649`), so any mapping carrying a non-empty `global_name`
  resolves as a global regardless of its declared `type`.
- **No type coercion, anywhere.** `value: '45'` is the string `"45"`; `value: 45` is the int.
  This matters for `equals` (§7) and for methods doing arithmetic. The example recipes are
  themselves inconsistent here — `simple_recipe.yml:96` uses `value: 45` where
  `simple_multiplestep_recipe.yml` uses `value: '45'` for the same step.

Both YAML spellings are equivalent — flow style and block style:

```yaml
input_mapping:
  arg1: { type: direct, value: "hello" }        # flow
  arg2:                                          # block
    type: local
    local_name: local_var1
```

---

## 7. `output_mapping` — judging and storing what came back

Each key must **exactly match a key in the dict the step returned**. If the step returns a
non-dict, it is wrapped as `{"output": <value>}`; `None` becomes `{}`
(`steps.py:249-256`). A mapping key with no matching output key is a `KeyError` → `ERROR`.

| `type` | Extra keys | Effect on the step's result |
|---|---|---|
| `passfail` | — | `PASS` if the value is truthy, else `FAIL` |
| `equals` | `value` | `PASS` if `output == value` (**no coercion**), else `FAIL` |
| `range` | `min`, `max` | `PASS` if `min <= float(output) <= max`; strings are `float()`ed, so `min: '10'` works |
| `passthrough` | — | the value *is already* a `ResultType`; used for the implicit `__result` of `SequenceStep`/`IndexedStep` |
| `local` | `local_name` | writes into the current sequence's locals; **does not change the result** |
| `global` | `global_name` | writes into globals; **does not change the result** |

**Result determination — the real rule** (`recipe.py:667-694`):

```python
step_result = ResultType.DONE
for output_name, output_config in self.output_mapping.items():
    match output_config["type"]:
        ...   # each judging branch ASSIGNS step_result
return step_result
```

- Start value is `DONE`. If no judging mapping exists, the step ends `DONE` (treated as "ran,
  no verdict" — it is *not* a failure).
- **The last judging mapping wins.** Two `passfail` entries where the first fails and the
  second passes → the step is `PASS`. [DOC] `yaml_format.rst:219` claims *"all must pass"* —
  that is false (§16 F6). Dict order = YAML order, so this is deterministic but fragile.
- `local`/`global` branches do not touch `step_result`, so mixing storage and judging is safe
  in either order.
- `output_config["type"]` is plain indexing → an output mapping without `type` is an `ERROR`.

---

## 8. The result model

`ResultType` is an `IntEnum` and **the ordering is the aggregation rule**
(`recipe.py:28-34`, `recipe.py:97-106`):

```
SKIP(0) < DONE(1) < PASS(2) < FAIL(3) < ERROR(4) < STOP(5)
```

A sequence's result is `max(child results)`. So:

- all steps `SKIP` → sequence `SKIP`;
- any `PASS` among `DONE`s → `PASS`;
- one `FAIL` anywhere → the whole sequence `FAIL`;
- `ERROR` (an unhandled exception) outranks `FAIL`; `STOP` (operator abort) outranks everything.

Each `StepResult` carries: `step`, `result`, `inputs`, `outputs`, `error_info` (a formatted
traceback), `uuid`, `parent`, `subresults`, plus reporting metadata `recipe_name`,
`recipe_file_name`, `serial_number`, `sequence_name`, `pypts_version`.

Those metadata fields are exactly the report's CSV columns
(`old_code/report.py:104`):

```
recipe_name, recipe_file_name, sequence_name, serial_number, pypts_version,
step_name, step_id, step_type, result, inputs, outputs, error_info
```

→ **Anything a recipe author wants to see in the report must end up in a step's `inputs` or
`outputs`.** There is no free-form annotation channel today.

---

## 9. Execution and error control flow

### 9.1 Order of execution

`Sequence.__init__` appends `setup_steps` and `steps` into **one flat list**
(`recipe.py:566-575`):

```python
for step_data in sequence_data["setup_steps"]: self.steps.append(...)
for step_data in sequence_data["steps"]:       self.steps.append(...)
for step_data in sequence_data["teardown_steps"]: self.teardown_steps.append(...)
```

So setup steps are literally just steps that run first — they have **no special error handling,
no guarantee, no separate reporting**. Only `teardown_steps` is genuinely different: it runs in
a `finally` block (`recipe.py:588-590`), so it executes after a failure or an abort, and its
results are appended to the sequence's results.

### 9.2 What stops a sequence

The single decision point (`recipe.py:776-789`):

```python
try: runtime.continue_on_error = runtime.get_global('continue_on_error')
except: pass
if step_result.is_type(ResultType.ERROR) and (not runtime.continue_on_error or step.is_critical()):
    break
```

Read carefully, this says:

1. **Only `ERROR` can stop a sequence.** A `FAIL` — a failed measurement — never halts
   anything. This surprises everyone; it is intended (a failing DUT should still be fully
   characterised) but it is nowhere documented.
2. **`globals.continue_on_error`, if it exists, overrides everything** — including per-step
   settings — and is re-read on every step boundary.
3. If that global does *not* exist, `runtime.continue_on_error` holds whatever value **the last
   executed step assigned to it**. Step types set `runtime.continue_on_error = self.continue_on_error`
   inside their `_step` (e.g. `steps.py:226`), and the types that don't set it (`WaitStep`,
   `SequenceStep`, `IndexedStep`) leave the previous step's value in place. Step-level
   `continue_on_error` therefore **leaks forward** (§16 F8).
4. `critical: true` re-arms the stop even when continuing is enabled.

Resulting behaviour matrix — this one does match [DOC] `yaml_format.rst:707`:

| `continue_on_error` | `critical` | on ERROR |
|---|---|---|
| false | false | stop |
| false | true | stop |
| true | false | continue |
| true | true | stop |

…with the crucial caveats that only `ERROR` triggers it, that the header-level
`continue_on_error:` used by four of the five example recipes is **inert** (§16 F1), and that
`recipe_version: 1.1.0` gates nothing (§16 F2).

### 9.3 Abort

`runtime.stop_event` is checked before each step and again right after `_step` returns
(`recipe.py:723, 739`). On abort the step result is `STOP`, `WAIT_FOR_TERMINATION` is set, and
the sequence unwinds into teardown. Interactive steps poll the same event while waiting for the
operator, so an abort during a prompt is honoured within ~1 s (`steps.py:572-581`).

---

## 10. Step type catalogue

Ten classes exist; two (`IndexedStep`, `SequenceStep`) are structural, eight are usable
directly. **`continue_on_error` is only accepted by the types marked ✓** — putting it on any
other type is a load-time `TypeError` (§16 F9).

### 10.1 `PythonModuleStep` — run user Python  · `continue_on_error` ✓

The workhorse. Loads a module and calls into it.

```yaml
- steptype: PythonModuleStep
  step_name: Check rail voltage
  description: Reads the 3V3 rail and compares against limits
  action_type: method           # method | read_attribute | write_attribute
  module: example_tests.py      # resolved per §3.3
  method_name: range_test       # required when action_type == method
  input_mapping:
    value: { type: local,  local_name: measured }
    min:   { type: direct, value: 3.1 }
    max:   { type: direct, value: 3.5 }
  output_mapping:
    compare: { type: range, min: '3.1', max: '3.5' }
```

- `input_mapping` is passed to the method **as keyword arguments** (`method_to_call(**input)`),
  so key names must equal the Python parameter names exactly.
- Return value: a dict → used as-is; `None` → `{}`; anything else → `{"output": value}`.
- `read_attribute` needs input `attribute_name`; `write_attribute` needs `attribute_name` and
  `attribute_value`.
- Required fields per [VAL]: `steptype, step_name, action_type, module, method_name, description`.

### 10.2 `WaitStep` — sleep · `continue_on_error` ✗

```yaml
- steptype: WaitStep
  step_name: Settle
  description: Let the rail settle
  input_mapping:
    wait_time: { value: '3' }     # seconds; string or number, float()ed
  output_mapping: {}
```

Returns `{}` → always `DONE`. A missing `wait_time` is a `TypeError` → `ERROR`.

### 10.3 `UserInteractionStep` — prompt with buttons · `continue_on_error` ✓

```yaml
- steptype: UserInteractionStep
  step_name: Confirm wiring
  description: Operator confirms the harness is connected
  input_mapping:
    message:    { type: direct, value: 'Connect the harness, then press Next' }
    image_path: { type: direct, value: harness.jpg }
    options:
      type: direct
      value:
        - 'next': 'Next'        # response value : button label
        - 'cancel': 'Cancel'
  output_mapping:
    output: { type: equals, value: 'next' }
```

**`options` semantics** (`gui.py:423, 438-442`) — this is the most misunderstood part of the
format:

```python
flat_options = {k: v for d in options for k, v in d.items()}
for value, label in flat_options.items():
    add_button(label=label or value.capitalize(), value=value)
```

- `options` is a **list of single-entry dicts**.
- The **key is what the step receives back**; the **value is the button caption**.
- An empty caption falls back to `key.capitalize()` — hence `- 'yes': ''` renders a button
  labelled "Yes" that returns `"yes"`.
- No options at all → a single unlabelled button.
- `yes`/`no` **must be quoted** in YAML or they become booleans (§14).

**Special response values.** The GUI reacts to three response values by opening a second dialog
and pushing a *second* item onto the same response queue (`gui.py:398-412`):
`file` → file chooser, `wrt` → text input, `ID` → serial-port chooser returning
`(port, baudrate, IDN)`. Which step type consumes that second item differs (see 10.5–10.7).

**Optional `trigger_response`** — when the operator's answer matches, the step builds a
`PythonModuleStep` on the fly and runs it, using `module`, `action_type` and the *raw*
`input_mapping["method_name"]["value"]` (`steps.py:595-635`). Its result is reported only as
`status: ok|error` in the step outputs; it does **not** affect the step's PASS/FAIL.

Returns `{"output": <response>, "status": {...}}`.

> ⚠️ The cancel path in this step type is broken — the `AbortTestException` is raised inside a
> `try` whose `except Exception: pass` swallows it (`steps.py:587-593`). The Cancel button does
> nothing here, while it *does* abort in the three `User*` types below (§16 F13).

### 10.4 `SequenceStep` — call another sequence · `continue_on_error` ✗

```yaml
- steptype: SequenceStep
  step_name: Run voltage subtests
  sequence: { type: internal, name: Voltage subtests }
  input_mapping:
    sublocal: { type: direct, value: 45 }
  output_mapping:
    __result: { type: passthrough }
```

- `sequence.type` supports only `internal` today; `external` (load from another file) is
  commented out (`steps.py:438-454`).
- `input_mapping` becomes the **initial locals** of the callee, layered on top of its declared
  `locals`.
- The callee's declared `outputs` are **not returned** — the only thing that comes back is
  `__result`, the callee's aggregated `ResultType` (§16 F16). To get data out of a subsequence
  today, the subsequence must write to a **global**.
- The engine wraps the whole run in a synthetic `SequenceStep` for `main_sequence`
  (`recipe.py:497-500`), so this path is exercised on every run.

### 10.5 `UserLoadingStep` — operator picks a file · `continue_on_error` ✓

```yaml
- steptype: UserLoadingStep
  step_name: Load config file
  description: Operator selects the calibration file
  input_mapping:
    message: { type: direct, value: 'Select the calibration file' }
    options:
      type: direct
      value:
        - cancel: 'Cancel'
        - file:   'Browse…'      # 'file' must equal globals.loadFile_key
  output_mapping:
    output: { type: passfail }
  file_save_location: { type: global, variable: config_file }
```

Requires globals `loadFile_key` and `cancel_key`. On the `file` response the chosen path
arrives as the second queue item and is stored per `file_save_location`, defaulting to the
global `file`. **`type: local` in `file_save_location` still writes to a global** (§16 F15).

### 10.6 `UserRunMethodStep` — prompt, then run a method · `continue_on_error` ✓

Same prompt shape as 10.3, plus `action_type` + `module`, with `method_name` given as an input
of `type: method`. Any input key other than `message`/`image_path`/`options`/`method_name` is
forwarded to the method as an argument. `trigger_response` selects which button triggers the
call. Requires global `cancel_key`.

### 10.7 `UserWriteStep` — operator types a value / configures a serial port · `continue_on_error` ✓

Two modes, selected by the response key:

- `wrt` (must equal `globals.wrt_key`) → a text dialog; the typed string is written to the
  variable named in `output_mapping.output`.
  ⚠️ …and then immediately **overwritten by the literal string `"wrt"`** when `process_outputs`
  runs on the returned `{"output": "wrt"}` (§16 F14). As written, this mode cannot deliver the
  operator's text into a variable.
- `ID` (must equal `globals.ID_key`) → a serial-port dialog; writes the **hard-coded locals**
  `serial_ID`, `serialport`, `baudrate`, which the sequence must declare.

Requires globals `cancel_key`, `wrt_key`, `ID_key`.

**Ported as `UserWrite`** (2026-09-02), the `wrt` half only, and without the three key
globals — the buttons are the GUI's. F14 cannot recur: there is no button whose label
competes with the typed text. The `ID` half is **dropped**: identifying an instrument over
RS-232 is a `PythonModule` step calling a driver, not a person typing. See `step/step.md`
§2.4.

### 10.8 `SSHConnectStep` / `SSHCloseStep` — paramiko session · `continue_on_error` ✓

```yaml
setup_steps:
- steptype: SSHConnectStep          # exact CamelCase — case-insensitivity is broken here
  step_name: Open SSH session
  description: Connect to the DUT
teardown_steps:
- steptype: SSHCloseStep
  step_name: Close SSH session
  description: Disconnect
```

Reads **globals only** — `host`, `user`, `password`, `private_key`, `port` — never
`input_mapping`. Every one of them must be declared or the step raises `KeyError` → `ERROR`.
`port` accepts `None`/`"None"`/empty → 22. Password auth is used when `password` is set,
otherwise the RSA key at `private_key`. On success it publishes the live client as the global
`ssh_client`, which downstream `PythonModuleStep`s take as an input:

```yaml
input_mapping:
  target: { type: global, global_name: ssh_client }
```

> ⚠️ Publishing a live paramiko client through a global is exactly the pattern that **cannot
> survive a process boundary** (unpicklable). It works today because everything is one thread.
> See §17 and the roadmap's pickling TODO.
>
> ⚠️ `resources/recipes/comprehensive_recipe.yml:20` contains a **plaintext SSH password**
> (§16 F22).

Rule from [DOC] worth keeping: *whenever `SSHConnectStep` is used, put `SSHCloseStep` in
`teardown_steps`* — teardown is the only block guaranteed to run.

### 10.9 `IndexedStep` — never written by hand

Synthesised by `build_step` when any input carries `indexed: true`. See §11.

---

## 11. Indexed steps (looping)

Mark one or more inputs `indexed: true` and give them lists. `build_step` then wraps the step in
an `IndexedStep` (`recipe.py:828-838`) which runs the original step once per element:

```yaml
- steptype: UserInteractionStep
  step_name: Guided assembly
  input_mapping:
    message:
      type: direct
      value: ['Connect devices', 'Verify connection', 'Load configuration']
      indexed: true
    options:
      type: direct
      value: [{'next': 'Next'}]
  output_mapping:
    output: { type: equals, value: 'next' }
```

Mechanics (`steps.py:53-186`):

- **Iteration count = length of the *shortest* indexed list.** Empty list → the step is `SKIP`.
- Non-indexed inputs are repeated verbatim each iteration.
- Each iteration is a `deepcopy` of the template step, renamed `"<name> - Iteration i/n"`, and
  its results become **subresults** of the wrapper.
- Per-iteration `local`/`global` output mappings are **deleted** so iterations don't overwrite
  each other; per-iteration `passfail`/`equals`/`range` checks *are* kept.
- An output mapping may itself be `indexed: true` with a `value:` list — that supplies a
  different expected value per iteration.
- The wrapper's result is `max()` over all iterations.

**Limitations to know before relying on it:**
- The wrapper's own `output_mapping` from the YAML is discarded (`steps.py:40`), so the
  aggregated per-iteration outputs it carefully collects **can never be stored anywhere**
  (§16 F25).
- `critical` and `continue_on_error` are dropped when the wrapper is built (`recipe.py:832`).
- There is no other loop construct — no `while`, no `repeat`, no conditional. Indexed inputs are
  the entire control-flow vocabulary of the format.

---

## 12. Subsequences — the unfinished corner

`parameters` (what a caller may set) and `outputs` (what the callee returns) are parsed into
`Sequence` and then **never referenced again**. `SequenceStep._step` contains a ~35-line comment
block (`steps.py:464-494`) working through the problem and concluding with a workaround: write
to globals instead. `resources/recipes/subsequence_executions_draft.yml` is entirely commented
out, with the note *"the subsequence execution was never actually tested yet"*.

**Treat subsequence parameter/output passing as unimplemented.** It is the single largest
functional gap in the recipe format, and §17 proposes fixing it during the port rather than
carrying the workaround forward.

---

## 13. Required globals & locals cheat sheet

| Step type | Required **globals** | Required **locals** |
|---|---|---|
| `SSHConnectStep` / `SSHCloseStep` | `host`, `user`, `password`, `private_key`, `port`, `ssh_client` | — |
| `UserLoadingStep` | `cancel_key`, `loadFile_key` | — |
| `UserRunMethodStep` | `cancel_key` | — |
| `UserWriteStep` | `cancel_key`, `wrt_key`, `ID_key` | `serial_ID`, `serialport`, `baudrate` — only when the `ID` option is used |
| `UserInteractionStep` | `cancel_key` (soft — swallowed, §16 F13); `file` **and** `loadFile_key` if `trigger_response` is used (§16 F17) | — |
| all | `serial_number` is injected by the engine — never declare it | — |

Canonical header block for a recipe that uses the interactive/SSH steps:

```yaml
globals:
  cancel_key: 'cancel'
  loadFile_key: 'file'
  wrt_key: 'wrt'
  ID_key: 'ID'
  file: None
  ssh_client: None
  host: my-dut-hostname
  user: root
  password:              # prefer private_key; see §16 F22
  private_key: /path/to/key
  port: None
```

---

## 14. YAML pitfalls that bite recipe authors

1. **`yes`/`no`/`on`/`off`/`true` are booleans in YAML 1.1.** `- yes: ''` produces the key
   `True`, not `"yes"`, and the `equals` comparison against `'yes'` then fails. **Always quote
   them**: `- 'yes': ''`. Every example recipe does this; the rule is undocumented.
2. **`None` is the string `"None"`, not null.** YAML null is `null`, `~`, or empty. The
   recipes use `None` as a placeholder and `SSHConnectStep` explicitly defends against both
   spellings — nothing else does.
3. **Quoting changes the type, and nothing coerces.** `value: 45` ≠ `value: '45'` for
   `equals`. `range` is safe (it calls `float()`).
4. **The leading `-` before `steptype`** is what makes a step a list element. Losing it turns
   the step into a mapping key and produces a confusing `KeyError`.
5. **Key order matters to the validator** — the header document must *start* with `name:`, a
   sequence document with `sequence_name:` (§16 F5).
6. **Tabs are illegal in YAML.** Indentation must be spaces.
7. **A blank `locals:` is `null`, not `{}`.** Write `locals: {}` explicitly.
8. **Duplicate keys silently win-last** — including duplicate `sequence_name` across documents.
9. Multi-line message strings: the folded/literal block or the trailing-newline form used in
   `simple_recipe.yml:31-35` both work; the value reaches the GUI verbatim.

---

## 15. What the verificator actually checks

`verify_recipe.py` composes the YAML twice (`yaml.compose_all` for a path→line map,
`safe_load_all` for values) so faults carry line numbers. Faults are hard errors; warnings are
`null`/empty strings in `str` fields. Entry points: `validate_recipe_file(path)`,
`validate_recipe_filepath(path)`, `validate_all_recipes_in_folder(s)`,
`validate_recipe_string_variable(text)` (used live by the Recipe Creator).

**Checked:**

- Each document is a dict; document kind is inferred from its **first key**.
- Header: `version`, `description`, `main_sequence`, `globals` present, correct type, non-empty.
- Sequence: `description`, `setup_steps`, `steps`, `teardown_steps`, `parameters`, `outputs`,
  `locals` present and correctly typed.
- For each entry in **`steps` only**: the per-steptype required-field list, `input_mapping` /
  `output_mapping` are dicts if present, `skip` is a bool.

**Not checked** (the honest gap list):

- `setup_steps` and `teardown_steps` step contents — never validated (`verify_recipe.py:184`).
- `name` in the header (it is only used to *recognise* the document).
- That `main_sequence` names an existing sequence.
- That `steptype` is a known type — and `SequenceStep`/`IndexedStep` aren't in
  `STEP_REQUIRED_FIELDS` at all, so they fall through to the `default` rule and are wrongly
  required to have `action_type`/`module`/`method_name` (§16 F19).
- Anything *inside* `input_mapping`/`output_mapping`: no check that `type` is valid, that
  `direct` has `value`, that `local`/`global` have their `*_name`, that `equals` has `value`,
  that `range` has `min`/`max`.
- That referenced locals/globals are declared, or that required globals for a steptype exist.
- That `module`/`method_name` resolve.
- Recipe-level uniqueness of `step_name`/`id`.

And the rules themselves live in **three disagreeing places** — `recipe_rules.py`,
`recipe_creator.py:795-800`, and `yaml_format.rst` (§16 F19, F21).

---

## 16. Findings — rule/doc/code contradictions and defects

Ordered by impact. Each is verified against the source; none is speculative. Severity:
**H** = wrong results or silent misbehaviour, **M** = confusing/blocking, **L** = cleanup.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| **F1** | **H** | Header-level `continue_on_error:` is **never read**. Only `globals.continue_on_error` has any effect. 4 of 5 example recipes set it at header level and therefore run with error-stops enabled, contrary to their author's intent. | `recipe.py:427-432` vs `recipe.py:777`; `yaml_format.rst:31,45,666`; `simple_recipe.yml:9`, `black_forest.yml`, `graph_testing.yml`, `simple_multiplestep_recipe.yml` |
| **F2** | M | `recipe_version` is read by nothing. The documented "requires recipe_version 1.1.0" gating does not exist. | grep: no reader; `yaml_format.rst:24,41` |
| **F3** | **H** | `Recipe.run(sequence_name=...)` is overwritten by `self.main_sequence` on the next line — **it is impossible to run any sequence other than `main_sequence`**. | `recipe.py:472` |
| **F4** | M | `main_sequence` is mandatory in effect (plain indexing) but missing from the loader's checked-fields list → raw `KeyError` instead of the intended clear message. | `recipe.py:400` vs `recipe.py:428` |
| **F5** | M | Validator identifies documents by **first key**, loader by **document position**. A header whose first key is `version` validates as "unrecognized document" yet loads fine; a *second* document starting with `name:` is validated as a header but loaded as a sequence. | `verify_recipe.py:168-194` vs `recipe.py:396-425` |
| **F6** | **H** | `output_mapping` result rule is **last-writer-wins**, not "all must pass" as documented. A step with a failing and then a passing check reports PASS. | `recipe.py:670-694` vs `yaml_format.rst:219` |
| **F7** | **H** | Only `ERROR` stops a sequence; `FAIL` never does. Undocumented, and the opposite of most users' mental model. | `recipe.py:782` |
| **F8** | **H** | Step-level `continue_on_error` is stored on the *runtime* by each step as it executes, and step types that don't set it (`WaitStep`, `SequenceStep`, `IndexedStep`) inherit the **previous** step's value. | `steps.py:226,548,734,820,945,1037`; `recipe.py:776-789` |
| **F9** | M | `continue_on_error` is a `TypeError` at load time on `WaitStep`, `SequenceStep` and `IndexedStep` — their constructors don't accept it — although [DOC] says it applies to all step types. | `steps.py:661,385,25` vs `yaml_format.rst:315` |
| **F10** | M | `steptype` case-insensitivity is broken for exactly two types: the `SSHConnectStep`/`SSHCloseStep` match arms compare a *lowercased* string against CamelCase literals, so only the exact spelling works (via `eval` fall-through). | `recipe.py:809-819` |
| **F11** | **H** | Steps are constructed with `eval(step_type + "(**step_data)")` → **arbitrary code execution from a recipe file**, plus `NameError` for unknown steptypes. Already on the roadmap (§3.3). | `recipe.py:826` |
| **F12** | **H** | `Step.__init__` uses mutable default arguments `input_mapping={}, output_mapping={}`, and `SequenceStep.__init__` then does `self.output_mapping["__result"] = ...` — mutating the **shared default dict** for every step that omitted `output_mapping`. | `recipe.py:605`, `steps.py:403` |
| **F13** | **H** | `UserInteractionStep`'s Cancel is dead: `AbortTestException` is raised inside a `try` whose `except Exception: pass` swallows it. Cancel aborts in the other three `User*` types but not this one. | `steps.py:587-593` |
| **F14** | **H** | `UserWriteStep` `wrt` mode writes the operator's text to the variable, then `process_outputs` overwrites it with the literal `"wrt"`. The documented purpose of the mode cannot be achieved. | `steps.py:971-976` + `recipe.py:692`; `yaml_format.rst:599-607` |
| **F15** | M | `UserLoadingStep`'s `file_save_location: {type: local}` calls `runtime.set_global`. `local` silently means global. | `steps.py:760-761` |
| **F16** | **H** | Sequence `parameters`/`outputs` are parsed and never used; a subsequence cannot return data. Additionally `push_locals(self.locals)` pushes the parsed dict **by reference**, so a sequence run twice does not start clean. | `recipe.py:564-565, 581`; `steps.py:464-497` |
| **F17** | M | `UserInteractionStep`'s `trigger_response` path reads globals `loadFile_key` and `file`; `file` is declared by no example recipe and only comes into existence if a `UserLoadingStep` ran first → order-dependent `KeyError`. | `steps.py:605-614`; `comprehensive_recipe.yml:10-22` |
| **F18** | M | Teardown is invoked as `Step.run_steps(..., stop_event=stop_event.clear())` — `clear()` returns `None`, so the argument is meaningless, and the call **clears the global abort flag** as a side effect. Also `AttributeError` if `stop_event` is absent. | `recipe.py:589-590` |
| **F19** | M | Validator gaps: `setup_steps`/`teardown_steps` contents unvalidated; `SequenceStep`/`IndexedStep` absent from `STEP_REQUIRED_FIELDS` so they're checked against the Python-module template; nothing inside `input_mapping`/`output_mapping` is validated; no cross-reference checks. | `verify_recipe.py:184`, `recipe_rules.py:24-34` |
| **F20** | M | `verify_recipe.py` imports its rule constants `from pypts`, which no longer exports them → **the verificator cannot be imported at all** today. (Already noted in the roadmap.) | `verify_recipe.py:7` vs `src/pypts/__init__.py` |
| **F21** | M | A third, divergent copy of the required-field rules lives in the Recipe Creator (it demands `method_name` for `UserRunMethodStep`, and knows none of the SSH/`User*` types). | `recipe_creator.py:795-800` vs `recipe_rules.py` |
| **F22** | **H** | `resources/recipes/comprehensive_recipe.yml:20` contains a plaintext SSH password (`password: WhiteV4Pypts`) committed to the repository. Rotate it and move credentials out of recipes. | file:20 |
| **F23** | M | [DOC] says `parameters`/`outputs` are lists; [VAL] requires dicts; the draft recipe uses lists. | `yaml_format.rst:118-119` vs `recipe_rules.py:19-20` |
| **F24** | M | The example recipes are **not runnable**: they reference `example_tests.py`, which does not exist anywhere in the repo (only `spikes/GUI/dev_tests.py` does). Characterization tests for the port (roadmap Phase 0) need this fixed first. | `find` over the tree; `simple_recipe.yml:47` etc. |
| **F25** | M | `IndexedStep` discards the wrapper's YAML `output_mapping` and drops `critical`/`continue_on_error`, so its aggregated outputs are unreachable. | `steps.py:40`, `recipe.py:832` |
| **F26** | L | `equals` compares with `==` and no coercion, so YAML quoting silently decides pass/fail; the two "same" example recipes disagree on quoting for the same step. | `recipe.py:677-682`; `simple_recipe.yml:96` vs `simple_multiplestep_recipe.yml` |
| **F27** | L | `process_inputs` mutates the recipe data in place (injects `type: direct`), and `build_step` `del`s `steptype` from the step dict — the parsed recipe is not reusable/re-serialisable. | `recipe.py:642, 823` |
| **F28** | L | `Step.run_steps` passes the **builtin `input` function** as the step's `input` argument. Harmless (the parameter is unused) but a clear sign the signature is vestigial. | `recipe.py:772` |

---

## 17. [PROPOSAL] Recipe format for the new framework

Everything in this section is a suggestion for discussion — nothing here is implemented, and I
have not touched the format. Grouped by how much they cost.

### 17.1 Keep as-is (the format's genuine strengths)

- **Multi-document YAML, header + sequences.** Simple, diffable, teachable.
- **`input_mapping`/`output_mapping` as an explicit data-flow contract.** The step code stays a
  plain Python function with no framework imports; the recipe wires it up. This is what makes
  "tests executable stand-alone" true, and it should survive untouched.
- **`direct`/`local`/`global` sources** and the **`passfail`/`equals`/`range`/`passthrough`**
  verdict vocabulary. Coverage is right; only the evaluation rule needs fixing (F6).
- **`setup_steps` / `steps` / `teardown_steps`** with a guaranteed teardown.
- **The `ResultType` severity ordering** as the aggregation rule. Elegant, and the report
  depends on it.

### 17.2 Fix during the port (behaviour bugs, no format change)

F1, F3, F6, F7 (document it, or make FAIL-stops configurable), F8, F12, F13, F14, F15, F18, F25.
These are all "the format says X, the engine does Y" — fixing them makes existing recipes mean
what they look like they mean. F11 (`eval` → plugin registry) is already the roadmap's Phase 2
item and is cheapest during the step port.

### 17.3 One schema, one owner

The three rule sets (`recipe_rules.py`, `recipe_creator.py`, `yaml_format.rst`) must collapse
into one machine-readable schema that the verificator, the Creator, and the docs all read —
this is exactly the roadmap's `StepPlugin.required_fields` / `input_schema` / `output_schema`
idea (§3.2). Concretely: **each step type owns its schema**, and validation, the Creator's
field list, and the generated docs all derive from it. That closes F9, F19, F21, F23 by
construction.

### 17.4 Format changes worth proposing

| # | Change | Why |
|---|---|---|
| P1 | Add **`format_version`** to the header, with an explicit compatibility policy | Already a roadmap open question; `recipe_version` exists but means nothing (F2) — either give it teeth or replace it |
| P2 | **Finish subsequences**: `parameters` = declared inputs, `outputs` = declared returns, `SequenceStep.output_mapping` reads them | Closes F16, removes the "write to a global" workaround, and makes recipes composable — the biggest capability win available |
| P3 | **Declare variables with a type and a default** (`locals: {v: {type: float, default: 0}}` or keep the flat form and infer) | Kills the entire quoting class of bugs (F26) and lets the verificator check references |
| P4 | Make **undeclared variable access a validation fault**, not a runtime `KeyError` | Today a typo in `local_name` fails mid-run on the bench |
| P5 | Replace the magic-string globals (`cancel_key`, `wrt_key`, `ID_key`, `loadFile_key`, `file`, `ssh_client`) with **step-level fields or framework services** | These are the format's worst wart: hidden coupling, order-dependent (F17), and undiscoverable. `ssh_client`-as-a-global also breaks the moment anything crosses a process boundary |
| P6 | State the **`output_mapping` evaluation rule** explicitly — recommend "all checks must pass" (matching the docs and intuition), which is a deliberate behaviour change from F6 | Ambiguity here silently mis-reports test outcomes |
| P7 | Give a **real loop/conditional construct**; keep `indexed:` as sugar over it | `indexed:` is the only control flow, and it's a wrapper hack (§11). The roadmap already lists "conditional execution" as a spec requirement |
| P8 | **Credentials out of recipes** — reference a Config Handler entry by logical name | F22; also the HAL direction in roadmap Phase 5 |
| P9 | Decide `parameters`/`outputs` **dict vs list** once and enforce it | F23 |
| P10 | Recognise documents by **position and an explicit `kind:`**, not by first-key order | F5; makes key order cosmetic again |

### 17.5 Migration

The format changes above are additive except P6 and P9. A `format_version: 2` header plus a
one-shot converter script (the Recipe Creator already round-trips YAML with `ruamel.yaml`, so
it can host it) would carry the existing recipes forward. The pre-condition for any of this is
roadmap Phase 0's characterization tests — which need F24 fixed first, since the example
recipes currently reference a module that isn't in the repo.

---

## 18. Open questions for you

Answering these unblocks the next concrete piece of work. My recommendation is given first
where I have one.

1. **Scope of this guide's follow-up** — do you want (a) the findings turned into roadmap TODOs
   / GitLab issues, (b) the format proposal in §17 turned into a written spec for v2, or
   (c) this document folded into `docs/source/` as the replacement for `yaml_format.rst`?
   *I'd suggest (a) now, (b) before the step port starts.*
2. **F6 — `output_mapping` semantics.** Change to "all checks must pass" (matches docs and
   intuition, breaks any recipe relying on last-wins), or document last-wins as intended?
   *I'd change it; I doubt anyone depends on last-wins deliberately.*
3. **F7 — should a `FAIL` stop a sequence?** Today only `ERROR` does. Keep, or make it a
   per-recipe policy (`on_fail: continue|stop`)?
4. **F3 — is "run any sequence, not just `main_sequence`" a requirement** for the new CLI/GUI?
   It's a one-line fix but changes what `main_sequence` means.
5. **P5 — the magic globals.** Are `cancel_key`/`wrt_key`/`ID_key` used as a *customisation*
   point by any real recipe at CERN (e.g. localised button labels), or can they become fixed
   framework behaviour?
6. **P2 — subsequences.** Is composable sequence reuse actually wanted for v0.3.0, or is the
   flat single-sequence recipe the real usage today? This decides how much of the step/sequence
   port needs the scope machinery.
7. **F24 — where is `example_tests.py`?** It's referenced by every example recipe but absent
   from the repo. Is it in the old master branch, or should the examples be rewritten against a
   new demo test module?
8. **F22 — the committed SSH password.** Is `CTDW-864-CWRSV4P2` a real host with a live
   credential that needs rotating, or a dead lab machine?
9. **Recipe format vs plugin schema ordering.** The roadmap puts the plugin registry in Phase 2
   but the step port in Phase 1. Since each step type would own its schema (§17.3), do you want
   the schema layer pulled forward into Phase 1 so the rules are written once?
