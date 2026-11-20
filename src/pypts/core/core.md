<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# core — the mediator

`core.py` is the only file. `core_main()` is the Core process's entry point: it ignores
Ctrl+C (`ignore_keyboard_interrupt()` — the launcher decides when pypts stops), routes log
records to the Logger (`init_logging()`, the only call in this process — the threads inherit
it), opens the configuration for writing and runs `Core().start()`.

The Sequencer and the Report run as **daemon threads of this process**, started by
`start_submodules()` and joined by `join_submodules()`; only the HMI is across a process
boundary. CORE builds the four in-process links itself (plain `queue.Queue`, named from
`messages/links.py`) and receives the HMI link from the launcher.

## What it owns

- **Three message handlers** — `handle_hmi_message`, `handle_sequencer_message`,
  `handle_report_message`, one per link. Each ends with `unhandled()` so no message is
  silently dropped. `poll()` wraps each inbox: CORE cannot use `@catch_and_report_errors()`
  (it is the module errors are reported *to*), so a failure while handling a message is
  logged and the rest of that batch stays queued for the next tick. The two periodic calls
  (`do_periodic_tasks()`, `check_stop_status()`) are guarded in `main_loop()` too, but a
  failure there is not carried past: it is reported through `report_own_error()` and starts
  the ordinary shutdown, because a broken periodic task repeats every tick. If it strikes
  again while already shutting down — the shutdown checker itself is what is broken, so
  nothing would ever clear `running` — CORE just leaves the loop.
- **Routing** — CORE never interprets recipe content; it forwards the same object. See
  *Routing table* below.
- **Recipe loading** — `load_recipe()` handles `LoadRecipe` with `Recipe.from_file()`. On
  success CORE **keeps the `Recipe`** (`self.recipe`, the only copy) and sends the HMI
  `RecipeLoaded`; the Sequencer is told nothing. Each entry of `recipe.load_notices` (a
  version mismatch, missing pictures) is shown to the operator as a `ModuleError` (severity
  ERROR) — the recipe still loads. On failure
  (`RecipeError`, or any other exception out of the parser) nothing is kept and the error
  goes out through `report_own_error()`.
- **Recipe unloading** — `unload_recipe()` handles `UnloadRecipe`: it sets `self.recipe` to
  None (INFO `Recipe "<name>" unloaded.`; DEBUG only when nothing was loaded), sends the
  Sequencer `ForgetRecipe`, and answers the HMI `RecipeUnloaded` either way. It does not check
  for a run in progress — the frontend does not offer it then, as for `LoadRecipe`.
- **Starting a run** — `start_sequence()` answers `StartSequence` by sending
  `RunSequence(self.recipe, sequence_name, excluded_step_ids, write_report)`. That is the
  **only** way the recipe reaches the Sequencer, which keeps only the last run's until
  `ForgetRecipe`. The two engineering-mode fields are copied unread. With no recipe loaded —
  before the first load or after an unload — CORE refuses it itself and tells the operator.
- **A run without a report** — `self.run_has_report` is set from each `RunStarted.write_report`
  and put back to True once that run's `RunFinished` is routed. While it is False (the GUI's
  engineering-mode retest) `RunStarted`, `SequenceStarted`, `RunMetadata` and
  `RunFinished` go to the HMI only, no `GenerateReport` is sent, and `StepExecuted` is dropped
  (one DEBUG line at `RunStarted` says so). CORE routes on the Sequencer's `RunStarted`, not on
  the `StartSequence` it relayed, because the Sequencer may refuse the run.
- **Error reporting** — `handle_module_error()` writes two or three records per
  `ModuleError` (`logger/logging_rules.md` §7): one operator line at the level in
  `LOG_LEVEL_FOR_SEVERITY`, naming the part of the software through `describe_source()` /
  `FRIENDLY_SOURCE_NAME` (unknown sources read "the software"), one DEBUG line with
  operation, exception type and severity, and a separate DEBUG traceback record only when a
  traceback is present. Anything that is not a WARNING is also sent to the HMI as
  `ModuleErrorReported`. CORE's own failures go through `report_own_error()`, which builds the
  same `ModuleError` by hand — CORE has no outbox to itself, so `report_error()` cannot be used.
- **Heartbeats, both directions.**
  - *Outgoing*: `hmi_heartbeat` (a `HeartbeatManager` with source `CORE`) beats towards the
    HMI only, first thing in `do_periodic_tasks()`, and keeps beating during shutdown so the
    HMI does not read the silence as a dead engine. The threads get none — they die with CORE.
  - *Watchdog*: `self.modules` holds one `_ModuleState` per watched module (HMI, Sequencer,
    Report): `running`, `last_heartbeat` (None until first heard from), `heartbeat_lost`,
    `start_reported`. For modules still running: never heard from past `HEARTBEAT_TIMEOUT_S`
    → one DEBUG "has not started yet" (does not end the run; DEBUG because a slow GUI
    start is routine); silent past
    `HEARTBEAT_TIMEOUT_S` → one WARNING per outage, cleared when it answers again (INFO
    "responding again"); silent past `HEARTBEAT_FATAL_S` → `end_run_for_silent_module()`
    reports a CRITICAL `ModuleError` (source from `MODULE_SOURCE`; with a run open it adds
    `BENCH_MAY_BE_ENERGISED`) **then** takes the crash close, `close_at_once()`. There is no
    setting to turn this off. The watchdog stays on through an orderly close, which has no
    deadline, and stops once `closing_at_once` is set.
  - Operator lines use `FRIENDLY_MODULE_NAME`. The developer's DEBUG lines name the module
    alone, measurements on a line of their own: `Heartbeat timeout for module: <name>`,
    `Heartbeat fatal for module: <name>`, `Module is responding again: <name>`.
- **Shutdown choreography** — two closes, no deadline in either. `send_stop()` tells each
  module to stop exactly once (`stop_sent`), whichever close sends it.
  - *Orderly* (`ShutdownRequested()`): `stop_all_modules()`, idempotent (a frontend may ask
    more than once), logs `Shutting down.` and sends `StopSequencer`. The Sequencer lets a
    running test finish its step and its teardown steps (`sequencer/sequencer.md`, *Stop*),
    however long that takes. `SequencerStopped` → `StopReport`, so the stopped run's CSV tail
    and `report.html` are written first; `ReportStopped` → `StopHmi`, so the frontend has
    shown everything the other two said. `check_stop_status()` ends the loop once all three
    have stopped, and `join_submodules()` then joins both threads with no timeout.
  - *Crash* (`ShutdownRequested(immediate=True)` — the CLI's Ctrl+C, the launcher's
    `stop_core()` — and the watchdog): `close_at_once()` sends the stop to every module still
    running, waits for nothing, and leaves; `join_submodules()` does not join (the threads
    are daemons, a Sequencer thread may be stuck in a step). Overtaking an orderly close, it
    stops whatever is left. With nothing left running (the launcher after an orderly close) it
    only lets CORE leave, DEBUG only. Otherwise it logs `pypts is closing at once.` (INFO), or,
    with a run open (`run_open`, RunStarted to RunFinished), a CRITICAL ending in
    `BENCH_MAY_BE_ENERGISED`: the run's teardown never runs and the driver processes end
    with CORE without `teardown()`. The watchdog's own CRITICAL says it instead
    (`warn=False`).
  - A module that dies during an orderly close stops beating, and the watchdog turns the wait
    into a crash close. Nothing is killed — the threads are daemons and the HMI process
    belongs to the launcher.
- **Configuration changes** — CORE is pypts' runtime writer of `config.ini` (the Recipe
  Editor v2, a process of its own, writes its own `[recipe_editor]` lines — `config_handler.md`).
  `core_main()` calls `ConfigHandler.open_for_writing()` before `Core()` is built (its first
  read would otherwise make the process a reader, which cannot be promoted).
  `set_config_parameter()` refuses `READ_ONLY_SECTIONS`, writes through
  `ConfigHandler().set_parameter()` (which parses against the schema and refuses a discarded
  file), and answers every request with `ConfigParameterResult` — refusals are logged at
  WARNING and answered (`refuse_config_parameter()`), never only logged. In force from the
  next start; nothing is propagated to running modules. See `config_handler/config_handler.md`
  → *Writing*.

## Routing table

| Message | Goes to |
|---|---|
| `StopSequence`, `PauseSequence`, `ResumeSequence`, the three `User*Response` | Sequencer |
| `UnloadRecipe` | handled by CORE, which then sends `ForgetRecipe` to the Sequencer and `RecipeUnloaded` to the HMI |
| `RunStarted`, `SequenceStarted`, `RunMetadata` | Report **and** HMI (`relay_run_event()` for the first two); HMI only for a run without a report |
| `RunFinished` | Report (followed by `GenerateReport` on the same queue) and HMI; HMI only for a run without a report |
| `SequenceFinished`, `StepStarted`, `StepFinished`, `RunPaused`, `RunResumed`, the three `User*Request` | HMI only |
| `StepExecuted` | Report only — it must never cross the HMI boundary; dropped for a run without a report |
| `ReportGenerated` | HMI, as `StatusChanged` **and** `ReportReady(report_path, report_dir)` |
| `ReportExported` (not sent yet) | HMI, as `StatusChanged` |

Handled by CORE itself: `ShutdownRequested` (orderly, or with `immediate=True` the crash close), `HmiStopped` / `SequencerStopped` /
`ReportStopped`, `LoadRecipe`, `UnloadRecipe`, `StartSequence`, `SetConfigParameter`, `Heartbeat`,
`ModuleError`. `RunPaused` / `RunResumed` skip the Report: a hold changes when steps run, not
what they produce.

## Key constants

| Name | Where | Value | Meaning |
|------|-------|-------|---------|
| `HEARTBEAT_TIMEOUT_S` | `utilities/heartbeat_manager.py` | 5.0 s | Silence before a WARNING |
| `HEARTBEAT_FATAL_S` | `utilities/heartbeat_manager.py` | 15.0 s | Silence that takes the crash close |

No shutdown constant: neither close has a deadline. The launcher's `CORE_SHUTDOWN_TIMEOUT_S` (`launcher.md`) is the last resort for a wedged CORE.

The main loop sleeps 10 ms per tick (a literal in `main_loop()`, not a constant).

## Adding to the routing table

To route a new message through CORE: add a `case` to the handler for the link it arrives on
(`handle_hmi_message`, `handle_sequencer_message`, `handle_report_message`). The handler
must end with `unhandled()` — do not add an unreachable `case _` of your own. Update the
routing table above and `messages/messages.md` in the same change.

A new module whose `ModuleError`s the operator may see belongs in `FRIENDLY_SOURCE_NAME`;
a new watched module needs entries in `self.modules`, `FRIENDLY_MODULE_NAME` and
`MODULE_SOURCE`.

## Known gaps / open TODOs (see roadmap)

- Error-handling policy for CORE (§1.11): today CORE logs, shows the operator and shuts down
  only for a silent module or for a failure of its own periodic machinery. What it *does*
  about other critical failures is an open design question.
- `ExportReport` has no trigger in CORE; only the `ReportExported` receiving branch exists.
