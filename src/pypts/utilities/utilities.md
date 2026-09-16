<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# utilities — shared infrastructure

No business logic. Each file has one narrow job.

## Files

### `error_handling.py`

Two decorators, two functions — pick carefully:

| Name | Use for | On failure |
|------|---------|------------|
| `@catch_and_report_errors()` | Event loop methods | Sends `ModuleError`, returns `None`, loop continues |
| `@report_and_reraise()` | Step execution layer | Sends `ModuleError`, re-raises so `StepResult` gets `ERROR` |
| `report_error(self, exc, severity=…)` | Recognised exceptions | Sends `ModuleError`, does not raise |
| `report_problem(self, message, severity=…)` | Refusals / bad state | Sends `ModuleError`, does not raise |

All four require the decorated/calling class to have a `core: QueueWrapper` attribute.

The decorators are the net for **unexpected** failures. For **recognised** failures, handle
them with `except SpecificError:` and call `report_error` / `report_problem` explicitly.

**Where `@catch_and_report_errors()` goes (roadmap §1.49).** The boundary is the *loop tick*,
not the call chain. A method carries it only when a failure inside it has nowhere else to go:

| Carries it | Because |
|------------|---------|
| `poll_core()` | a failure in `inbox.receive()` itself is inside no message handler |
| `handle_core_message()` | one bad message fails alone, without abandoning the rest of the batch |
| `do_periodic_tasks()` | called straight from the loop body; heartbeats depend on it |
| a thread entry point (`start()`, `Sequencer.execute_sequence()`) | there is no outer frame on that thread |

Everything below those is **undecorated** and lets its failure unwind to one of them. Stacking
them down a call chain does not add a net — only the innermost one ever fires — and it lets a
caller carry on as though a swallowed call had worked.

Two rules that follow from it:

- **Never on `main_loop()`.** The `while` is *inside* it, so catching there ends the loop it
  looks like it protects, and the module then stops turning while CORE still believes it is
  alive. The decorator goes on `start()` instead.
- **A thread entry point sends its module's goodbye from a `finally`**, so a loop that died
  rather than ended does not cost CORE its whole shutdown budget. `send_goodbye()` is guarded
  so the ordinary path, where `stop()` already sent it, does not send a second.

### `heartbeat_manager.py`

- `HeartbeatManager` — sends a `Heartbeat` at `DEFAULT_INTERVAL_S` (1.0 s). Each module
  that needs to be watched creates one and calls `tick()` in its event loop.
- Module name constants: `HMI`, `SEQUENCER`, `REPORT` — these must match the keys in
  CORE's heartbeat tables. They are defined here (not in core.py) so the Debug Monitor can
  import just the constants without pulling in the whole engine.
- Timeout constants: `HEARTBEAT_TIMEOUT_S` (5.0 s), `HEARTBEAT_SILENCE_LIMIT_S` (15.0 s).

### `local_storage.py`

- `get_log_file_path(logs_dir)` — returns the timestamped log file path for this run.
- `ensure_folder_exists(path)` — `os.makedirs(..., exist_ok=True)` wrapper.
- The name and location of the log file are set once by the launcher and shared with all
  processes. `local_storage` must not be called more than once per run for the log path.

### `common.py`

Small helpers shared across modules: `RESTART_EXIT_CODE` (75 - the GUI process's exit code
asking the launcher to start pypts again, see `launcher/launcher.md` → *Restart*; here because
neither side may import the other), `ignore_keyboard_interrupt()`, `convert_string_to_int()`,
and `describe_value()` / `describe_step_values()` - a step's text values as the CLI, headless
mode and the step table's tooltip show them (`outputs: voltage = 12.1 (range 11 .. 13)`, M-3).

### `data_removal.py`

Utilities for sanitising step inputs before they appear in the log or CSV — placeholder;
the redaction seam is not yet designed (see `plans/README.md` deferred items).

### `recent_recipes.py`

Maintains a list of recently opened recipe file paths in local storage. Used by the GUI to
populate the "recent recipes" menu.

## Rules

- None of these files may import from `core/`, `sequencer/`, `report/`, `hmi/`, or
  `launcher/`. They are infrastructure; they must not depend on business modules.
- `heartbeat_manager.py` imports almost nothing on purpose — the Debug Monitor needs its
  constants without loading the rest of the engine.
