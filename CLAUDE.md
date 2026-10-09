# CLAUDE.md

## Prime rule — certainty before action

**Never proceed unless you are ~95% certain.** If you are less certain about anything — the
intent of a request, which module owns a behaviour, which of two designs is wanted, whether a
file may be touched — **stop and ask.** Asking is always cheaper than a wrong implementation.

- Read the relevant code and its context file before proposing or writing anything.
- Never guess an API, a message name, a field, or a behaviour — verify it in the source.
- If a task is underspecified, list the concrete options and ask which one to take.
- Do not silently widen scope. One task at a time, as orchestrated by the user.
- State assumptions explicitly. Report honestly: untested, unfinished or skipped — say so.

## What this project is

**PyPTS / `pts-framework`** — a CERN Python test-automation framework. It runs YAML "recipes"
(sequences of steps) against hardware and produces CSV + HTML reports. Import name `pypts`,
distribution `pts-framework`, Python ≥ 3.11, LGPL-2.1-or-later, REUSE compliant.

`reuse.toml` is the authority on licence headers. It covers `src/pypts/**/*.py`,
`tests/**/*.py`, `spikes/**/*.py` and `docs/**/*.rst`, so new files there need no inline SPDX
header. Anything outside its globs does — typically `resources/**` and repo-root HTML
(`CC-BY-SA-4.0`).

Still a stub: `stream_handler/` (empty).

## Where things are documented

| Document | Owns |
|---|---|
| `pypts_implementation_status.html` (root) | **Status, plan, TODOs** — single source of truth. Read before planning. |
| `usage_manual.html` (root) | Everything a user sees, types or gets back: modes, options, exit codes, GUI, files, helper tools. |
| `recipe_guide.html` (root) | The recipe format: step types, inputs/outputs, verificator gaps. |
| `src/pypts/<module>/<module>.md` | How a module works: files, rules, decisions, how to extend, known gaps. |
| `docs/source/*.rst` | Thin Sphinx shell pointing at the above. Holds no detail of its own. |
| `TODO.txt` (root) | The user's task inbox for Claude. Mark items `[x]` with a note; never delete. |

Module context files — **read before touching the module**:

| Module | Context file |
|---|---|
| `api/` | `api/api.md` |
| `config_handler/` | `config_handler/config_handler.md` |
| `core/` | `core/core.md` |
| `hal/` | `hal/hal.md` |
| `hmi/` (shared client, CLI) | `hmi/hmi.md` |
| `hmi/gui/` | `hmi/gui/gui.md` |
| `launcher/` | `launcher/launcher.md` |
| `logger/` | `logger/logging_rules.md` |
| `messages/` | `messages/messages.md` |
| `recipe/` | `recipe/recipe.md` |
| `report/` | `report/report.md` |
| `sequencer/` | `sequencer/sequencer.md` |
| `step/` | `step/step.md` |
| `stream_handler/` | `stream_handler/stream_handler.md` |
| `utilities/` | `utilities/utilities.md` |
| `helper_applications/recipe_creator/` | `helper_applications/recipe_creator/recipe_creator.md` |

## Documentation moves with the code — non-negotiable

A wrong context file misleads every future change; drift is a bug. **A change is not done
until the documents above describe the code as it now is, in the same change** — any added,
changed, renamed or removed file, class, public function, constant, setting, CLI option,
message, field, route, behaviour, log line, or implemented-vs-stub status.

- Write what the code does, verified in the source — never what was planned, never from memory.
  Every identifier and file a document names must exist.
- Delete what is no longer true; no stale sentence beside a corrected one.
- A routing change touches `core/core.md` **and** `messages/messages.md`.
- A recipe-format change touches `recipe_guide.html` **and** the verificator (sync rule in
  `recipe_creator.md`).
- New work items go into the roadmap as TODOs, not into code comments.
- Drift you were not asked to fix: say so in your report, ask before a large fix.

## Generated HTML documents

Ephemeral generated HTML goes in **`resources/internal_reports/`** — nowhere else. One
self-contained file: inline CSS, no external assets, light and dark palettes, inline SPDX
header (`CC-BY-SA-4.0`). Open a **newly created** one with `Invoke-Item <path>` as the last
step and say where it is; do not open one you only edited.

## Architecture in one screen

```
src/pypts/
  launcher/      entry point (python -m pypts): pins spawn, parses args, spawns Logger + CORE + frontend
  core/          mediator: routes every link, runs Sequencer + Report as threads, heartbeats, shutdown
  sequencer/     event loop; run_sequence() starts execute_sequence() on a worker thread
  recipe/        recipe data layer: parser, schema (Pydantic models), validation
  step/          step types (PythonModule, UserInteraction, UserWrite, UserLoading, Wait, Sequence,
                 Indexed — expanded at load time), Runtime seams, step.run_sequence()
  report/        report.csv (incremental) + report.html, one folder per run
  hmi/           hmi_client.py (protocol half every frontend shares), cli/, gui/ (PySide6)
  api/           Pts (headless engine driven from code), open_gui(), headless mode
  messages/      typed message dataclasses, one module per link, QueueWrapper
  config_handler/ per-user config.ini
  logger/        Logger process: the single run-log writer
  utilities/     error handling, heartbeats, local storage, recent recipes
  hal/           hardware layer: devices by logical name, one driver process each, SSH driver
  stream_handler/   stub
  helper_applications/  recipe_creator (incl. verificator), example_finder
resources/recipes/Development_recipes/   one demo recipe per step type
```

**Processes:** CORE (with Sequencer + Report threads), the HMI frontend, and the Logger. Only
HMI↔CORE crosses a process boundary, so everything on it must stay **pickle-safe** — no
queues, Qt objects or device handles. A thread entry point never calls `init_logging()`.

**Messaging:** modules never call each other or touch queues — everything goes through CORE,
except log records, which go straight to the Logger. Each link is a module
`messages/<a>_<b>_communication.py` with a union type per direction; `QueueWrapper` traces
every `send()`/`receive()` at DEBUG. Every handler is a `match` closed with `unhandled()`. To
add a message: declare the dataclass and add it to the union, then add a `case` in the
recipient's handler (`mypy` and `test_messages.py` catch the gap). Catalogue:
`messages/messages.md`.

**Errors:** `@catch_and_report_errors()` reports and continues (event loops);
`@report_and_reraise()` reports and re-raises (step layer); `report_error()` /
`report_problem()` for recognised failures. Details: `utilities/utilities.md`.

## Running

```bash
python -m pypts                       # GUI (default)
python -m pypts --mode cli            # CLI
python -m pypts --mode headless --recipe x.yml [--sequence Name]   # exit codes: api/api.md
python -m pypts --log-level TRACE     # adds the full message trace to the run log
python run_pypts.py / run_recipe_creator.py         # same, with src on the path (.bat wrappers too)
```

Config: `%LOCALAPPDATA%\pypts\config.ini` / `~/.config/pypts/config.ini`. **Never change
`CONFIG_VERSION` on your own** — only when a change adds something mandatory, and ask if
unsure (rules in `config_handler/config_handler.md`).

## Quality gates

A change is done only when all four pass:

```bash
pytest tests          # unit_tests/ + functional_tests/
ruff check src tests  # config in [tool.ruff], line length 100
mypy                  # scope in [tool.mypy]
```

4. **Documentation check** — re-read every document your change touches against the final
   code, and say in your report which ones you updated, or why none needed it.

A `# noqa:` must name a rule the config enables, with the reason on the same line.

## Code style

**Old-school, plain, readable Python. Shortest is not clearest.** An `if`/`else` over a
conditional expression, a named local over a clever one-liner (that is why `SIM108` is off).

- Logging is `%`-style, never f-strings (`G004`). `logger/logging_rules.md` is the authority on
  wording and levels: **INFO and above for the technician, everything developer-facing DEBUG**;
  the lifecycle phrases there are fixed.
- **Load-bearing — do not simplify away:** `match`/`case` closed with `unhandled()`, link union
  types, `Never`/`NoReturn`, `QueueWrapper[Msg]`. Changing them is a design conversation.
- Match existing conventions; prefer small, reviewable changes.
- **Never `git checkout` a file to undo an experiment** — it takes uncommitted work with it.
