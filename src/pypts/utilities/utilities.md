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

All four send through the instance's `core` attribute (its `QueueWrapper` outbox to CORE),
via `send_module_error()`. An instance **without** `core` does not raise: the failure is
written straight to the log instead (an ERROR line plus the DEBUG details and traceback), so
a driver or a half-built object under test still records what went wrong.

Both decorators take two optional arguments: `module_name` (the `ModuleError.source`;
defaults to the decorated function's module, resolved once at decoration time) and
`severity` (default `ErrorSeverity.ERROR`). `operation` is always the function's
`__qualname__`. `report_error()` / `report_problem()` take `severity`, `source` and
`operation` as keyword arguments; `source` defaults to the instance's class module.
`report_error()` must be called inside the `except` block — the traceback comes from
`traceback.format_exc()`.

Nothing here writes the operator's line in the normal path: CORE logs the `ModuleError` it
receives (`core/core.md` → *Error reporting*). `message` is therefore operator-facing text.

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

Both halves of the heartbeat protocol, kept together so they cannot drift.

- `HeartbeatManager(outbox, source, interval_s=DEFAULT_INTERVAL_S)` — the sending half.
  `tick()` is cheap enough to call every loop iteration and sends a `Heartbeat` at most once
  per `DEFAULT_INTERVAL_S` (1.0 s). Used by the Sequencer, the Report and the HMI towards
  CORE, and by CORE towards the HMI.
- `HeartbeatWatch(source=CORE, timeout_s=HEARTBEAT_TIMEOUT_S, fatal_s=HEARTBEAT_FATAL_S)` —
  the receiving half used by the **HMI** to watch CORE (`HmiClient.check_core_is_alive()`).
  `note()` on each beat, `silent_for()`, `is_silent()` (past the timeout — worth reporting),
  `is_lost()` (past the fatal limit — worth acting on) and a `reported` flag for one report
  per outage. It starts counting at construction, not at the epoch. CORE does not use it: it
  tracks its three modules in its own `_ModuleState` table.
- Module name constants: `HMI`, `SEQUENCER`, `REPORT` (the modules CORE watches, and the keys
  of its table) and `CORE` (the source of CORE's own heartbeat to the HMI). Defined here, not
  in `core.py`, so the names are spelled once for CORE and the three modules alike.
- Timeout constants: `HEARTBEAT_TIMEOUT_S` (5.0 s — a WARNING, costs nothing if wrong) and
  `HEARTBEAT_FATAL_S` (15.0 s — ends the run). Deliberately different numbers: the two
  thresholds do different jobs.

### `local_storage.py`

Naming the files and folders pypts writes; it does not decide *where* they go (that is the
configuration's `paths.reports_dir`, passed in by the caller, so this module stays free of
the configuration).

- `get_log_file_path(folder)` — creates `folder` and returns
  `<folder>/pypts_<YYYYmmdd_HHMMSS>.log` as a string, in naive local time (the Logger
  uses local time too). `LOG_FILE_PREFIX = "pypts"`. The launcher calls it with the reports
  folder (the session log), the Sequencer with a run folder (the run log).
- `make_run_folder(reports_dir, recipe_name)` — creates and returns
  `<reports_dir>/<YYYYmmdd_HHMMSS>_<recipe name>` (`safe_name_part()`: non-alphanumerics
  become `_`, at most 60 characters; `recipe` if nothing is left; `_2`, `_3`… in the same
  second). Raises `OSError` if it cannot. Called by the Sequencer at every run start, and by
  the Report only when `RunStarted` names no folder.
- `next_log_file_path(current)` — a new run log beside `current`, named by
  `get_log_file_path()`; if that name is `current` or already exists (same second), `_2`,
  `_3`… is added, so the Logger never just appends to an old file. The GUI calls it when the
  operator unloads the recipe.
- `ensure_folder_exists(path)` — `os.makedirs(..., exist_ok=True)` wrapper.
- The timestamp is taken at call time. The launcher calls `get_log_file_path()` once at
  startup (`launcher/startup.py`) and hands the path to every process; after that only an
  unload starts a new session file (`next_log_file_path()`). A run's own log is a detour
  the Logger takes and returns from (`logger/log.py` `start_run_log()` / `end_run_log()`).

### `common.py`

Small helpers shared across modules: `RESTART_EXIT_CODE` (75 - the GUI process's exit code
asking the launcher to start pypts again, see `launcher/launcher.md` → *Restart*; here because
neither side may import the other), `ignore_keyboard_interrupt()`, `convert_string_to_int()`,
and `describe_value()` / `describe_step_values()` - a step's text values as the CLI, headless
mode and the step table's tooltip show them (`outputs: voltage = 12.1 (range 11 .. 13)`, M-3).
Also `SECRET_KEY_WORDS`, `MASK`, `is_secret_key()` and `masked()`: which configuration keys
are secrets, and a copy of a mapping fit for a log (the config dump, the hardware layer's call
trace).

### `recent_recipes.py`

`RecentRecipes` — the GUI's "recent recipes" list. The GUI builds one and keeps it; it holds
no Qt and no messages.

- **State, not a cache**: stored as JSON at `file_locations.recent_recipes_path()` (under
  `state_dir()`), not in a cache directory that cleanup tools may wipe.
- **References, not copies**: each `RecentEntry(path, recipe_name, opened_at)` is a resolved
  path; opening one re-reads the file from disk. At most `MAX_ENTRIES` (10), newest first.
- `entries()`, `remember(path, name)` (called only after CORE answered `RecipeLoaded`),
  `forget(path)` (a remembered file that is gone), `clear()`.
- **Discarded, never repaired**: an unreadable file, or one whose `version` is not
  `STORE_VERSION` (1), is dropped for the run with a WARNING; one unusable entry costs only
  itself. Saves are atomic (temporary file + `os.replace`). **Nothing here raises.**

## Rules

- None of these files may import from `core/`, `sequencer/`, `report/`, `recipe/`, `step/`,
  `hmi/`, `api/` or `launcher/`. They are infrastructure; they must not depend on business
  modules. What they do import today: `logger/log.py` (`error_handling`, `recent_recipes`),
  `messages/common_messages.py` (`error_handling`, `heartbeat_manager`) and
  `config_handler/file_locations.py` (`recent_recipes`).
- `heartbeat_manager.py` imports nothing of pypts but `common_messages`.
- `common.py` and `local_storage.py` import nothing of pypts.
