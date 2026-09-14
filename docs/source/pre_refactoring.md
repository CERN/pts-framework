<!--
SPDX-FileCopyrightText: 2025 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Pre-refactoring architecture reference

This document preserves the design of the **old, single-process pypts engine** as it
existed before the `architecture_refactor` branch. The old code lives in
`src/pypts/old_code/` and is the behavioural reference for every port. Read this when
integrating old functionality into the new architecture.

---

## Old architecture overview

The old engine was a **single process** with two threads:

- **Main thread** — Qt event loop (`QApplication.exec()`), owns the GUI.
- **Recipe thread** — runs `recipe.Recipe.run()`, drives steps, puts events on queues.

A `SimpleQueue` carried events from the recipe thread to a `RecipeEventProxy` (a
`QThread`), which transformed them into Qt signals for the GUI. A second `SimpleQueue`
(`report_queue`) carried `StepResult` objects to a daemon report thread.

There was no CORE process, no message protocol, no heartbeats, no Logger process.

```
python -m package.__main__
  ├── recipe thread     (run_pts() → recipe.Recipe.run())
  ├── RecipeEventProxy  (QThread — translates events → Qt signals)
  ├── report thread     (report_listener daemon)
  └── Qt main thread    (MainWindow, app.exec())
```

---

## Old public API

The user's `__main__.py` looked like this:

```python
from pypts.pts import run_pts
from pypts.startup import create_and_start_gui

api = run_pts()
window, app = create_and_start_gui(api)
exit_code = app.exec()
sys.exit(exit_code)
```

Key old modules (no longer exist at these paths):

| Module | Role |
|--------|------|
| `pypts.pts` | `run_pts()` — starts the recipe thread, returns a `PtsApi` |
| `pypts.startup` | `create_and_start_gui()` — builds `QApplication` + `MainWindow` |
| `pypts.recipe` | `Recipe`, `Sequence`, `Step`, `StepResult`, `ResultType`, `Runtime` |
| `pypts.steps` | `PythonModuleStep`, `SequenceStep`, `IndexedStep`, `UserInteractionStep`, `WaitStep` |
| `pypts.report` | `Report`, `report_listener`, `generate_html_report`, `STOP_LISTENER` |
| `pypts.event_proxy` | `RecipeEventProxy` — the bridge between recipe thread and GUI thread |

---

## Old step types

All were in `pypts.steps` (old) / `src/pypts/old_code/steps.py`. YAML `steptype` values
used the full class name with the `Step` suffix:

| Old `steptype` | New `steptype` | Status in new arch |
|---|---|---|
| `PythonModuleStep` | `PythonModule` | Available |
| `UserInteractionStep` | `UserInteraction` | Available |
| `WaitStep` | `Wait` | Available |
| `UserWriteStep` | `UserWrite` | Available (text-entry mode only; serial-port mode dropped) |
| `IndexedStep` | handled at load time | Reshaped — inline expansion, row-wise |
| `SequenceStep` | — | Dropped (no nested sequences) |
| `UserRunMethodStep` | — | Deprecated (use `UserInteraction` + `PythonModule`) |
| `SSHConnectStep` | — | Not a step type — moves to HAL (Phase 3) |
| `SSHCloseStep` | — | Same as above |
| `UserLoadingStep` | — | Not yet ported |

---

## Old step type details

### `PythonModuleStep`

Loaded a Python module and called a method, read an attribute, or wrote an attribute.
`action_type` was `method`, `read_attribute`, or `write_attribute`. The new architecture
supports `method` only; attribute actions are dropped.

Two loading modes: file-based (path relative to recipe or `cwd`) and resource-based
(`test_package` in the recipe header). Both still work in the new architecture.

### `UserInteractionStep`

Showed a message, optional image, and a set of buttons to the operator. Blocked until one
was clicked. `cancel` / `'cancel'` was hardcoded to stop the run. The new architecture
preserves this behaviour with a cleaner message protocol (`UserPromptRequest` /
`UserPromptResponse`).

### `WaitStep`

Slept for `wait_time` seconds. `wait_time` was an `input_mapping` entry. In the new
architecture it is a direct field on the step.

### `UserWriteStep`

Two modes: `wrt` (text entry → global/local variable) and `ID` (serial-port picker →
`serial_ID` / `serialport` / `baudrate` locals). The `ID` mode is dropped in the new
architecture; `wrt` maps to `UserWrite`.

### `SSHConnectStep` / `SSHCloseStep`

`SSHConnectStep` opened a paramiko client and stored it in the `ssh_client` global.
Required globals: `host`, `user`, `password` / `private_key`, `port`. `SSHCloseStep`
always went in `teardown_steps`. These will move to the HAL layer (Phase 3) rather than
being step types.

### `UserRunMethodStep`

Combined a user prompt with a method call triggered by a specific button. Replaced in the
new architecture by sequencing a `UserInteraction` step followed by a `PythonModule` step.

### `UserLoadingStep`

Prompted the operator to pick a file; stored the path in a global or local variable.
Not yet ported to the new architecture.

### `SequenceStep` / `IndexedStep`

`SequenceStep` called another sequence as a sub-step. Dropped in the new architecture
(no nested sequences).

`IndexedStep` ran a step multiple times with a list of inputs, column-wise. In the new
architecture this is handled at recipe-load time by expanding `indexed: true` inputs into
a row-wise set of parameter combinations; there is no `IndexedStep` class at runtime.

---

## Old report pipeline

```
StepResult → report_queue.put(step_result)
           → report_listener (daemon thread)
           → Report.add_step_result()
           → report.csv  (single file, overwritten each run)
           → finish_reports() → generate_html_report()
```

Key differences from the new architecture:
- Single `./pts_reports/report.csv` overwritten each run → new: per-run folder.
- Stopped via `STOP_LISTENER` sentinel on the queue → new: `StopReport` message from CORE.
- `generate_html_report()` was a standalone function → new: `GenerateReport` message handled inside the Report thread.

---

## Old GUI event handling (`RecipeEventProxy`)

The `RecipeEventProxy` ran as a `QThread`. It read from a `SimpleQueue` where
`recipe.Runtime` put event objects (`pre_run_step`, `post_run_step`, `post_run_recipe`,
etc.) along with `StepResult` / `Step` objects. For each event it constructed a ViewModel
dictionary and emitted a corresponding Qt signal (`Signal(dict)`).

`MainWindow` slots received these dictionaries and updated the UI without importing recipe
types — except for `StepResultModel` (the final tree view), which remained coupled to
`recipe.StepResult`.

In the new architecture the `RecipeEventProxy` is gone. The HMI receives typed message
objects (`StepStarted`, `StepFinished`, `RunFinished`, etc.) from CORE via the
`QueueWrapper` poll thread, and emits Qt signals to the main thread directly.

---

## Magic globals (old convention, no longer needed)

The old engine read certain globals by convention at runtime. These are not used in the
new architecture and can be removed from ported recipes:

| Global | Old use |
|--------|---------|
| `cancel_key` | Button label that cancels the run |
| `ssh_client` | Paramiko SSH client handle |
| `ID_key` | Triggers serial-port picker in `UserWriteStep` |
| `wrt_key` | Triggers text-entry in `UserWriteStep` |
| `loadFile_key` | Triggers file picker in `UserLoadingStep` |

---

## Old recipe format differences

The recipe YAML format is largely the same. Key differences:

- `steptype` values used to include the `Step` suffix (e.g. `PythonModuleStep`).
- `setup_steps` / `teardown_steps` / `parameters` / `outputs` are still parsed but
  `parameters` and `outputs` are not yet used in the new engine.
- `continue_on_error` and `critical` at the step level are parsed but not enforced in
  the new engine (roadmap M-6/M-7).
- The old engine required `main_sequence: Main` explicitly; the new engine defaults to the
  first sequence if `main_sequence` is absent.

For the full old-engine recipe format specification, including all 28 audit findings,
see `resources/roadmap/recipe_guide.md`.
