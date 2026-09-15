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
- **Pause / Resume** (GUI only) — `PauseSequence` sets `pause_requested` (ignored with no
  sequence running); `ResumeSequence` clears it. The step layer calls the Runtime seam
  `hold_if_paused(step_name, position, total)` before every main step; `Sequencer.hold_if_paused()`
  returns at once unless a pause is pending, otherwise sends `RunPaused`, polls every
  `HOLD_POLL_S` until Resume or Stop, then sends `RunResumed` (whichever ended it). So the
  running step always finishes first, and a Stop during a hold ends the hold and then skips
  the remaining steps as usual. `drop_pending_pause()` runs once after the main steps and
  before teardown: a pause that found no step to hold before lapses there, with the INFO
  line "The run was not paused: no steps were left." (not logged if the run was stopped).
  Teardown is never held. A Resume before the hold began sends nothing. The Report never
  sees either event.

## Threading rules

- The event loop runs on its own thread (started by `Core.start_submodules()`).
- `execute_sequence()` runs on a **separate worker thread** per sequence run.
- `ask_operator()` blocks on the worker thread while the event loop delivers the response.
- `stop_requested` is a plain `bool` (not an `Event`) — the step layer checks it
  **between** steps; within a step, behaviour is step-specific.
- `pause_requested` is a plain `bool` too. It is set and cleared on the event loop and
  cleared by the sequence thread in `drop_pending_pause()`; each write is a whole
  assignment, and a late read only moves the hold by one boundary or one poll. The hold
  blocks the **sequence thread** — the event loop keeps turning, so heartbeats continue
  and Resume/Stop are read.
- Both flags are cleared when a run starts (`run_sequence()`), never when one ends.

## Key constants

| Name | Value | Meaning |
|------|-------|---------|
| `SEQUENCE_JOIN_TIMEOUT_S` | 2.0 s | How long `stop()` waits for the sequence thread |
| `HOLD_POLL_S` | 0.05 s | How often a held run looks at the pause and stop flags |

## Known gaps

- `WaitStep` does not honour `stop_requested` mid-sleep (step layer issue, not sequencer).
