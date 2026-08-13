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
does. It blanket-covers `src/pypts/**/*.py`, `tests/**/*.py`, `spikes/**/*.py` and a named
list of config/doc/image paths, so **a new file in one of those paths needs no inline SPDX
header**. A new file *outside* those globs does — `resources/**` is the common case, which
is why the recipes and the roadmap docs carry their own headers. Most Python files here
have an inline header anyway; that is harmless (the annotations are `precedence =
"aggregate"`) but it is a habit, not a requirement.

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

It contains: the current state of the branch (done / placeholder / known defects), the
architecture change (two processes; Sequencer/Report become **threads** inside the engine
process — **done**, see §1.5 — with StreamHandler to follow as a third), the phased
roadmap (Phase 0 stabilize → Phase 1 port the engine → Phase 2 plugins → … → v1.0.0),
the plugin/`pypts.api` proposal, and the risks/open questions.

Keeping it current is part of every task:

- New work items and follow-ups go in as **TODOs in this file** — not scattered in code
  comments, not in a separate plan file.
- When something is implemented, update its status there (move it out of "placeholder",
  tick the TODO) in the same change that implements it.
- If reality and the roadmap disagree, say so and ask — do not silently work around it.

Supporting context in the same folder: `recipe_guide.md` (what a recipe is, what the old
engine actually does with it, and the proposed format for the new one — the reference for
the Phase 1 port). The rendered summary of the recipe rules is
`resources/internal_reports/recipe_rules.html`, with every other HTML document.

## Module context files

A module may carry a `<module>.md` next to its code holding the whole context of that
folder — what each file owns, the rules that shape it, the decisions behind them, how to
extend it, and its known gaps. **Read it before doing anything with that module**; it is
there so the source does not have to be re-read from scratch each time, and it knows more
about its module than this file or the roadmap does.

- Present so far: `src/pypts/config_handler/config_handler.md`,
  `src/pypts/messages/messages.md`.
- It explains *how the module works*. The roadmap stays the authority on *status and plan*;
  where they overlap, the roadmap wins and the module file should point at it.
- Keeping it current is part of changing the module — update it in the same change, the way
  the roadmap is updated.

## Where generated HTML documents go

**Every HTML report, summary or overview the user asks for is saved in
`resources/internal_reports/`.** Not the repo root, not next to the code it describes, not a
scratch directory, not loose in `resources/` — the user opens these in a browser and expects
every one of them in one folder. This holds for *all* HTML documents in the project.

- One self-contained file: inline CSS, no external assets, light *and* dark palettes. It has
  to open from disk with no network.
- `resources/**` is **not** covered by `reuse.toml`, so such a file needs its own inline SPDX
  header — `CC-BY-SA-4.0` for documentation, matching the two below.
- Say where you put it, and offer to open it.
- Present so far: `messaging_overview.html` (the communication model) and
  `recipe_rules.html` (a rendered summary of the recipe rules), both in
  `resources/internal_reports/`.

## Layout

```
src/pypts/
  launcher/startup.py    entry point; --mode gui|cli|connect and --log-level; creates the
                         queues, builds the HMI<->CORE links, spawns Logger + CORE + frontend
  messages/              the whole communication contract - one module per link (see below,
                         and messages.md for the catalogue)
  core/core.py           mediator: routes every link, runs Sequencer + Report as threads,
                         heartbeat watch
  sequencer/             thread of CORE; event loop is real, run_sequence() is still a stub
  recipe/  step/         recipe data layer + step types (empty; to be ported from old_code)
  report/                event loop is real; CSV/HTML logic is a stub (see old_code/report.py)
  hmi/hmi_client.py      the protocol half every frontend shares
  hmi/cli/  hmi/gui/     CLI shell and PySide6 GUI
  hardware_layer/hal.py  HAL (empty stub)
  stream_handler/        StreamContainer.py, holding GlobalContainer + Stream (not integrated)
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

Every message is a **frozen slotted dataclass** of plain values. Each *link* gets its own
module under `pypts/messages/`, named for the two ends it joins and holding both directions
and a union type per direction (`core_hmi_link.py`, `core_sequencer_link.py`,
`core_report_link.py`, and `to_logger_link.py`, which is named for its single direction
because nothing is sent back; `common.py` and `run_events.py` hold what more than one link
shares, `links.py` the name of each direction). One generic `QueueWrapper` in
`queuewrapper.py` is the transport for all of them — it wraps anything with `put()` and
`get_nowait()`, which is what lets the same class serve a process boundary and a thread
boundary. The catalogue of what each link carries is `messages/messages.md`.

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

Everything else is found for you: a type checker flags every `match` that is now
incomplete, and `tests/unit_tests/test_messages.py` fails until the message has an
example and a branch.

Anything crossing the HMI↔Core boundary must stay **pickle-safe** — no live queues, no Qt
objects, no device handles.

## Running

```bash
python -m pypts                       # GUI mode (PySide6) - the default
python -m pypts --mode cli            # CLI mode
python -m pypts --log-level DEBUG     # adds the full message trace to the run log
python run_tests.py                   # unit tests, then functional tests
pytest tests                          # the same suite, directly
```

`--log-level` overrides `[logging] level` in the generated `config.ini`, which ships as
`INFO`. The file lives in the per-user config directory (`%LOCALAPPDATA%\pypts\config.ini`
on Windows, `~/.config/pypts/config.ini` on Linux); the launcher creates it from the
template on first run and migrates it when its structure version is older than the code's.
A leftover `%TEMP%/pypts/config/config.ini` from an older build is no longer read at all.

`--mode connect` is accepted by argparse but **has no branch**, so it silently falls
through and starts the CLI. It is not implemented.

## Working style

- The user orchestrates specific tasks; do that task, not the surrounding ones.
- Prefer small, reviewable changes aligned with the roadmap phase in progress.
- Match existing conventions (frozen message dataclasses, link modules, `unhandled()`-closed
  handlers, module layout) rather than introducing new patterns unasked. For SPDX headers,
  follow `reuse.toml` — see above.
