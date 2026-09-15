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

Current branch: `architecture_refactor`.

- `src/pypts/old_code/` — **the old, working implementation. Do not modify it. Do not
  delete it.** Read it to understand old behaviour when porting or debugging. It is the
  reference for anything not yet ported.
- `src/pypts/<module>/` — the new architecture. The process model, messaging, heartbeats,
  config, logging, recipe parsing, step layer, and report are all implemented and working.
  Remaining stubs: `hardware_layer/hal.py`, `stream_handler/`.
- Goal: **same functionality as the old code, and beyond**, in the new architecture.

## Where the plan and the implementation status live

**`pypts_implementation_status.html` (repo root) is the single source of truth for what is
implemented, what is still a stub, and what comes next.** It is a *living* document.
**Read it before planning or starting any work.**

Also at repo root: `recipe_guide.html` — the new-format recipe reference (step
types, input/output mapping, verificator gaps). `usage_manual.html` — the short user manual:
modes (GUI, CLI, API, headless), options, where files go.

**Everything that affects how a user uses the application goes into `usage_manual.html`**,
in the same change: a new or changed mode, command-line option, CLI command, GUI button or
menu, prompt behaviour, exit code, file location, setting, or helper tool. A change that alters
what a user sees, types or gets back is not done until the manual says so. Keep it short and
simple — what to do and what happens, not how it is built (that belongs in the context files).

Keeping the roadmap current is part of every task:

- New work items go in as **TODOs there** — not scattered in code comments.
- When something is implemented, update its status in the same change.
- If reality and the roadmap disagree, say so and ask.

## Module context files

Every module carries a `<module>.md` beside its code with the full context: what each file
owns, the rules and decisions behind them, how to extend it, known gaps.
**Read it before touching that module.**

| Module | Context file |
|--------|-------------|
| `config_handler/` | `config_handler/config_handler.md` |
| `messages/` | `messages/messages.md` |
| `hmi/gui/` | `hmi/gui/gui.md` |
| `step/` | `step/step.md` |
| `logger/` | `logger/logging_rules.md` |
| `recipe/` | `recipe/recipe.md` |
| `sequencer/` | `sequencer/sequencer.md` |
| `report/` | `report/report.md` |
| `core/` | `core/core.md` |
| `utilities/` | `utilities/utilities.md` |
| `launcher/` | `launcher/launcher.md` |
| `hmi/` | `hmi/hmi.md` |
| `hardware_layer/` | `hardware_layer/hal.md` |
| `stream_handler/` | `stream_handler/stream_handler.md` |
| `api/` | `api/api.md` |
| `helper_applications/recipe_verificator/` | `recipe_verificator/recipe_verificator.md` |

The roadmap stays authority on *status and plan*; context files say *how it works*.
Update the context file in the same change that touches the module.

## Where generated HTML documents go

**Ephemeral generated HTML documents go in `resources/internal_reports/`.** Not the repo
root, not next to the code they describe — the user opens these in a browser and expects every
one of them in one folder. **Permanent project-reference HTML documents** (
`pypts_implementation_status.html`, `recipe_guide.html`, `migration_instructions.html`,
`usage_manual.html`)
live at the **repo root** alongside `TODO.txt`.

- One self-contained file: inline CSS, no external assets, light *and* dark palettes.
- A file in `resources/**` needs its own inline SPDX header (`CC-BY-SA-4.0`). A file at repo
  root also needs one.
- **Open a *newly created* document in the browser** as the last step — do not offer, do not
  ask, just open it: `Invoke-Item <path>` from PowerShell. Say where you put it in the same breath.
- **Do not open a document you only edited.** Say what changed and where; the user opens it
  when they want it.
- List the folder to see what already exists rather than assuming.

## Layout

```
src/pypts/
  launcher/startup.py    entry point; pins spawn, parses args, creates queues, spawns
                         Logger + CORE + frontend (context: launcher/launcher.md)
  core/core.py           mediator: routes every link, manages Sequencer + Report threads,
                         heartbeat watch, shutdown choreography (context: core/core.md)
  sequencer/             event loop + execute_sequence(); sequences run on a worker thread
                         (context: sequencer/sequencer.md)
  recipe/                recipe data layer: Recipe, Sequence, rules, parser, validator
                         (context: recipe/recipe.md)
  step/                  step types and runtime: PythonModule, UserInteraction, Wait,
                         UserWrite; Runtime seams; run_sequence() (context: step/step.md)
  report/                incremental CSV + HTML, one folder per run (context: report/report.md)
  hmi/hmi_client.py      protocol half shared by all frontends (context: hmi/hmi.md)
  hmi/cli/  hmi/gui/     CLI shell and PySide6 GUI
  api/                   pypts.api: Pts (headless engine driven by code) and open_gui()
                         (context: api/api.md; showcase: api_showcase.py at repo root)
  messages/              all typed message dataclasses, one module per link
                         (context: messages/messages.md)
  config_handler/        per-user config.ini (context: config_handler/config_handler.md)
  logger/log.py          Logger process: single run-log writer (context: logger/logging_rules.md)
  utilities/             error_handling, heartbeat_manager, local_storage, common
                         (context: utilities/utilities.md)
  hardware_layer/hal.py  HAL stub — Phase 3+ (context: hardware_layer/hal.md)
  stream_handler/        empty placeholder — Phase 3+ (context: stream_handler/stream_handler.md)
  helper_applications/   debug_monitor, recipe_creator, recipe_verificator, example_finder
  old_code/              frozen legacy implementation — read only, never modify
resources/internal_reports/  generated HTML documents (dev artifacts)
resources/roadmap/       (roadmap content now in repo-root HTML files)
resources/recipes/       example recipes (YAML, *.yml)
tests/                   unit_tests/ + functional_tests/
pypts_implementation_status.html  phased plan + implementation status (at repo root)
recipe_guide.html        new-format recipe reference (at repo root)
usage_manual.html        short user manual: modes, options, files (at repo root)
migration_instructions.html  porting guide for old recipes (at repo root)
TODO.txt                 open task list (at repo root)
plans/                   refactoring_progress.md (completed work log) + README.md
```

## Communication model

Modules never touch queues directly and never call each other. Everything goes through
CORE — except log records, which go straight to the Logger.

**Two processes.** CORE (with Sequencer + Report as threads) and the HMI frontend, plus the
Logger. Only the HMI↔CORE link crosses a process boundary (pickled). The four engine links
are plain `queue.Queue`. A thread entry point must never call `init_logging()`.

Every message is a plain **dataclass** of plain values. Each link gets a module
`<a>_<b>_communication.py` with both directions and a union type per direction.
One generic `QueueWrapper` is the transport for all of them. Catalogue: `messages/messages.md`.

Every `QueueWrapper` traces itself: `send()` and `receive()` each log one DEBUG line, so
`--log-level DEBUG` puts every message in the system into the run log twice.

Every handler is a `match` closed with `unhandled()`, so a forgotten message raises instead
of being silently dropped. To add a message: (1) declare the dataclass and add it to the
union, (2) add a `case` in the recipient's handler. `mypy` flags incomplete matches;
`test_messages.py` drives every union member through the real handler.

Anything crossing the HMI↔CORE boundary must stay **pickle-safe** — no live queues, no Qt
objects, no device handles.

A sequence runs on its own worker thread (started by `run_sequence()`, executed by
`execute_sequence()`). The event loop must keep turning while it does.

Two error decorators — pick the right one:
- `@catch_and_report_errors()` — reports and **continues** (event loops)
- `@report_and_reraise()` — reports and **re-raises** (step execution layer)

For recognised failures use `report_error(self, exc, severity=…)` (live exception) or
`report_problem(self, message, severity=…)` (refused command, no exception). Neither raises.
See `utilities/utilities.md` and `pypts_implementation_status.html` §1.10–§1.11.

## Running

```bash
python -m pypts                       # GUI mode (PySide6) - the default
python -m pypts --mode cli            # CLI mode
python -m pypts --mode headless --recipe x.yml [--sequence Name]
                                      # one unattended run; exit 0 PASS/DONE, 1 FAIL,
                                      # 2 ERROR/STOP/SKIP, 3 no run (api/api.md)
python -m pypts --log-level DEBUG     # full message trace in the run log
python -m pypts --no-debug-monitor    # without the Debug Monitor
pytest tests                          # unit + functional tests
python run_tests.py                   # same, via wrapper

python -m pypts.helper_applications.debug_monitor   # Monitor alone, on the newest log

run_pypts.bat [args]                  # Windows double-click / shell: run_pypts.py via .venv
run_recipe_creator.bat                # the Recipe Creator, the same way
python run_pypts.py [args]            # = python -m pypts, with src on the path
python run_recipe_creator.py          # = python -m pypts.helper_applications.recipe_creator
```

The Debug Monitor is **on by default during the refactor** (`--no-debug-monitor` turns it
off). It only has something to show at DEBUG. Nothing in the framework may import
`helper_applications/debug_monitor/`. See `pypts_implementation_status.html` §1.4.1 for the
revert TODO.

Config file: `%LOCALAPPDATA%\pypts\config.ini` (Windows) / `~/.config/pypts/config.ini`
(Linux). Ships as DEBUG level during the refactor (see §1.6 for revert TODO).
A broken or version-mismatched file is discarded and the run continues on template defaults.

**Config structure version** (`CONFIG_VERSION` in `config_handler/configuration_schema.py`,
mirrored in `config_template.ini`) is a `MAJOR.MINOR.PATCH` string, currently `1.0.0`; only
the major number must match for a file to be trusted. **Do not change it automatically** when
editing the schema — only when a change adds something new that is mandatory. If unsure
whether a change qualifies, ask.

## Quality gates

All three must pass before any change is called done:

```bash
pytest tests                 # 408 passed, 43 skipped as of exec/005-spawn
ruff check src tests         # rules and line-length 100 in [tool.ruff] in pyproject.toml
mypy                         # scope is [tool.mypy]: messages/ and the handler modules
```

The `# noqa:` codes name rules that config actually enables — do not add a `noqa` for a
rule that is off, and do not silence a rule without saying why in the same line.

## Code style

**Old-school, plain, readable Python. Shortest is not clearest.** Prefer an `if`/`else` over
a conditional expression, a named local over a clever one-liner. `SIM108` and `N818` are
disabled in ruff for exactly this reason.

- **Logging is `%`-style**, never f-strings: `log.info("Starting %s", name)`. `G004` enforces it.
- **`logger/logging_rules.md` is the authority** on what a log line says and at which level.
  In one sentence: **INFO and above are written for the technician**; **everything
  developer-facing is DEBUG**.
- **Lifecycle log wording is fixed**: `<NAME> module starting.` (DEBUG) /
  `<NAME> module started.` (INFO) / `<NAME> entered its main event loop.` (DEBUG) /
  `<NAME> left its main event loop.` (DEBUG) / `<NAME> module stopping.` (DEBUG) /
  `<NAME> module stopped.` (INFO). `<NAME>` is one of `LAUNCHER LOGGER CORE SEQUENCER REPORT GUI CLI`.
- **Load-bearing constructs — do not simplify away**: `match`/`case` closed with
  `unhandled()`, link union types, `Never`/`NoReturn`, `QueueWrapper[Msg]`. These make a
  forgotten message an error instead of silence. Changing them is a design conversation.

## Working style

- **`TODO.txt` in the repo root is the user's task inbox for Claude** — check it when asked
  to work through tasks; mark items `[x]` with a note rather than deleting them.
- The user orchestrates specific tasks; do that task, not the surrounding ones.
- Prefer small, reviewable changes aligned with the roadmap phase in progress.
- Match existing conventions rather than introducing new patterns unasked.
- **Never `git checkout` a file to undo an experiment** — it reverts to HEAD and takes any
  uncommitted work in that file with it.
