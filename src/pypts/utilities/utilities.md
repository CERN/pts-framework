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

Small helpers shared across modules: `format_duration()`, `truncate_string()`, and similar
utility functions that belong to no specific module.

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
