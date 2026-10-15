<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# sequencer — executes recipes

`sequencer.py` is the only file. Runs as a **thread of the Core process**.

## What it owns

- **Event loop** — `sequencer_main()` polls `from_core`, dispatches to handlers,
  sends heartbeats. Four methods carry `@catch_and_report_errors()` and no others:
  `poll_core()`, `handle_core_message()` (one bad message fails alone), `do_periodic_tasks()`
  and the two thread entry points `start()` and `execute_sequence()`. The handlers below them
  — `run_sequence()`, `forget_recipe()`, `stop_sequence()`, `pause_sequence()`,
  `resume_sequence()`, `stop()` —
  are deliberately **undecorated**: their failures unwind to the per-message boundary instead
  of being swallowed a frame deeper, where the caller would carry on as if the call had
  worked. `start()` rather than `main_loop()` because the `while` is inside main_loop. The
  rule, and why, is in `utilities/utilities.md`.
- **Recipe execution** — `run_sequence()` starts a worker thread for `execute_sequence()`.
  The event loop keeps turning while the sequence thread runs; this is what lets
  heartbeats keep flowing and `StopSequence` be processed mid-run.
- **`execute_sequence()`** — resolves the sequence, builds a `Runtime`, makes the run
  folder and starts the run log in it (`start_run_folder()`), emits `RunStarted` naming both,
  runs the steps (`run_body()` → `run_sequence_body()` from the step layer), logs the run
  summary, ends the run log, and only then emits `RunFinished`. That order is what puts every
  line of the run - its first to the summary - in the run log, and the run's last lines before
  the Report sees `RunFinished`. **Once `RunStarted` is out, `RunFinished` always follows**:
  the end - run log closed, then `RunFinished` - is in a `finally`, and the run is `ERROR`
  until `run_body()` and the summary have both returned. An `Exception` or `SystemExit`
  escaping either (devices that would not close, a broken summary) is reported with
  `report_error()` and the run is sent as `ERROR`, with whatever step outcomes it already had;
  otherwise the frontends would show the run as going for ever and the Report would never
  finish the CSV. A refusal before `RunStarted` (no recipe, no such sequence) sends neither, and
  an abandoned run (see *Stop*) sends no `RunFinished`: nobody is listening any more.
- **Engineering mode** — `RunSequence.excluded_step_ids` and `.write_report` reach
  `execute_sequence()` through `run_sequence()` (as thread arguments). The exclusions go on the
  `Runtime` (`excluded_step_ids`, `step/step.md` §3); the step layer records each SKIP.
  `write_report=False` (the GUI's Space retest) skips `start_run_folder()`: no run folder, no
  run log, `RunStarted(run_dir="", run_log_path="", write_report=False)` — the run is logged
  in the session log, and CORE keeps it away from the Report on the strength of that
  `RunStarted`. `log_engineering_run()` writes the technician's lines before `RunStarted`:
  INFO `Engineering run: N of M steps left out.` (M counts the sequence's table rows, called
  sequences' steps and teardown included) when anything is left out, and INFO
  `Engineering run: no report and no run folder for this run.` when `write_report` is False.
  An ordinary run writes neither.
- **The run folder and run log** — `start_run_folder()` calls
  `utilities.local_storage.make_run_folder(self.reports_dir(), recipe name)`; a folder that
  cannot be made is a WARNING `ModuleError` ("The results folder could not be created: …")
  and the run goes on with `run_dir=""`. The run log is `get_log_file_path(run folder)`,
  started with `log.start_run_log()`; its first line is `Run log of recipe '…', sequence '…'.`
  With no Logger process (unit tests) there is no run log and `run_log_path` is `""`. After
  the run the session log gets `The run's log is <path>`. `reports_dir` defaults to
  `reports_dir_from_config()` (`paths.reports_dir`); tests replace it.
  `RunFinished.outcomes` and the run summary lines count **real steps** at every depth
  (`real_step_results()`): the row of a called sequence is not counted, the steps inside it
  are (`step/step.md` §2.8). Also watches `report_metadata` globals and forwards `RunMetadata` updates to CORE.
- **The run's devices** — `execute_sequence()` runs the step layer inside
  `with LocalSetup(self.read_hardware_sections):` (`hal/hal.md` → *Lifetime*). Test code opens a
  device on first `get_device()`; every device closes when the block ends — after the teardown
  steps, before `RunFinished`. `read_hardware_sections` defaults to
  `hal.local_setup.hardware_sections_from_config` and is only called on the first `get_device()`, so a
  run that uses no device never reads the device sections; tests replace it.
- **Forgetting the recipe** — `self.recipe` is written only by `RunSequence` and keeps the
  last run's recipe afterwards. `ForgetRecipe` (CORE sends it when the operator unloads the
  recipe) runs `forget_recipe()`: `self.recipe = None`, and `forget_loaded_modules()` from
  `step/python_module_step.py` drops the cached test modules, so an edited test file is read
  afresh next time. Refused with `report_problem()` (ERROR, "Cannot unload the recipe: a test
  is running…") while a sequence thread is alive — that thread is the module cache's only,
  lockless, reader.
- **Operator interaction** — `ask_operator()` puts a `UserPromptRequest`,
  `UserTextRequest` or `UserPathRequest` on the CORE link and blocks in `PendingRequests.wait()` until the
  response arrives. The event loop must keep turning; `ask_operator` runs on the sequence
  thread, not the event loop thread.
- **Stop** — `stop_running_sequence()` sets `stop_requested` and joins the sequence thread
  up to `SEQUENCE_JOIN_TIMEOUT_S` (2 s). If the thread is still alive after that, the run is
  **abandoned**: `run_abandoned` is set, so the run's events (the `emit` seam), its questions
  (`ask_operator()` answers `None` at once) and its `RunFinished` are no longer sent - CORE is
  shutting down without it, so the `RunStarted`/`RunFinished` pairing does not hold for an
  abandoned run. It reports `CRITICAL` via `report_problem()`, then
  `tear_down_abandoned_devices()` calls `hal.abandon_active_setup()` with
  `ABANDONED_DEVICES_TIMEOUT_S`: the run's devices are torn down side by side, and any that
  were not is a second `CRITICAL` naming them ("may still be energised"; `hal/hal.md`,
  *Lifetime*). Then the shutdown continues. `SequencerStopped`
  is sent after the join, so it always arrives after any `RunFinished` on the same queue.
  The send sits in a `finally` and goes through `send_goodbye()`, because it comes *after* the
  line that can fail: an exception on its way out to the per-message boundary would otherwise
  skip it, and CORE would keep the module marked as running, hold `StopReport` until the
  shutdown deadline, and name the Sequencer as a module that never stopped. The failure still
  reaches CORE as a `ModuleError`, just behind the `SequencerStopped` rather than instead of
  it. `start()` has the same `finally` for the loop that dies instead of ending;
  `send_goodbye()` is guarded so only one `SequencerStopped` ever goes out.
- **Pause / Resume** (GUI only) — `PauseSequence` sets `pause_requested` (ignored with no
  sequence running); `ResumeSequence` clears it. The step layer calls the Runtime seam
  `hold_if_paused(step_name, position, total)` before every main step - including a step
  inside a called sequence, where `position`/`total` count within that sequence, but never
  before the row of the call itself; `Sequencer.hold_if_paused()`
  returns at once unless a pause is pending, otherwise sends `RunPaused`, polls every
  `HOLD_POLL_S` until Resume or Stop, then sends `RunResumed` (whichever ended it). So the
  running step always finishes first, and a Stop during a hold ends the hold and then skips
  the remaining steps as usual. `drop_pending_pause()` runs once after the run's main steps
  (the first sequence's, never a called sequence's) and before teardown: a pause that found no step to hold before lapses there, with the INFO
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
| `ABANDONED_DEVICES_TIMEOUT_S` | `RESCUE_TIMEOUT_S` + 1 = 11.0 s | How long `stop()` gives an abandoned run's devices, torn down side by side |
| `HOLD_POLL_S` | 0.05 s | How often a held run looks at the pause and stop flags |

## Known gaps

- `WaitStep` does not honour `stop_requested` mid-sleep (step layer issue, not sequencer).
- An abandoned run's thread is not stopped, only cut off: its test code runs on until it ends or
  CORE's process exits. Its teardown *steps* do not run; only the devices are torn down.
