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
  logged and the rest of that batch stays queued for the next tick.
- **Routing** — CORE never interprets recipe content; it forwards the same object. See
  *Routing table* below.
- **Recipe loading** — `load_recipe()` handles `LoadRecipe` with `Recipe.from_file()`. On
  success CORE **keeps the `Recipe`** (`self.recipe`, the only copy) and sends the HMI
  `RecipeLoaded`; the Sequencer is told nothing. A non-empty `recipe.version_notice` is shown
  to the operator as a `ModuleError` (severity ERROR) — the recipe still loads. On failure
  (`RecipeError`, or any other exception out of the parser) nothing is kept and the error
  goes out through `report_own_error()`.
- **Starting a run** — `start_sequence()` answers `StartSequence` by sending
  `RunSequence(self.recipe, sequence_name)`. That is the **only** way the recipe reaches the
  Sequencer — it holds nothing between runs. With no recipe loaded CORE refuses it itself
  and tells the operator.
- **Error reporting** — `handle_module_error()` logs every `ModuleError` twice
  (`logger/logging_rules.md` §7): one operator line at the level in `LOG_LEVEL_FOR_SEVERITY`,
  naming the part of the software through `describe_source()` / `FRIENDLY_SOURCE_NAME`
  (unknown sources read "the software"), and one DEBUG line with operation, exception type
  and traceback. Anything that is not a WARNING is also sent to the HMI as
  `ModuleErrorReported`. CORE's own failures go through `report_own_error()`, which builds the
  same `ModuleError` by hand — CORE has no outbox to itself, so `report_error()` cannot be used.
- **Heartbeats, both directions.**
  - *Outgoing*: `hmi_heartbeat` (a `HeartbeatManager` with source `CORE`) beats towards the
    HMI only, first thing in `do_periodic_tasks()`, and keeps beating during shutdown so the
    HMI does not read the silence as a dead engine. The threads get none — they die with CORE.
  - *Watchdog*: `self.modules` holds one `_ModuleState` per watched module (HMI, Sequencer,
    Report): `running`, `last_heartbeat` (None until first heard from), `heartbeat_lost`,
    `start_reported`. For modules still running: never heard from past `HEARTBEAT_TIMEOUT_S`
    → one WARNING "has not started yet" (does not end the run); silent past
    `HEARTBEAT_TIMEOUT_S` → one WARNING per outage, cleared when it answers again (INFO
    "responding again"); silent past `HEARTBEAT_FATAL_S` → `end_run_for_silent_module()`
    reports a CRITICAL `ModuleError` (source from `MODULE_SOURCE`) **then** runs the ordinary
    `stop_all_modules()`. There is no setting to turn this off. The watchdog stops checking
    once `shutting_down` is set.
  - Operator lines use `FRIENDLY_MODULE_NAME`. Three DEBUG lines are **machine-read** by the
    Debug Monitor (`helper_applications/debug_monitor/liveness.py`) — keep their prefix and
    shape: `Heartbeat timeout for module: <name>`, `Heartbeat fatal for module: <name>`,
    `Module is responding again: <name>`.
- **Shutdown choreography** — `stop_all_modules()` is idempotent (the frontend and the
  launcher both ask). It starts the `SHUTDOWN_TIMEOUT_S` deadline and sends `StopSequencer` +
  `StopHmi`. `StopReport` is held (`stop_report_pending`) until `SequencerStopped` arrives,
  so an aborted run's CSV tail and `report.html` are written first — see
  `release_stop_report()`. `check_stop_status()` ends the loop when every module has reported
  itself stopped, or at the deadline: it then releases the held `StopReport`, logs an ERROR
  naming the modules that did not answer, and leaves. Nothing is killed — the threads are
  daemons and the HMI process belongs to the launcher.
- **Configuration changes** — CORE is the single runtime writer of `config.ini`.
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
| `RunStarted`, `SequenceStarted`, `RunMetadata` | Report **and** HMI |
| `RunFinished` | Report (followed by `GenerateReport` on the same queue) and HMI |
| `SequenceFinished`, `StepStarted`, `StepFinished`, `RunPaused`, `RunResumed`, the three `User*Request` | HMI only |
| `StepExecuted` | Report only — it must never cross the HMI boundary |
| `ReportGenerated` | HMI, as `StatusChanged` **and** `ReportReady(report_path, report_dir)` |
| `ReportExported` (not sent yet) | HMI, as `StatusChanged` |

Handled by CORE itself: `ShutdownRequested`, `HmiStopped` / `SequencerStopped` /
`ReportStopped`, `LoadRecipe`, `StartSequence`, `SetConfigParameter`, `Heartbeat`,
`ModuleError`. `RunPaused` / `RunResumed` skip the Report: a hold changes when steps run, not
what they produce.

## Key constants

| Name | Where | Value | Meaning |
|------|-------|-------|---------|
| `Core.SHUTDOWN_TIMEOUT_S` | `core.py` | 5.0 s | Budget from `stop_all_modules()` to leaving without the modules that did not answer |
| `Core.THREAD_JOIN_TIMEOUT_S` | `core.py` | 5.0 s | How long `join_submodules()` waits per thread after the loop ended |
| `HEARTBEAT_TIMEOUT_S` | `utilities/heartbeat_manager.py` | 5.0 s | Silence before a WARNING |
| `HEARTBEAT_FATAL_S` | `utilities/heartbeat_manager.py` | 15.0 s | Silence that ends the run |

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

- Error-handling policy for CORE (§1.11): today CORE logs, shows the operator and — only for
  a silent module — shuts down. What it *does* about other critical failures is an open
  design question.
- `ExportReport` has no trigger in CORE; only the `ReportExported` receiving branch exists.
