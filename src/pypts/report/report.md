<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# report — builds the run artefacts

`report.py` is the only file. `report_main()` runs `Report(...).start()` as a **thread of the
Core process**; everything it knows arrives as messages forwarded by CORE. The run folder
comes on `RunStarted`; `paths.reports_dir` (or a test's `output_dir`) is only where the Report
makes one itself when `RunStarted` names none.

## What it owns

- **Run folder** — on `RunStarted`, `start_run()` writes into `RunStarted.run_dir`, the
  folder the Sequencer made (`sequencer/sequencer.md`), where the run's log is already being
  written. Only when that is `""` - the Sequencer could not make it, or the Report is driven
  directly - does it make one itself with `utilities.local_storage.make_run_folder()`
  (`<reports_dir>/<YYYYmmdd_HHMMSS>_<recipe name>/`: non-alphanumerics become `_`, at most 60
  characters, `recipe` if nothing is left, `_2`, `_3`… if it already exists). It opens
  `report.csv` (`LIVE_CSV_NAME`) with the header row written and flushed, logs the folder at
  INFO, and keeps the start time twice: `run_started_at` for the rows, `file_timestamp`
  (`YYYYmmdd_HHMMSS`) for the file names.
- **Incremental CSV** — `record_step()` appends one row per `StepExecuted`, flushed
  immediately, and keeps it in `self.rows`. `SequenceStarted` sets the `sequence_name`
  stamped on the rows that follow. A `StepExecuted` with no run open is a WARNING and is
  dropped.
- **Metadata** — `RunMetadata` updates `self.metadata` (`record_metadata()`), the recipe's
  `report_metadata` globals as the run learns them. Rows already written keep their blanks
  until the run ends.
- **End of run** — on `RunFinished`, `finish_run()` stores the verdict, closes the CSV, then:
  - `rewrite_csv()` writes `report.csv` once more with every row's run-level cells
    (`run_result`, metadata) filled in.
  - `rename_csv()` gives it its final name, `file_stem()` + `.csv`. A rename that fails is a
    WARNING and the file stays `report.csv` - the name is cosmetic, the results are not.

  A run that dies before `RunFinished` leaves its flushed rows in `report.csv`.

  The folder keeps its name: it is not renamed with the metadata any more (2026-10-09),
  because the run log is open inside it for the whole run, and Windows will not rename a
  folder with an open file in it.
- **File names** — `file_stem()` = `utilities.local_storage.report_file_stem(board_id(),
  file_timestamp)`: `<board id>_<YYYYmmdd_HHMMSS>`, e.g. `SN_0042_20261013_142530.csv` /
  `.html`. `board_id()` is the value of the recipe's **first** `report_metadata` global
  (`serial_number` by default); the id goes through `safe_name_part()`, so `SN-0042` becomes
  `SN_0042`. A run that never learned it, or whose recipe has `report_metadata: []`, is
  `report_<YYYYmmdd_HHMMSS>`. The timestamp is when the Report received `RunStarted`.
- **HTML** — CORE sends `GenerateReport` right behind `RunFinished`. `generate_report()` writes
  a self-contained `<file_stem()>.html` (header with metadata, recipe, verdict, start time and pypts
  version; a per-result summary; one table row per step, coloured by result) and sends
  `ReportGenerated(report_path)`. With no run recorded it is a WARNING and nothing is sent.
- **Regenerable from the CSV alone** — every run-level value is on every row, so
  `render_html()` needs only rows; `rows_from_csv(path)` reads a past run's CSV back into
  them. A run in which no step executed has no rows to regenerate from.
- **Export** — `ExportReport` is a **stub at both ends**: `export_report()` only logs a
  WARNING, and nothing sends the message.

## CSV columns

`columns_for(metadata_names)` = `RUN_COLUMNS` + one `metadata_column(name)` per
`report_metadata` name + `STEP_COLUMNS`. `CSV_COLUMNS` is the set for a run that declares no
metadata.

**Metadata columns are prefixed** with `METADATA_PREFIX` (`meta_`): `serial_number` is the
column `meta_serial_number`. The names are the recipe's, and without the prefix a global
called `result` shared the step verdict's column - `rewrite_csv()` then overwrote every
row's verdict with it, so a FAIL step read PASS (codebase review #3, 2026-10-14). No built-in
column starts with `meta_`, so no name can clash and none has to be refused. The prefix
lives only at the CSV boundary (`columns_for()`, `run_level_cells()`, the HTML header's
lookup): `RunMetadata`, `self.metadata`, the HTML header's label and `board_id()` use the
bare name. A CSV written before the prefix has bare metadata columns, and the HTML rebuilt
from it with `rows_from_csv()` shows no metadata.

| Group | Columns |
|-------|---------|
| `RUN_COLUMNS` (repeated on every row) | `recipe_name`, `recipe_description`, `recipe_version`, `pypts_version`, `run_started_at`, `run_result` |
| metadata | `meta_<name>` per `report_metadata` name, in recipe order |
| `STEP_COLUMNS` | `sequence_name`, `step_name`, `step_id`, `step_type`, `result`, `inputs`, `outputs`, `error_info`, `started_at`, `duration_s` |

`inputs` / `outputs` are JSON (`default=str`); times are local `YYYY-mm-dd HH:MM:SS`;
`run_result` and metadata cells are empty in the flushed rows until `rewrite_csv()`.

## State

| State | Condition |
|-------|-----------|
| No run open | `run_dir is None` — `finish_run` returns early, `generate_report` warns; `record_step` warns whenever `csv_writer is None` |
| Run open | `run_dir` set, CSV open and growing |
| Run finished | `run_dir` set, CSV closed, rewritten and renamed (`csv_path` follows it), `run_result` set |
| Stopped | `running = False`, CSV closed |

`start_run()` clears all per-run state *before* making the folder, so a failed `mkdir`
leaves the Report in "no run open" rather than attributing the new run to the previous
run's folder.

## Error boundary and shutdown

CORE holds `StopReport` until `SequencerStopped` arrives (`core/core.md` → *Shutdown*). This
guarantees the aborted run's `StepExecuted` tail, `RunFinished` and `GenerateReport` reach the
Report before it stops.

`stop()` sends `ReportStopped` from a `finally`, through `send_goodbye()`, so closing the CSV
— file I/O, and the likeliest thing here to raise — cannot cost CORE its whole shutdown budget
and get the Report named as the module that hung. `start()` carries the same `finally` for a
loop that dies rather than ends, and `send_goodbye()` is guarded so only one `ReportStopped`
goes out. Same guarantee, and same reasons, as `Sequencer.stop()` / `Sequencer.start()`.

Decorated with `@catch_and_report_errors()`: `start()`, `poll_core()`,
`handle_core_message()`, `do_periodic_tasks()` (the heartbeat). `stop()` and the per-message
handlers (`start_run`, `record_step`, `record_metadata`, `finish_run`, `rename_csv`,
`generate_report`, `export_report`) are **undecorated** — the error boundary is `handle_core_message()`. See
`utilities/utilities.md` for the rule.

## Known gaps

- `ExportReport` / `ReportExported` — stub, no trigger anywhere.
- TDMS plots, configurable templates, `report.type` / `report.theme` — planned (roadmap §1.19,
  Phase 4).
