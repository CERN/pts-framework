<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# sequencer — executes recipes

`sequencer.py` is the only file. Runs as a **thread of the Core process**.

## What it owns

- **Event loop** — `sequencer_main()` builds the Sequencer and calls `start()`;
  `main_loop()` polls `from_core` (`poll_core()`), dispatches (`handle_core_message()`) and
  sends heartbeats (`do_periodic_tasks()`, which also ends a pending stop once the sequence
  thread has finished - see *Stop*). Five methods carry `@catch_and_report_errors()`
  and no others:
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
  heartbeats keep flowing and `StopSequence` be processed mid-run. A `RunSequence` while a
  sequence thread is alive is refused with `report_problem()` ("Cannot start '…': a test is
  already running. Stop the running test first.").
- **`execute_sequence()`** — resolves the sequence, builds a `Runtime`, makes the run
  folder and starts the run log in it (`start_run_folder()`), emits `RunStarted` naming both,
  runs the steps (`run_body()` → `run_sequence_body()` from the step layer), logs the run
  summary, ends the run log, and only then emits `RunFinished`. That order is what puts every
  line of the run - its first to the summary - in the run log, and the run's last lines before
  the Report sees `RunFinished`. **Once `RunStarted` is out, `RunFinished` always follows**:
  the end - run log closed, then `RunFinished` - is in a `finally`, and the run is `ERROR`
  until `run_body()` and the summary have both returned. `run_body()` fills the caller's
  outcome list in place as soon as the steps are over - *before* the devices close - so an
  `Exception` or `SystemExit` escaping either (a run scope whose exit raised, a broken summary)
  is reported with `report_error()` and the run is sent as `ERROR` with the outcomes of the
  steps that ran;
  otherwise the frontends would show the run as going for ever and the Report would never
  finish the CSV. A refusal before `RunStarted` (no recipe, no such sequence) sends neither.
- **The run's streams** — after the run folder is made, `execute_sequence()` builds a
  `stream_handler.StreamSession(run_dir)` (`StreamSession(None)` when `run_dir == ""`: a retest,
  or a folder that could not be made - streams then register but record nothing) and runs the
  steps inside `with session:`. That block ends *before* `end_run_log()` and `RunFinished`, so
  the streams are closed and the process-wide slot cleared by then, on success and on failure
  (`close()` never raises); a thread of test code that kept a handle can no longer write into
  the next run (`stream_handler/stream_handler.md`). The session opens in `execute_sequence()`,
  not `run_body()`, so the `Runtime`'s emit seam can hold it. `make_metadata_watcher()` also
  gets `graph_by_step` (step id -> `graph:` name, from the `graph` of `sequence.to_summary()`
  rows): when a `StepFinished` arrives for such a step that ran (a SKIP outcome never ran, so it is
  not checked) and the session records streams but
  has no stream of that name, it logs WARNING `Step '<name>' shows graph '<graph>', but no
  stream of that name was registered.` - a typo in the recipe. A run with no folder cannot tell
  and does not warn (the session warns once, `no run folder`, on first registration).
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
- **The run's devices** — `run_body()` (called by `execute_sequence()`) runs the step layer inside
  `with pyhal.run_scope():` (`src/pyhal/pyhal.md` → *The client*, *Lifetime*): the devices are
  on the HAL server, which CORE connected to at startup (`core/core.md` → *The HAL link*). On
  entry every run - also one that uses no device - waits for CORE's startup connect if that is
  still running: normally seconds (a start with the window, about 6 s), at most
  `CONNECT_WAIT_S`; a Stop is not acted on during that wait, only once the run's steps begin.
  Test code opens a device on the HAL with its first `get_device()`; every
  device the run asked for is closed when the block ends — after the teardown steps, before
  `RunFinished`; a close that fails is a WARNING, never raised. With no HAL (the connect
  failed, bench.ini was discarded, `PYPTS_HAL=off`) `get_device()` raises the reason; a run
  that uses no device is not affected by that (only by the wait above). The Sequencer reads neither bench.ini nor the
  device sections.
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
- **Stop** (`StopSequencer`, the application closing) — `stop()` never waits. With no
  sequence running it calls `finish_stopping()` at once: `running = False` and
  `send_goodbye()`. With one running it logs INFO `Waiting for the running test to stop.`,
  sets `stop_requested` - exactly what the Stop button sets - and `stopping`, and returns. The
  run then ends the ordinary way, with **no deadline**: the step in progress finishes, the
  teardown steps run, the devices close at the `run_scope()` block end, `RunFinished` goes out.
  The event loop keeps turning meanwhile, so the heartbeat goes on; a question to the operator
  is not waited for once `stop_requested` is set (`ask_operator()`'s `should_abort`).
  `do_periodic_tasks()` sees `stopping` with the sequence thread gone and calls
  `finish_stopping()`. `SequencerStopped` is sent from the event loop after the sequence thread
  has ended, so it always arrives after that run's `RunFinished` on the same queue. `start()`
  has a `finally` that sends the goodbye for a loop that dies instead of ending;
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
- Both flags are cleared when a run starts (`run_sequence()`); `pause_requested` is also
  cleared by `drop_pending_pause()` after the main steps.

## Key constants

| Name | Value | Meaning |
|------|-------|---------|
| `HOLD_POLL_S` | 0.05 s | How often a held run looks at the pause and stop flags |

## Known gaps

- `WaitStep` does not honour `stop_requested` mid-sleep (step layer issue, not sequencer).
- A step that never returns holds the orderly close for good; there is no deadline on
  purpose. The way out is the crash close (CLI Ctrl+C, or the frontend ending, after which
  the launcher asks for it), which runs no teardown and leaves the devices as they are.
