<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# core — the mediator

`core.py` is the only file. The Sequencer and Report run as **threads of this process**;
only the HMI is across a process boundary.

## What it owns

- **Three message handlers** — one per link (HMI, Sequencer, Report). Each ends with
  `unhandled()` so no message is silently dropped.
- **Routing** — events from the Sequencer and Logger flow to the HMI and Report. CORE
  never interprets recipe content; it forwards.
- **Shutdown choreography** — `stop_all_modules()` sends `StopSequencer` + `StopHmi`
  first. `StopReport` is held (`stop_report_pending`) until `SequencerStopped` arrives
  (or the deadline expires), so an aborted run's CSV tail and `report.html` are always
  written. See `release_stop_report()`.
- **Heartbeat watchdog** — `check_heartbeats()` tracks the last-seen timestamp for HMI,
  Sequencer and Report. A module silent past `HEARTBEAT_TIMEOUT_S` is logged as a warning;
  silence past `HEARTBEAT_SILENCE_LIMIT_S` triggers a shutdown.
- **Recipe loading** — receives `LoadRecipe` from HMI, validates via `RecipeParser`,
  forwards `RecipeLoaded` (or error) back to HMI and to the Sequencer.
- **Error reporting** — all `ModuleError` messages above WARNING are forwarded to the HMI
  as `ModuleErrorReported`.

## Key constants

| Name | Value | Meaning |
|------|-------|---------|
| `SHUTDOWN_TIMEOUT_S` | 5.0 s | Budget from shutdown request to forced exit |
| `HEARTBEAT_TIMEOUT_S` | 5.0 s | Silence before "module may be dead" warning |
| `HEARTBEAT_SILENCE_LIMIT_S` | 15.0 s | Silence before forced shutdown |
| `POLL_TIMEOUT_S` | 0.01 s | Main loop tick |

## Adding to the routing table

To route a new message through CORE: add a `case` to the appropriate handler
(`handle_hmi_message`, `handle_sequencer_message`, `handle_report_message`). The handler
must end with `unhandled()` — do not add an unreachable `case _`.

## Known gaps / open TODOs (see roadmap)

- Error-handling policy for CORE (§1.11): today CORE logs and forwards; what it *does*
  about critical failures is an open design question.
- `SetConfigParameter` declared in the HMI link but not implemented.
