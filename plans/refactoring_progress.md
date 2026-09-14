<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# PyPTS refactoring progress

Compiled from roadmap §1 and plans 001–005. Ordered roughly chronologically.
Individual plan files (001–005) were removed after this document was created.

---

## Process skeleton and infrastructure

- **Package layout** — full `src/pypts/` tree created: `core/`, `sequencer/`, `recipe/`,
  `step/`, `report/`, `hmi/{gui,cli}/`, `config_handler/`, `logger/`, `stream_handler/`,
  `hardware_layer/`, `helper_applications/`, `utilities/`, `launcher/`, `old_code/` (frozen).
- **Process model (§1.5)** — `launcher/startup.py` with `--mode gui/cli` (gui default) and
  `--log-level`; spawns Logger and Core as processes, GUI as a third. Core runs Sequencer and
  Report as its own threads. No `fork` on any platform.
- **Spawn start method pinned (plan 005, §1.37-like)** — `main()` calls
  `set_start_method("spawn")` as its very first statement; test asserts it is idempotent.
- **Logger process** — single-writer, timestamped format (file:function, ms), file + stdout
  handlers, `set_stdout_logging_enabled()` toggle, level resolved once by the launcher.
- **`--mode connect` removed** — was accepted by argparse but had no branch; now an argparse
  error instead of a silent lie.
- **`--mode cli` no longer imports PySide6 (§1.37)** — import moved into the `gui` branch of
  `main()`; test pins this in a fresh interpreter.

## Typed messaging (§1.1)

- **Frozen dataclasses** replaced the enum + `payload: dict` protocol — one class per
  message, one union per link, one generic `QueueWrapper` for all six links.
- **`unhandled()`-closed handlers** — a forgotten message raises instead of being dropped.
- **QueueWrapper trace** — `send()` and `receive()` each log one DEBUG line naming the link
  and the message. Both directions, so a sent-but-never-received message is visible.
- **`drain()`** — bounded batch per tick instead of one message per 10 ms.
- Defects closed by construction: Core had no branch for HMI error messages; Sequencer had no
  branch for `StopSequence`; CLI never acknowledged `StopHmi`; launcher used `terminate()` as
  primary shutdown (now asks first, terminates only on timeout).
- **Sequencer worker thread (§1.8)** — `RunSequence` starts the thread and returns; event
  loop keeps turning; `PendingRequests.wait()` on the sequence thread is answered by
  `deliver_response()` on the loop thread.
- **mypy over messages and handler modules (§1.9)** — runs in CI; flags incomplete `match`
  statements at edit time.
- Adding a message is two edits (declare in link module + handle with a `case`).

## Error handling

- **Two decorators (§1.10)** — `@catch_and_report_errors()` (report + continue, for event
  loops) and `@report_and_reraise()` (report + re-raise, for the execution layer).
- **`report_error()` / `report_problem()` (§1.11)** — for failures a method recognises; name
  the module, the method and the exception type. Neither raises; the call site keeps control.
- **HeartbeatManager** — ticking from Sequencer/Report/HMI; Core-side timeout detection armed
  only for modules still expected to run.

## Configuration (§1.3)

- **`ConfigHandler` singleton** in the platform's per-user config directory (`platformdirs`).
- **Four small modules**: `file_locations.py`, `configuration_schema.py`, `template_writer.py`,
  `config_handler.py`.
- **Versioned + typed** — `CONFIG_VERSION` checked on load; typed access via schema; `get_parameter()`
  returns `Path`, `int` or `bool`, never a string.
- **No migration/repair** — a broken or version-mismatched file is discarded whole for the
  run; template defaults used in memory; launcher shows a startup notice; ERROR in the log.
- **Reading is pure** — only `bootstrap()` (called once by the launcher) may create the file.
- **Opened explicitly (plan 004)** — `_read_raw()` uses `open()` + `read_file()` so an
  unreadable file reports "exists but cannot be opened" not "version 0".
- **Schema/template agreement** asserted by `test_schema_and_template_agree` in CI.
- Stale `%TEMP%/pypts/config/config.ini` no longer read.

## Logging / debug trace (§1.2)

- **`--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}`** overrides `[logging] level` in
  `config.ini`; ships as `DEBUG` for the refactor (reverts to `INFO` before v1.0).
- **`--mode debug` and debug console removed** — replaced by the message trace in the log and
  the Debug Monitor. The framework has one build.
- **`--debug-monitor` flag (§1.4.1)** — on by default for the refactor; starts the Debug
  Monitor helper app via `subprocess.Popen`; reverts to opt-in before v1.0.

## Debug Monitor (§1.4)

- **Helper application** in `helper_applications/debug_monitor/` — reads the run log, renders
  the message trace (filterable by link, free text, heartbeats), and a Modules tab with
  state + liveness derived from the log.
- Framework has no knowledge of it; nothing in `src/pypts/` (outside the app itself) imports
  it.
- **32 tests** — parser and liveness fold are pure functions, tested without Qt or a running
  framework.
- Replay of past runs is the same code path as live tail.

## Execution engine (§1.13–§1.16)

- **`recipe/` data layer** — `Recipe.from_file()` / `Recipe.from_yaml_text()`; loud
  `RecipeError`s on malformed input; `base_dir` for relative module paths.
- **`step/` base lifecycle** — `Step.run()`, `StepResult`, `Runtime`, step registry replacing
  `eval()`.
- **`execute_sequence()` real** — runs the requested sequence, emits every run event
  (`RunStarted`, `SequenceStarted`, `StepStarted`, `StepFinished`, `SequenceFinished`,
  `RunFinished`); `StopSequence` honoured between steps.
- **`Core.load_recipe()` / `Core.start_sequence()` real** — recipe loaded, live object handed
  off to Sequencer via `RunSequence`.
- **`UseRecipe` moved to `RunSequence` (§1.42)** — live `Recipe` travels with the run start
  command, not at load time.
- **Step types ported**: `Wait`, `PythonModule` (method only; file-based + resource-based
  loading), `UserInteraction` (prompt + buttons + exactly-once answer guard), `UserWrite`
  (text-entry mode; `ID`/serial-port mode dropped), `IndexedStep` (handled at load time,
  row-wise expansion).
- **Step types dropped**: `SequenceStep` (no nested sequences), `UserRunMethodStep`
  (deprecated), SSH pair (moves to HAL Phase 3).
- **`continue_on_error` default (§1.28)** — an ERROR no longer abandons the sequence by
  default; per-step flag honoured.

## GUI (§1.14, §1.15, §1.20–§1.22)

- **PySide6 migration** — PyQt6/LGPL conflict resolved; `test_pyside6_conversion.py` pins it.
- **Old GUI studied** — 868 lines + proxy + command loop written up in `gui.md`.
- **Scaffold vendored** as a PySide6 port; license clearance from upstream author still owed.
- **Four-panel operator screen**: top bar (Open/sequence dropdown/Start/Stop), UUID-keyed step
  table, CenterView stack (logo/prompt/serial pages), status line.
- **Visual parity with master (§1.20)** — full light/dark theme, `LogPanel`, `InteractionPanel`
  (image + keyboard nav + prompted buttons), `ResultsPanel` (PASS/FAIL/TOTAL badges + flat
  `StepOutcome` tree), SVG-icon toolbar with pause, browse/pause mode.
- **LogPanel (§1.22)** — tails the run log file at INFO and above, every 200 ms.
- **`force_light_mode()`** — pins light scheme; dark mode deferred.
- Window [X] triggers the shutdown handshake.

## Report (§1.19, plan 001)

- **Per-run folder** with incremental CSV growing step by step and `report.html` generated on
  `RunFinished`.
- **`ReportReady` message** — operator told where the output is; GUI "Open report folder"
  button.
- **State hardening (plan 001)** — `start_run()` clears state before `make_run_dir()`; a
  failed mkdir leaves the Report in "no run open" state. `safe_name` capped at 60 chars.

## Shutdown (plan 002)

- **`stop_all_modules()`** holds `StopReport` in a flag until `SequencerStopped` arrives.
- **`release_stop_report()`** sends it exactly once — from `SequencerStopped` handler or
  from the shutdown deadline path.
- **Sequencer join timeout** reports CRITICAL to the operator instead of a bare log line.

## Test coverage (plan 003)

- **Core tests** — shutdown routing, heartbeat recording, poison-message survival.
- **Sequencer tests** — mid-run abort with partial outcomes.
- **Message tests** — `wait_until_stopped` fast path and grace-period timeout.
- **Startup tests** — `stop_core()` normal, wedged, no-process no-op; monitor log-wait timeout.
- Quality gates on the completed plans batch: **408 passed / 43 skipped**, ruff clean, mypy clean.

## Verificator (Phase 0)

- **Broken import fixed** — `verify_recipe.py` + `recipe_rules.py` replaced entirely.
- New verificator in `helper_applications/recipe_verificator/` imports only from
  `pypts.recipe.rules` (the authoritative schema source).
- Returns `list[ValidationIssue]` with severity, field path, message, hint, and line number.
- Collects all problems in one pass (no bail-out on first error).

## Licensing and docs

- **LGPL-2.1-or-later + CC-BY-SA-4.0**, SPDX headers, `reuse.toml`, `licenses/` — REUSE
  compliance largely in place.
- `dependency_license_analysis.rst` in Sphinx docs.
- Module context `.md` files created for every module under `src/pypts/`.
- `docs/source/` rewritten for the current architecture; `pre_refactoring.md` preserves the
  old-engine design as a reference.
