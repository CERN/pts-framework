# CLAUDE.md

## Prime rule — certainty before action

**Never proceed unless you are ~95% certain.** If you are less certain than that about
anything — the intent of a request, which module owns a behaviour, what the old code
actually did, which of two designs is wanted, whether a file may be touched — **stop and
ask.** Asking a question is always cheaper than an incorrect implementation.

Practical form of the rule:

- Read the relevant code (including `old_code/`) before proposing or writing anything.
- Never guess an API, a message name, a field, or a behaviour — verify it in the source.
- If a task is underspecified, list the concrete options and ask which one to take.
- Do not silently widen scope. One task at a time, as orchestrated by the user.
- State assumptions explicitly when you do make them.
- Report honestly: if something is untested, unfinished, or skipped, say so.

## What this project is

**PyPTS / `pts-framework`** — a CERN Python test-automation framework. It runs YAML
"recipes" (sequences of steps) against hardware, and produces reports. Import name is
`pypts`; distribution name is `pts-framework`. Python ≥ 3.11, LGPL-2.1-or-later, REUSE
compliant.

`reuse.toml` is the authority on licensing headers — do not apply a stricter rule than it
does. It blanket-covers `src/pypts/**/*.py`, `tests/**/*.py` and `spikes/**/*.py`, so a new
file there needs **no inline SPDX header**. A file outside those globs does; `resources/**`
is the common case. Most Python files carry one anyway — harmless, but a habit, not a rule.

We are **refactoring an existing working framework into a new architecture**. Current
branch: `architecture_refactor`.

- `src/pypts/old_code/` — **the old, working implementation. Do not modify it. Do not
  delete it.** Read it freely to learn what the software actually does. It is the source
  of truth for behaviour and the reference for every port.
- `src/pypts/<module>/` — the new structure. Mostly **stubs plus a working skeleton**:
  the process model, typed messaging, heartbeats, logging and config work; the execution
  engine does not exist yet.
- Goal: **same functionality as the old code, and beyond**, in the new architecture.

## Where the plan and the implementation status live

**`resources/roadmap/pypts_roadmap.md` is the single source of truth for what is
implemented, what is still a stub, and what comes next.** It is a *living* document — we
track the refactor in it. **Read it before planning or starting any work.**

It holds the state of the branch (done / placeholder / known defects), the numbered record of
each completed rework (§1.1–§1.10), the phased plan (Phase 0 stabilize → Phase 1 port the
engine → … → v1.0.0), the plugin/`pypts.api` proposal, and the open questions.

Keeping it current is part of every task:

- New work items and follow-ups go in as **TODOs there** — not scattered in code comments,
  not in a separate plan file.
- When something is implemented, update its status in the same change that implements it.
- If reality and the roadmap disagree, say so and ask — do not silently work around it.

Also in that folder: `recipe_guide.md` — what a recipe is and what the old engine does with
it, the reference for the Phase 1 port.

## Module context files

A module may carry a `<module>.md` beside its code holding the whole context of that folder:
what each file owns, the rules and decisions behind them, how to extend it, its known gaps.
**Read it before touching that module** — it knows more about it than this file or the
roadmap does. Present: `config_handler/config_handler.md`, `messages/messages.md`.

It explains *how the module works*; the roadmap stays the authority on *status and plan*, and
wins where they overlap. Update it in the same change, the way the roadmap is updated.

## Where generated HTML documents go

**Every HTML report, summary or overview the user asks for is saved in
`resources/internal_reports/`.** Not the repo root, not next to the code it describes, not a
scratch directory, not loose in `resources/` — the user opens these in a browser and expects
every one of them in one folder. This holds for *all* HTML documents in the project.

- One self-contained file: inline CSS, no external assets, light *and* dark palettes. It has
  to open from disk with no network.
- `resources/**` is **not** covered by `reuse.toml`, so such a file needs its own inline SPDX
  header — `CC-BY-SA-4.0` for documentation, matching the two below.
- **Always open it in the browser** as the last step of writing or updating it — do not offer,
  do not ask, just open it: `Invoke-Item <path>` from PowerShell. The user reads these in a
  browser, so a report that has been written but not opened is not finished. This applies to a
  *re*-generated document as well as a new one. Say where you put it in the same breath.
- List the folder to see what already exists rather than assuming; `messaging_overview.html`
  (the communication model) and `recipe_rules.html` (the recipe rules) are the two worth
  reading before writing about either subject.

## Layout

```
src/pypts/
  launcher/startup.py    entry point; --mode gui|cli|connect, --log-level and
                         --debug-monitor; creates the queues, builds the HMI<->CORE links,
                         spawns Logger + CORE + frontend
  messages/              the whole communication contract - one module per link (see below,
                         and messages.md for the catalogue)
  core/core.py           mediator: routes every link, runs Sequencer + Report as threads,
                         heartbeat watch
  sequencer/             thread of CORE; event loop is real and a sequence runs on a worker
                         thread of its own, so the loop keeps turning; execute_sequence() is
                         still a stub
  recipe/  step/         recipe data layer + step types (empty; to be ported from old_code)
  report/                event loop is real; CSV/HTML logic is a stub (see old_code/report.py)
  hmi/hmi_client.py      the protocol half every frontend shares
  hmi/cli/  hmi/gui/     CLI shell and PySide6 GUI
  hardware_layer/hal.py  HAL (empty stub)
  stream_handler/        empty placeholder package; the StreamContainer spike now lives in
                         spikes/stream_handler/ until Phase 3 promotes it
  config_handler/        ConfigHandler singleton; INI template -> config.ini in the
                         per-user config dir, versioned, migrated, typed via
                         configuration_schema.py (context: config_handler.md)
  logger/log.py          the Logger process: single writer of the run log, plus init_logging()
  utilities/             error_handling, heartbeat_manager, local_storage, common
  helper_applications/   recipe_creator, recipe_verificator, example_finder (not yet refactored)
  old_code/              the frozen legacy implementation - read only, never modify
resources/internal_reports/  every generated HTML document (see the rule above)
resources/roadmap/       the plan, plus the recipe guide
resources/recipes/       example recipes (YAML, *.yml)
tests/                   unit_tests/ + functional_tests/
```

## Communication model (important)

Modules never touch queues directly and never call each other. Everything goes through
CORE — except log records, which go straight to the Logger.

**Two processes.** The engine (CORE) and the operator's frontend, plus the Logger. The
Sequencer and the Report are **threads of the Core process**, started by
`Core.start_submodules()`. Only the HMI ↔ CORE link crosses a process boundary, so only its
messages are pickled; the four engine links are plain `queue.Queue`. A thread entry point
must never call `init_logging()` — the root logger belongs to the process.

Every message is a **frozen slotted dataclass** of plain values. Each *link* gets a module
`<a>_<b>_communication.py` holding both directions and a union type per direction; the Logger's
is `to_logger_communication.py`, named for its one direction because nothing is sent back.
`common_messages.py` and `run_events.py` hold what more than one link shares, `links.py` the
name of each direction. One generic `QueueWrapper` in `queue_wrapper.py` is the transport for
all of them — it wraps anything with `put()` and `get_nowait()`, which is what lets one class
serve a process boundary and a thread boundary. Catalogue: `messages/messages.md`.

Every `QueueWrapper` traces itself: `send()` and `receive()` each log one DEBUG line naming
the link and the message, so `--log-level DEBUG` puts every message in the system into the
run log twice — once from the sender, once from the receiver. That is why a wrapper carries a
`link` name, and it is the only way to see Core↔Sequencer and Core↔Report, which never leave
the engine process. It is also the only thing that identifies those two modules in the log at
all: the format names the *process*, so their records read `Core`. There is no debug build;
there is nothing else to turn on.

Every handler is a `match` closed with `unhandled()`, so a message nobody thought about
raises instead of being silently dropped.

To add a message, follow the 2 steps in `src/pypts/README.md`:
1. declare the dataclass in the link module and add it to that link's union,
2. handle it with a `case` in the recipient's handler.

Everything else is found for you: `mypy` flags every `match` that is now incomplete, and
`tests/unit_tests/test_messages.py` drives every member of every union through the real
handler and fails until the message has an example and a branch.

Anything crossing the HMI↔Core boundary must stay **pickle-safe** — no live queues, no Qt
objects, no device handles.

**A sequence runs on its own worker thread**, started by `run_sequence()` and left to
`execute_sequence()`. The event loop must keep turning while it does, or heartbeats stop,
`StopSequence` is never read and a step waiting in `PendingRequests.wait()` deadlocks. See
roadmap §1.8 — the tests in `test_sequencer.py` exist to keep that shape.

Two error decorators in `utilities/error_handling.py`, and picking the wrong one matters:
`@catch_and_report_errors()` reports and **continues** (event loops — a module that dies on
one bad message takes the run with it); `@report_and_reraise()` reports and **re-raises**
(execution layer — a step failure has to reach a `StepResult`). See roadmap §1.10.

The decorators are the net for a failure **nobody expected**, so all they can call it is an
ERROR. A failure a method **recognises** is handled where it happens — an ordinary
`except SpecificError:` — and reported with `report_error(self, exc, severity=…)` (a live
exception) or `report_problem(self, message, severity=…)` (a refusal, nothing raised). Neither
raises: the raise site keeps control of what it does next. Every `ModuleError` names the module,
the method (`operation`) and the exception type; CORE logs at the level the severity asks for and
shows the operator anything above WARNING, and that is *all* CORE does about an error today. See
roadmap §1.11.

## Running

```bash
python -m pypts                       # GUI mode (PySide6) - the default
python -m pypts --mode cli            # CLI mode
python -m pypts --log-level DEBUG     # adds the full message trace to the run log
python -m pypts --debug-monitor       # opens the Debug Monitor on this run's log too
python run_tests.py                   # unit tests, then functional tests
pytest tests                          # the same suite, directly

python -m pypts.helper_applications.debug_monitor   # the Monitor alone, on the newest log
```

`--debug-monitor` is off unless asked for. The launcher starts the Monitor with
`subprocess.Popen`, never as an import, so the framework does not depend on it and it cannot
stop a run; it is handed this run's log path, and left open when the run ends. It only has
something to show at DEBUG. **Nothing in the framework may import
`helper_applications/debug_monitor/`** — the dependency runs one way only. See roadmap §1.4.1.

`--log-level` overrides `[logging] level` in the generated `config.ini`, which **ships as
`DEBUG` for the duration of the refactor** so every run carries the message trace and the
Debug Monitor always has something to read. It reverts to `INFO` before v1.0 — see roadmap
§1.6 and its revert TODO. The file lives in the per-user config directory (`%LOCALAPPDATA%\pypts\config.ini`
on Windows, `~/.config/pypts/config.ini` on Linux); the launcher creates it from the
template on first run and migrates it when its structure version is older than the code's.
A leftover `%TEMP%/pypts/config/config.ini` from an older build is no longer read at all.

`--mode connect` is accepted by argparse but **has no branch**, so it silently falls
through and starts the CLI. It is not implemented.

## Quality gates

All three must pass before any change is called done, and all three run in CI
(`.gitlab-ci.yml`, `analyse` and `test` stages):

```bash
pytest tests                 # 248 passed, 69 skipped as of the last green run
ruff check src tests         # rules and line-length 100 in [tool.ruff] in pyproject.toml
mypy                         # scope is [tool.mypy]: messages/ and the handler modules
```

The `# noqa:` codes in the source name rules that config actually enables — do not add a
`noqa` for a rule that is off, and do not silence a rule without saying why in the same line.

## Code style

**Old-school, plain, readable Python. Shortest is not clearest.** Prefer an `if`/`else` over
a conditional expression, a named local over a clever one-liner, a loop over stacked
comprehensions. `SIM108` and `N818` are disabled in ruff for exactly this reason.

- **Logging is `%`-style**, never f-strings: `log.info("Starting %s", name)`. Lazy formatting
  is why the DEBUG trace costs nothing when the level is higher. `G004` enforces it.
- **Lifecycle log wording is fixed**: `Starting module.` / `Starting main event loop.` /
  `Left main event loop.` / `Stopping module.` / `Module stopped.`
- **Some "modern" constructs are load-bearing and must not be simplified away**: the
  `match`/`case` handlers closed with `unhandled()`, the frozen slotted dataclasses, the link
  union types, `Never`/`NoReturn`, and `QueueWrapper[Msg]`. They are what makes a forgotten
  message an error instead of silence. Changing them is a design conversation, not a cleanup.

## Working style

- The user orchestrates specific tasks; do that task, not the surrounding ones.
- Prefer small, reviewable changes aligned with the roadmap phase in progress.
- Match existing conventions (frozen message dataclasses, link modules, `unhandled()`-closed
  handlers, module layout) rather than introducing new patterns unasked. For SPDX headers,
  follow `reuse.toml` — see above.
- **Never `git checkout` a file to undo an experiment** — it reverts to HEAD and takes any
  uncommitted work in that file with it. Restore what you changed, or commit first.
