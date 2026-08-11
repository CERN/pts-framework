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
agreed architecture change (two processes; Sequencer/Report/StreamHandler become
**threads** inside the engine process, only the HMI keeps a process boundary), the phased
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
the Phase 1 port) and `recipe_rules.html` (a rendered summary of the recipe rules).

## Layout

```
src/pypts/
  launcher/startup.py    entry point; --mode gui|cli|connect|debug; creates the queues,
                         builds the HMI<->CORE channels, spawns Logger + CORE + frontend
  messages/              the whole communication contract - one module per link (see below)
  core/core.py           mediator: routes every link, owns the submodules, heartbeat watch
  sequencer/             event loop is real; run_sequence() is still a stub
  recipe/  step/         recipe data layer + step types (empty; to be ported from old_code)
  report/                event loop is real; CSV/HTML logic is a stub (see old_code/report.py)
  hmi/hmi_client.py      the protocol half every frontend shares
  hmi/cli/  hmi/gui/     CLI shell and PySide6 GUI
  hmi/debug/             the --mode debug developer console: taps every link, injects messages
  hardware_layer/hal.py  HAL (empty stub)
  stream_handler/        StreamContainer.py, holding GlobalContainer + Stream (not integrated)
  config_handler/        INI template -> config.ini under the temp dir
  logger/log.py          the Logger process: single writer of the run log, plus init_logging()
  utilities/             error_handling, heartbeat_manager, local_storage, common
  helper_applications/   recipe_creator, recipe_verificator, example_finder (not yet refactored)
  old_code/              the frozen legacy implementation - read only, never modify
resources/roadmap/       the plan, plus the recipe guide
resources/recipes/       example recipes (YAML, *.yml)
tests/                   unit_tests/ + functional_tests/
```

## Communication model (important)

Modules never touch queues directly and never call each other. Everything goes through
CORE — except log records, which go straight to the Logger.

Every message is a **frozen slotted dataclass** of plain values. Each *link* gets its own
module under `pypts/messages/` holding both directions and a union type per direction
(`hmi_link.py`, `sequencer_link.py`, `report_link.py`, `logger_link.py`; `common.py` and
`run_events.py` hold what more than one link shares). One generic `Channel` in
`channel.py` is the transport for all of them — it wraps anything with `put()` and
`get_nowait()`, which is what keeps the roadmap's thread migration cheap.

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
python -m pypts                # --mode debug is the default for now (see below)
python -m pypts --mode cli     # CLI mode
python -m pypts --mode gui     # GUI mode (PySide6)
python -m pypts --mode debug   # developer console: shows every link, injects messages
python run_tests.py            # unit tests, then functional tests
pytest tests                   # the same suite, directly
```

Two things to know about `--mode`:

- The default is **`debug`**, not `gui`, for the duration of the refactor — the execution
  engine is a stub, so the console is far more useful than an idle status label. Putting
  it back to `gui` before v1.0 is a TODO in the roadmap.
- `--mode connect` is accepted by argparse but **has no branch**, so it silently falls
  through and starts the CLI. It is not implemented.

## Working style

- The user orchestrates specific tasks; do that task, not the surrounding ones.
- Prefer small, reviewable changes aligned with the roadmap phase in progress.
- Match existing conventions (frozen message dataclasses, link modules, `unhandled()`-closed
  handlers, module layout) rather than introducing new patterns unasked. For SPDX headers,
  follow `reuse.toml` — see above.
