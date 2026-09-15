<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# sequencer — executes recipes

`sequencer.py` is the only file. Runs as a **thread of the Core process**.

## What it owns

- **Event loop** — `sequencer_main()` polls `from_core`, dispatches to handlers,
  sends heartbeats. `@catch_and_report_errors()` on each handler keeps the loop alive
  through individual message failures.
- **Recipe execution** — `run_sequence()` starts a worker thread for `execute_sequence()`.
  The event loop keeps turning while the sequence thread runs; this is what lets
  heartbeats keep flowing and `StopSequence` be processed mid-run.
- **`execute_sequence()`** — resolves the sequence, builds a `Runtime`, emits
  `RunStarted`, calls `run_sequence_body()` from the step layer, emits `RunFinished`.
  Also watches `report_metadata` globals and forwards `RunMetadata` updates to CORE.
- **Operator interaction** — `ask_operator()` puts a `UserPromptRequest`,
  `UserTextRequest` or `UserPathRequest` on the CORE link and blocks in `PendingRequests.wait()` until the
  response arrives. The event loop must keep turning; `ask_operator` runs on the sequence
  thread, not the event loop thread.
- **Stop** — `stop_running_sequence()` sets `stop_requested` and joins the sequence thread
  up to `SEQUENCE_JOIN_TIMEOUT_S` (2 s). If the thread is still alive after that, it
  reports `CRITICAL` via `report_problem()` and continues the shutdown. `SequencerStopped`
  is sent after the join, so it always arrives after any `RunFinished` on the same queue.

## Threading rules

- The event loop runs on its own thread (started by `Core.start_submodules()`).
- `execute_sequence()` runs on a **separate worker thread** per sequence run.
- `ask_operator()` blocks on the worker thread while the event loop delivers the response.
- `stop_requested` is a plain `bool` (not an `Event`) — the step layer checks it
  **between** steps; within a step, behaviour is step-specific.

## Key constants

| Name | Value | Meaning |
|------|-------|---------|
| `SEQUENCE_JOIN_TIMEOUT_S` | 2.0 s | How long `stop()` waits for the sequence thread |

## Known gaps

- `WaitStep` does not honour `stop_requested` mid-sleep (step layer issue, not sequencer).
