<!-- SPDX-FileCopyrightText: 2026 CERN <home.cern> -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# PyPTS Recipe Guide

**Purpose.** The definitive reference for what a recipe *is* and what the current framework
does with it. One document, one version of the truth.

---

## 1. The model in 30 seconds

A recipe is a **multi-document YAML file**:

```
document 1        recipe header   — name, version, main_sequence, globals
document 2..N     sequences       — each: locals + setup_steps / steps / teardown_steps
```

A **sequence** is an ordered list of **steps**. A **step** has a `steptype` (which Python
class runs it), an `input_mapping` (where its arguments come from), and an `output_mapping`
(what to do with what it returned).

Two variable scopes: **globals** (whole recipe) and **locals** (one dict per sequence). Steps
never talk to each other directly — they communicate by writing and reading variables.

Every step produces a `StepResult` with one `ResultType`. A sequence's result is the maximum
severity of its children.

```
Recipe
└── Sequence "Main"
    ├── setup_steps   ─┐
    ├── steps          ├─ executed as one flat list in order
    └── teardown_steps ─┘ always executed, even after failure
```

---

## 2. File anatomy

```yaml
# SPDX headers (required by REUSE for files under resources/)
name: My Recipe
version: 0.1.0
...
---                             # YAML document separator
sequence_name: Main
...
---
sequence_name: Subsequence
...
```

Loaded with `yaml.safe_load_all` — document order is significant. Doc 1 is the header,
every following doc is a sequence keyed by `sequence_name`.

---

## 3. Recipe header

```yaml
name: LED driver acceptance      # required; shown in GUI title and report
description: Checks the LED driver board at 5 V
version: 0.2                     # required; stored in the report
main_sequence: Main              # required; the sequence that runs by default
test_package: my_tests           # optional; package root for module resolution
report_metadata: [serial_number] # optional; globals that become report columns
globals:
  target_voltage: 5.0
  tolerance: 0.1
```

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | GUI header, report metadata |
| `description` | yes | GUI, log |
| `version` | yes | report metadata |
| `main_sequence` | yes | sequence that the GUI/CLI starts by default |
| `test_package` | no | package root for `PythonModule` file resolution (see §6.1) |
| `report_metadata` | no | list of global names to embed as CSV columns; defaults to `[serial_number]` |
| `globals` | yes | flat `name: value` dict; initial global variable store |

**`serial_number` is not injected.** The engine has no concept of a serial number. Capture
it with a `UserWrite` step and store it in the `serial_number` global; the framework picks it
up through `report_metadata`. See `best_practices.md` §1.

---

## 4. Sequence document

```yaml
sequence_name: Main          # required; the identifier other parts reference
description: Main test flow
locals:                      # required; {} if none needed
  target: '45'
setup_steps: []              # required; [] if empty
steps:
  - ...
teardown_steps: []           # required; [] if empty; runs even on failure/abort
```

All seven fields are required — a missing field or a `null` value raises at load time.

**`setup_steps` / `steps` / `teardown_steps`:** `setup_steps` and `steps` are merged into
one flat list in order; only `teardown_steps` has special behaviour (runs in a `finally`
block after success, failure or abort).

**Local scope:** `get_local`/`set_local` only ever touch `local_stack[-1]` — a sequence
cannot see its caller's locals.

---

## 5. Step — common fields

```yaml
- steptype: PythonModule     # required; selects the class (see §8)
  step_name: Check 3V3 rail  # required; shown in GUI table and report
  description: ...           # required
  id: my-stable-id           # optional; fresh uuid4 if absent
  skip: false                # optional; SKIP result, inputs never resolved
  continue_on_error: true    # optional; see §7
  input_mapping: {}          # optional; empty dict if absent
  output_mapping: {}         # optional; empty dict if absent
  # ... steptype-specific fields
```

- `steptype` is case-insensitive for all current types.
- `skip: true` → step is not executed; result is `SKIP`.

---

## 6. `input_mapping` — where arguments come from

```yaml
input_mapping:
  arg1: { type: direct, value: "hello" }
  arg2: { type: local,  local_name: target }
  arg3: { type: global, global_name: tolerance }
```

| `type` | Extra keys | Behaviour |
|---|---|---|
| `direct` (default when `type` omitted) | `value` | literal value from the YAML |
| `local` | `local_name` | reads `local_stack[-1][local_name]` |
| `global` | `global_name` | reads `globals[global_name]` |

**No type coercion.** `value: '45'` is the string `"45"`; `value: 45` is the int.
Both YAML styles (flow and block) are equivalent.

**Note on `indexed: true`:** currently **silently ignored** (step runs once with the whole
list). This will become a load-time `RecipeError` in an upcoming fix (M-6). Do not rely
on it.

### 6.1 `test_package` and module resolution

When `test_package` is set in the header, `PythonModule` resolves the `module:` key as a
package resource (recursive search under the package root, skipping common exclude dirs).
Without it, `module:` is a file path relative to the recipe's directory.

Both spellings work: `module: example_tests.py` and `module: example_tests`. Every directory
in the chain needs `__init__.py`. Module names must be unique — resolution picks whichever
the glob hits first for ambiguous names.

---

## 7. `output_mapping` — judging and storing results

```yaml
output_mapping:
  voltage:  { type: range,    min: 4.9, max: 5.1 }
  measured: { type: global,   global_name: last_voltage }
  passed:   { type: passfail }
```

| `type` | Extra keys | Effect on result |
|---|---|---|
| `passfail` | — | `PASS` if truthy, else `FAIL` |
| `equals` | `value` | `PASS` if `output == value` (no coercion) |
| `range` | `min`, `max` | `PASS` if `min ≤ float(output) ≤ max` |
| `local` | `local_name` | stores into sequence locals; does not affect result |
| `global` | `global_name` | stores into globals; does not affect result |

**Result rule:** start value is `DONE`. Each judging entry (`passfail`/`equals`/`range`)
assigns the step result. If there are multiple judging entries, the last one wins — write one
judging entry per step to avoid surprises. `local`/`global` entries never touch the result.

A step key not present in the returned dict is an `ERROR`.

---

## 8. Result model

`ResultType` is an `IntEnum`; the ordering is the aggregation rule:

```
SKIP(0) < DONE(1) < PASS(2) < FAIL(3) < ERROR(4) < STOP(5)
```

- A sequence's result is `max(child results)`.
- **Only `ERROR` stops a sequence** (unless `continue_on_error: false`). A `FAIL` never halts
  anything — a failing DUT should still be fully characterised.
- `STOP` is produced by an operator abort.
- `DONE` means "ran, no verdict" — a step with no judging `output_mapping` entries.

---

## 9. Execution control

### 9.1 `continue_on_error`

```yaml
- steptype: PythonModule
  step_name: power_on
  continue_on_error: false   # stop the sequence if this step raises
  ...
```

Default is `true` (continue on error). Set `false` when stopping is safer — power supply
never came up, fixture is open. `critical: true` re-arms the stop even when the sequence
default is continue.

**Current limitation (M-7):** `continue_on_error` at the step level causes a load failure
on some step types. This will be fixed to tolerate-and-warn. Until then, avoid it on non-
`PythonModule` steps.

### 9.2 Abort

`runtime.stop_event` is checked before each step and immediately after it returns. Interactive
steps poll the event while waiting for the operator, so an abort is honoured within ~1 s.

---

## 10. Step type catalogue

Four step types are available. `steptype` values are case-insensitive.

### `PythonModule` — run user Python

```yaml
- steptype: PythonModule
  step_name: measure_voltage
  description: Reads the 3V3 rail and compares against limits
  action_type: method
  module: example_tests.py
  method_name: range_test
  input_mapping:
    value: { type: local,  local_name: measured }
    min:   { type: direct, value: 3.1 }
    max:   { type: direct, value: 3.5 }
  output_mapping:
    result: { type: range, min: 3.1, max: 3.5 }
```

- `action_type: method` only; `read_attribute`/`write_attribute` from the old engine are
  dropped.
- `input_mapping` keys are passed as keyword arguments to the method.
- Return value: dict → used as-is; `None` → `{}`; anything else → `{"output": value}`.
- Required fields: `step_name`, `description`, `action_type`, `module`, `method_name`.

### `Wait` — sleep

```yaml
- steptype: Wait
  step_name: settle
  description: Let the rail settle
  wait_time: 3               # seconds (int or float)
```

Always returns `DONE`.

### `UserInteraction` — prompt operator with buttons

```yaml
- steptype: UserInteraction
  step_name: confirm_wiring
  description: Operator confirms the harness is connected
  message: Connect the harness, then press Next.
  image_path: harness.jpg    # optional
  options:
    - next:   Next
    - cancel: Cancel
  output_mapping:
    output: { type: equals, value: next }
```

- `options` is a list of `{response_key: button_label}` dicts.
- Empty label → `key.capitalize()` as the button text.
- No `options` → a single unlabelled button.
- `cancel` as a response key stops the run.

### `UserWrite` — operator types a value

```yaml
- steptype: UserWrite
  step_name: get_serial_number
  description: Scan or type the serial number
  message: Scan or type the serial number of the unit under test.
  outputs:
    output: { type: global, global_name: serial_number }
```

Text-entry mode only. The typed string is stored per `outputs`. The old serial-port picker
mode (`ID` key) is not available.

---

## 11. Step types not yet available

| Old type | Status in new architecture |
|---|---|
| `UserLoadingStep` | Not yet ported — blocked on multi-value response protocol (M-1) |
| `SSHConnectStep` / `SSHCloseStep` | Not step types in the new architecture — moves to HAL (Phase 3) |
| `SequenceStep` | Dropped — no nested sequences |
| `UserRunMethodStep` | Deprecated — use `UserInteraction` + `PythonModule` in sequence |
| `IndexedStep` | Not a YAML type — will be handled at load time; currently `indexed: true` is silently ignored |

---

## 12. YAML pitfalls

1. **`yes`/`no`/`on`/`off`/`true` are booleans in YAML 1.1.** A button key `- yes: ''`
   produces the key `True`, not `"yes"`. Always quote: `- 'yes': ''`.
2. **`None` is a string, not null.** YAML null is `null`, `~`, or empty. Recipes use `None`
   as a placeholder; quote it where needed.
3. **Quoting changes the type.** `value: 45` ≠ `value: '45'` for `equals`. `range` is safe
   (it calls `float()`).
4. **The leading `-` before `steptype`** makes a step a list element. Omitting it turns the
   step into a mapping key and produces a confusing `KeyError`.
5. **A blank `locals:` is null, not `{}`.** Write `locals: {}` explicitly.
6. **Duplicate `sequence_name` across documents** — last one silently wins.
7. **Tabs are illegal in YAML.** Indentation must be spaces.

---

## 13. What the verificator checks

`recipe_verificator` composes the YAML twice (once for line-number mapping, once for values)
so every fault carries a line number. Returns `list[ValidationIssue]` with severity, field
path, message, hint, and line number. Collects all problems in one pass.

**Checked:**
- Each document is a dict; document kind is inferred from its first key.
- Header: `version`, `description`, `main_sequence`, `globals` present, correct type.
- Sequence: all required fields present and correctly typed.
- Per step: per-steptype required fields, `input_mapping`/`output_mapping` are dicts, `skip` is bool.

**Not yet checked:**
- `setup_steps` / `teardown_steps` step contents.
- That `main_sequence` names an existing sequence.
- That a `steptype` is a known type.
- Contents of `input_mapping`/`output_mapping` (type validity, required sub-keys).
- That referenced locals/globals are declared, or that required globals exist.
- That `module`/`method_name` resolve at load time.
