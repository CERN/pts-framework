# PyPTS planning session — context notes (2026-07-17)

*Companion file to `pypts_roadmap.md`. Purpose: restore full context when we pick this conversation up again (in a new Claude session, paste/attach both files or point Claude at this folder).*

## What this session did

1. Studied the **Confluence spec** — `[PTS] Framework specification` (page 523537309, MTA space) and all children: General requirements, Milestones (v0.3.0 / v1.0.0), Development workflow, Usage workflow, Quick start (stub), Modules parent + 12 module pages (CORE, SEQUENCER, STEP, RECIPE, GUI, CLI, REPORT, HARDWARE LAYER, LOGGER, CONFIG HANDLER, STREAM HANDLER, Helper applications).
2. Analyzed the repo `C:\Git\pypts` — **first mistakenly on the master working tree**, then correctly on **branch `architecture_refactor`** (read from GitLab `origin/architecture_refactor` via browser, because the local device bridge dropped mid-session). If resuming: verify whether the local checkout has since been updated/merged.
3. Produced **`pypts_roadmap.md`** (same folder): current-state assessment of the branch, phased roadmap (v0.3.0 → v1.0.0), plugin architecture proposal, risks — plus a marked **TODO section** with the final agreed topology.

## State of branch `architecture_refactor` (as of this session)

- **Done:** process skeleton (launcher `--mode gui/cli`, Core spawning Sequencer+Report), typed message files (CORE/HMI/SEQUENCER/REPORT/COMMON_MESSAGES) + interface/queue-data-layer classes, HeartbeatManager + timeout warnings, `@catch_and_report_errors`, PySide6 migration, REUSE/LGPL-2.1 licensing (reuse.toml, SPDX headers, licenses/), logger (file+stdout, toggle), INI config handler in %TEMP%, real recipe verificator (line maps, faults/warnings), recipe creator GUI, unit_tests/ + run_tests.py, resources/ reorg.
- **Placeholders:** `sequencer.run_sequence()`, `report.generate/export`, `recipe/recipe.py` (one comment line), `step/` (empty), `hal.py` (one comment line), Core's LOAD_RECIPE/START_SEQUENCE handlers.
- **The working engine lives in `src/pypts/old_code/`** (newer than master: consolidated steps.py, resource-based `test_package` loading — see docs/source/architecture.rst). Critical path = port it into the skeleton, then delete old_code at v0.3.0.
- **Known defects found:** `verify_recipe.py` imports `RECIPE_*_REQUIRED_FIELDS` from `pypts/__init__.py` which no longer defines them (broken import); `catch_and_report_errors` swallows exceptions + `nonlocal`/stack-inspection bug; per-process import side effects (log file + config rewrite per process); heavy core deps (matplotlib, numpy, nptdms, nidmm, hightime, pyserial, paramiko, PySide6); `eval(step_type)` step factory in old_code; project renamed `pts-framework` in pyproject (PyPI name check pending).

## Decisions made in this conversation (the important part)

1. **Refactor: yes** — old architecture too nested/coupled (Recipe = data + engine + events; step class duplication; GUI stitched via string events). Port incrementally in small MRs with characterization tests; avoid the two-codebases stall.
2. **Topology (agreed, marked TODO in roadmap):**
   - Launcher (thin supervisor) spawns **two processes**: HMI/GUI process and Engine process. GUI is NOT spawned by Core — supervisor must be the dumbest, most stable part; GUI must survive an engine crash to report it.
   - Inside the engine: **Core = main thread; Sequencer, Report, StreamHandler = threads**. **HAL = plain imported library** (no process/loop/queue) — HAL-as-process was rejected (RPC on every driver call, breaks standalone-HAL requirement, forces bulk acquisition data through pickling).
   - Same typed interfaces everywhere; the launcher injects the queue type (`multiprocessing.Queue` at the GUI seam, `queue.Queue` in-engine). Thread↔process stays a one-line launcher change.
3. **Rationale — "solid data channels for any data":** pickling is a toll gate; arbitrary objects (device handles, live queues, step outputs) can only flow in-process by reference. Channel tiers: (1) control = typed pickle-safe dataclasses, (2) results = serializable dicts/dataclasses, (3) bulk streams = in-process reference / shared_memory / file-path handoff — never through message queues.
4. **Performance verdict:** threads win for this I/O-bound workload; process queues ~6× slower on large payloads (pickle+pipe+copy); free-threaded Python 3.13/3.14 removes the GIL argument long-term.
5. **Discipline items to earn "10/10":** CI test pickling every HMI↔Core message round-trip; defined heartbeat-timeout policy (restart/abort/notify — today warn-only); promotion rule = a module becomes a process only after a concrete incident (crash-prone C driver → sidecar wrapping that one driver).
6. **Plugin approach (boss requirement — extend/shrink on demand):** contract + discovery + registry.
   - `pypts.api` = small stable ABCs (StepPlugin with steptype/input_schema/output_schema/execute(ctx, inputs); Device/PowerSupply for HAL; ReportGenerator). Plugins import ONLY pypts.api; everything runtime comes via `StepContext`.
   - Discovery via **entry points** (groups: `pypts.steps`, `pypts.drivers`, `pypts.report_formats`, `pypts.gui_widgets`, `pypts.stream_formats`, `pypts.verification_rules`). Extend = `pip install pypts-xxx`, shrink = uninstall.
   - `PluginRegistry` with lazy loading replaces the `eval()` step factory; schema constants (`STEP_REQUIRED_FIELDS` etc.) become derived from registered step plugins (also fixes the broken verificator import).
   - Drivers as pip-installable plugin packages, NOT git submodules (deviates from HAL wiki page — argued in roadmap §3.6). Heavy deps move out of core into driver/extra packages.
   - Plugins load inside the module that owns them (steps in Sequencer, widgets in GUI) — plugin system and process/thread question are independent.
   - Patterns named: mediator/hub-and-spoke (Core), actor model (module loops), supervisor (heartbeats), ports & adapters (plugin API), sidecar (rogue drivers).
7. **User's approach rated:** initial (GUI+CORE+HAL as processes) 6.5/10 — HAL-as-process was the main flaw; corrected final design (above) 8.5/10, remaining points are execution discipline, not architecture.

## Open items / where to resume

- Transfer the TODO checklist in `pypts_roadmap.md` into GitLab issues.
- Phase 0 first: fix verificator import, error-decorator policy, log/config process policy, CI green, characterization tests around old_code.
- Then Phase 1 port order: Recipe (data-only) → Step+Sequencer (threads) → Core handlers → Report → CLI → delete old_code → tag v0.3.0.
- Decide `pypts.api` contracts with module owners before Phase 2 ends; check `pts-framework` name availability on PyPI.
- Spike: user-prompt request/response message pair across the HMI boundary (replaces live queue-in-event).

## Key links

- Spec root: https://confluence.cern.ch/spaces/MTA/pages/523537309/PTS+Framework+specification
- Repo: https://gitlab.cern.ch/pts/framework/pypts (branch `architecture_refactor`)
- Local checkout: C:\Git\pypts
