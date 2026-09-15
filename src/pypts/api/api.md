<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# api — driving pypts from another Python program

`pypts.api` is the embedding door (migration finding M-2): the old `run_pts` /
`PtsApi` came back as a small, stable surface. Showcase of every case:
`api_showcase.py` at the repository root.

## Files

| File | Owns |
|------|------|
| `__init__.py` | The public names. Callers import from `pypts.api` only. |
| `embedding.py` | `Pts`, `open_gui()`, `ApiClient`, the result dataclasses, `PtsError` |
| `headless.py` | `--mode headless`: `headless_main()`, exit codes (below) |

## The two doors

```python
from pypts.api import Pts, open_gui

if __name__ == "__main__":
    with Pts() as pts:                          # Logger + CORE, no window
        pts.load_recipe("bench.yml")            # -> LoadedRecipe, or PtsError
        result = pts.run(answer=my_answers)     # -> RunResult when the run ends

    open_gui()                                  # the ordinary window
    open_gui("bench.yml")                       # ...with the recipe loaded
    open_gui("bench.yml", start=True)           # ...and its main sequence started
    open_gui("bench.yml", start=True, sequence="Cal")
```

| Call | Blocks until | Raises |
|------|--------------|--------|
| `Pts(log_level=None, debug_monitor=False)` | Logger and CORE are started | whatever `start_engine()` raises |
| `load_recipe(path)` | `RecipeLoaded`, or CORE's refusal | `PtsError` with CORE's reason; timeout 30 s |
| `run(sequence=None, answer=None, on_step=None)` | `RunFinished`, then `ReportReady` (15 s budget) | `PtsError` if the start is refused or the engine stops |
| `stop()` | — (sends `StopSequence`; thread-safe) | — |
| `close()` / `with` | the shutdown handshake, CORE, then the Logger | — |
| `open_gui(...)` | the window is closed | `ValueError` on bad arguments; `PtsError` for a missing file or no PySide6, before any process starts |

## How it is built

- **A third frontend.** `ApiClient(HmiClient)` is the GUI and the CLI's protocol half with no
  presentation. It adds nothing to the message catalogue.
- **The same engine as the launcher.** `startup.start_engine()` / `stop_engine()` /
  `run_gui()` were split out of `main()` so `Pts` and `open_gui()` start exactly what
  `python -m pypts` starts - one copy of the startup, not two.
- **Two threads, on purpose.** A background thread polls CORE and heartbeats, like the CLI's.
  Everything that waits - and the `answer` function - runs on the caller's thread, so a slow
  answer never stops the heartbeats and CORE never takes the frontend for dead.
- **Refusals are told apart from run errors by `operation`.** A `ModuleErrorReported` under
  `Core.load_recipe` refuses a load; under `Core.start_sequence` / `Sequencer.run_sequence` /
  `Sequencer.execute_sequence` *before* `RunStarted` it refuses a start. Any other error is a
  load warning (a version notice) or goes into `RunResult.errors`. A new refusal path in CORE
  or the Sequencer has to be added to `LOAD_REFUSAL` / `START_REFUSALS`.
- **Three kinds of question, one `answer` function.** It is called with a `UserPromptRequest`
  (return one of `options`), a `UserTextRequest` (return the text) or a `UserPathRequest`
  (return the path of an existing file or folder - `request.select` says which), and returns
  `None` to decline. `ApiClient` overrides `ask_user` / `ask_user_text` / `ask_user_path` as
  DEBUG no-ops so the poll thread does not decline on `HmiClient`'s behalf; `run()` answers on
  the caller's thread through `_answer`. The UserLoading step checks a returned path itself:
  one that does not exist, or is the wrong kind, is an ERROR.
- **A question is always answered.** No `answer` function declines, as the CLI does. An answer
  function that raises still sends a decline before the exception reaches the caller, so the
  step is not left waiting out its 300 s timeout.
- **Returns dataclasses, not messages.** `LoadedRecipe`, `RunResult`, `StepVerdict` are the
  contract; the message dataclasses stay internal and free to change. `ResultType`,
  `UserPromptRequest`, `UserTextRequest` and `UserPathRequest` are re-exported because the
  caller needs them.
- **`open_gui(start=True)`** passes the recipe and the start to `gui_main()`; the GUI opens it
  through `open_recipe()` and starts the sequence in `show_recipe_loaded()`. A refused recipe
  is never started, and any other open before `RecipeLoaded` cancels the pending start
  (`hmi/gui/gui.md`).

## Step values (M-3)

`StepVerdict.inputs`, `.outputs` and `.expectations` are `dict[str, str]` - the step's values
as text and each output's check (`range 11 .. 13`), copied from `StepOutcome`. Headless mode
prints them under each step line. The real, typed values are in the run's report.

## Headless mode (`headless.py`, M-2b)

`python -m pypts --mode headless --recipe x.yml [--sequence Name]` - the launcher hands over
to `headless_main()` (imported lazily: this package imports the launcher). It is `Pts` with a
console: load, run, print each step, exit.

- **`HeadlessPts(Pts)`** only sets `MODE = "headless"`, so the run log says HEADLESS, not API.
- **Every question is declined** (`decline_question()`: a console line and a WARNING), so the
  step is an ERROR - as in the CLI. No answers file, by decision.
- **Exit codes:** `0` PASS/DONE · `1` FAIL · `2` ERROR, STOP or SKIP (not judged; also
  Ctrl+C) · `3` no run - missing or refused recipe, unknown sequence, engine failed to start
  or stopped mid-run. A rejected command line is `3` too (`startup.USAGE_EXIT_CODE`, not
  argparse's `2`), in every mode.
- The recipe file and the sequence name are checked before running; a missing file before
  anything is started.
- The Debug Monitor is **off** by default in this mode (`--debug-monitor` turns it on).
- Tests: `tests/unit_tests/test_headless.py`; a real-process run is in
  `test_api_processes.py` (opt-in).

## Rules and caveats

- **Spawn.** Callers must create `Pts` / call `open_gui()` under `if __name__ == "__main__":`.
- **Logging.** `start_engine()` calls `init_logging()` in the caller's process, which replaces
  the root logger's handlers. `close()` and `open_gui()` put back the handlers and level they
  found.
- **Importing `pypts.api` must not import Qt** - `open_gui()` imports the GUI only when called.
  Pinned by `test_importing_the_api_does_not_import_qt`.
- **Tests.** `tests/unit_tests/test_api.py` drives `ApiClient` against a fake CORE thread.
  `tests/functional_tests/test_api_processes.py` starts the real processes and is opt-in
  (`PYPTS_PROCESS_TESTS=1`): there is no override for the per-user config, log and report
  folders, and a spawned child cannot be monkeypatched.

## Not here (on purpose)

- The Phase 2 plugin contract (step and driver base classes) - a different door, *extending*
  pypts rather than driving it. It may share the `pypts.api` package later.
