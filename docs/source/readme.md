<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# docs/source — contents summary

Quick guide to every file in this directory. Read before adding or rewriting a doc.

---

## Sphinx-built pages (`.rst`)

| File | What it covers | Keep? |
|---|---|---|
| `index.rst` | Sphinx root — toctrees for "Getting started" and "Reference". Entry point for `make html`. | Yes |
| `usage.rst` | How to run pypts: `python -m pypts`, `--mode cli`, `--log-level`, step-type quick reference table, recipe structure overview. | Yes |
| `troubleshooting.rst` | Common problems and fixes: startup errors, config file issues, step type errors, log file location. | Yes |
| `yaml_format.rst` | Full YAML recipe format reference: header, sequence, all step types with field tables, `input_mapping`/`output_mapping` syntax, `output` type vocabulary. The user-facing complement to `recipe_guide.md`. | Yes |
| `architecture.rst` | Two-process architecture overview: CORE + HMI + Logger, Sequencer and Report as threads, message protocol, process topology diagram. | Yes |
| `gui_event_handling.rst` | How the GUI receives run events: `HmiClient` poll thread, typed message objects (`StepStarted`, `StepFinished`, …), Qt signal dispatch. Replaces the old `RecipeEventProxy` description. | Yes — but thin |
| `report_generation.rst` | Report output: per-run folder, incremental CSV columns, `report.html` generation on `RunFinished`, `ReportReady` message. | Yes — but thin |
| `api.rst` | Python API: new entry point (`python -m pypts`), note that the old `run_pts`/`PtsApi` are gone, pointer to the Phase 2 plugin plan. | Yes — but currently minimal |
| `dependency_license_analysis.rst` | License inventory of all third-party dependencies: SPDX IDs, compatibility notes. Mainly for REUSE compliance review. | Yes — but generated/static |

## Markdown pages (`.md`)

| File | What it covers | Keep? |
|---|---|---|
| `migration_instructions.md` | Moving an old recipe to the new architecture: step-type rename table, dropped types, entry-point change (`__main__.py` → `python -m pypts`), report path change, magic globals no longer needed. | Yes |
| `pre_refactoring.md` | Complete old-engine reference: single-process model, `run_pts`/`create_and_start_gui` API, all 10 old step types with behaviour, `RecipeEventProxy` GUI pattern, old report pipeline, old recipe format differences. Read when integrating anything from `old_code/`. | Yes — keep until old_code/ is deleted |
| `readme.md` | This file. | Optional |

## Notes on thin pages

`gui_event_handling.rst`, `report_generation.rst` and `api.rst` are currently short stubs
rewritten for the new architecture but not yet detailed. They are accurate for what they say;
they just don't say much. They can grow as the features they describe are completed in Phase 1
and Phase 4.

`dependency_license_analysis.rst` rarely needs editing — it is a static snapshot updated when
dependencies change.
