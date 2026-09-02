<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# PyPTS best practices — how to write a recipe

The conventions PyPTS *proposes*. None of them is enforced: a recipe that ignores
every one of them runs exactly the same. They are here because a bench with twenty
recipes written twenty different ways is harder to work with than the sum of its
recipes, and because the framework quietly rewards the ones below — the Report
picks them up without being told to.

**This is a living document. It is small on purpose, and it grows one practice at
a time, as the framework grows something that makes the practice worth having.**
`recipe_guide.md` is the reference for what a recipe *can* say; this is the opinion
about what it *should*.

---

## 1. Identify the unit under test in the first step

Name the step `get_serial_number`, make it a `UserWrite`, and store the answer in
the **`serial_number` global**:

```yaml
name: LED driver acceptance
version: 0.2                         # the pypts this recipe was written for
report_metadata: [serial_number]     # the default - it may be left out
---
sequence_name: Main
steps:
  - steptype: UserWrite
    step_name: get_serial_number
    message: Scan or type the serial number of the unit under test.
    outputs:
      output: {type: global, global_name: serial_number}
```

**What this buys you, for free:**

- `serial_number` becomes a **column in `report.csv`, filled in on every row** —
  so a season of runs concatenates into one table that can be grouped by unit;
- it appears in the **header of `report.html`**;
- the **run folder is renamed** to `<timestamp>_<recipe>_<serial>` when the run
  ends, so a folder can be found by eye;
- the **GUI's top bar shows it** while the run is going, so the operator can see
  which unit the bench believes is in front of them.

**Why it is a convention and not a feature.** The framework has no idea what a
serial number is. It does not ask for one, it has no message for one and no field
for one. What it has is a text prompt and a global scope; `report_metadata` in the
recipe header is the whole of the coupling, and its default value — `[serial_number]`
— is the only place the convention is written down in code.

An earlier design did it the other way round: a `SerialNumberRequest` message and a
serial-number page in the GUI meant the engine itself went and fetched the serial
number of the unit under test, whether or not the recipe wanted one. That is why it
is gone (see `step/step.md` §2.4).

**When your unit has no serial number**, name what it does have:

```yaml
report_metadata: [batch_id, operator]
```

or `report_metadata: []` for a recipe that identifies nothing. A name that is never
set is simply an empty column — no warning, no error. It is a convention.

## 2. Ask for what only a person knows — and nothing else

`UserWrite` is for a value that exists only in the room: a serial number off a
label, a reading from an instrument with no interface, a batch code on a box.

If the software can get it, get it with a `PythonModule` step. A typed value is
slower, and it is wrong sometimes — an operator typing forty serial numbers a day
will transpose two digits eventually, and no recipe can tell that they did.

## 3. Name a step after what it does to the unit

`get_serial_number`, `power_on`, `measure_quiescent_current`. The step name is what
lands in the step table the operator watches, in every row of `report.csv` and in
the report — it is read far more often than it is written, and usually by someone
looking for the step that failed.

## 4. Let a failing measurement finish the run

`continue_on_error` defaults to `True`, and it should usually stay that way: a unit
that fails one measurement should still be fully characterised, because the second
failure is often what explains the first. Reach for `continue_on_error: false` when
carrying on would be **unsafe or meaningless** — the power supply never came up, the
fixture is open — not merely because a measurement failed.

---

*Add a practice here when the framework starts rewarding one. Say what it buys, and
say plainly that it is a convention.*
