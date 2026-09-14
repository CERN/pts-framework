<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# report — builds the run artefacts

`report.py` is the only file. Runs as a **thread of the Core process**.

## What it owns

- **Run lifecycle** — `start_run()` creates `<reports_dir>/<timestamp>_<name>/report.csv`
  and writes the header. `finish_run()` records the overall result. `generate_report()`
  writes `report.html` and sends `ReportGenerated` back to CORE.
- **Incremental CSV** — one row per step, written and flushed immediately on each
  `StepExecuted` message. The CSV file is the record of truth; the HTML is derived from it.
- **Metadata tracking** — `RunMetadata` messages from the Sequencer update per-run metadata
  columns (e.g. `serial_number`) that are stamped on every subsequent row.
- **Export** — `ExportReport` copies the run folder to a configurable export destination.

## CSV columns

Run-level columns (repeated on every row): `recipe_name`, `recipe_description`,
`recipe_version`, `pypts_version`, `run_started_at`, `run_result`, plus any
`report_metadata` names from the recipe.

Step-level columns: `sequence_name`, `step_name`, `step_id`, `step_type`, `step_started_at`,
`step_result`, `step_inputs`, `step_outputs`, `step_error`.

## State machine

| State | Condition |
|-------|-----------|
| No run open | `run_dir is None` — guards in `record_step`, `finish_run`, `generate_report` return early |
| Run open | `run_dir` is set, CSV is open |
| Stopped | `running = False`, CSV closed |

`start_run()` clears all per-run state *before* calling `make_run_dir()` (plan 001), so a
failed `mkdir` leaves the Report in "no run open" state.

## Shutdown

CORE holds `StopReport` until `SequencerStopped` arrives (plan 002). This guarantees the
aborted run's `StepExecuted` tail and the `RunFinished` reach the Report before it stops.

## Known gaps

- `serial_number` column and TDMS export — planned (roadmap §1.19).
- `ExportReport` destination is configured but not fully exercised in tests.
