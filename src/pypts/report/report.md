<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# report — builds the run artefacts

Two files: `report.py` (the Report: run folder, CSV, verdict, file names) and
`html_report.py` (the HTML page, built from the CSV rows). `report_main()` runs `Report(...).start()` as a **thread of the
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
- **Environment** — `run_level_cells()` stamps every row with the machine the run is on:
  `host_name` (`platform.node()`), `platform` (`platform.platform()`) and `python_version`
  (`platform.python_version()`). The Report is a thread of the Core process, which runs the
  steps, so its platform is the run's.
- **End of run** — on `RunFinished`, `finish_run()` stores the verdict and `run_finished_at`
  (local `YYYY-mm-dd HH:MM:SS`), closes the CSV, then:
  - `rewrite_csv()` writes `report.csv` once more with every row's run-level cells
    (`run_result`, metadata) filled in. With no recorded rows it returns early and
    `report.csv` stays as written — header only.
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
  `<file_stem()>.html` and sends `ReportGenerated(report_path)`; `render_html()` picks the
  run-level row and the metadata and hands them to `html_report.render_report()` (see *The
  HTML page* below). With no run recorded it is a WARNING and nothing is sent.
- **Regenerable from the CSV — rows only** — every run-level value is on every row, and
  `rows_from_csv(path)` reads a past run's CSV back into `self.rows`. But `render_html()`
  takes no rows argument — it reads `self.rows` — and it takes the metadata *names* from
  `self.run_info`, so a rebuild from any CSV shows no metadata (no identity line, no metadata in the Run card). A run in which
  no step executed has no rows to regenerate from.
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
bare name. The metadata names themselves come from `self.run_info`, not from the CSV, so an
HTML rebuilt with `rows_from_csv()` shows no metadata whatever the CSV's vintage.

| Group | Columns |
|-------|---------|
| `RUN_COLUMNS` (repeated on every row) | `recipe_name`, `recipe_description`, `recipe_version`, `pypts_version`, `run_started_at`, `run_finished_at`, `run_result`, `host_name`, `platform`, `python_version` |
| metadata | `meta_<name>` per `report_metadata` name, in recipe order |
| `STEP_COLUMNS` | `sequence_name`, `step_name`, `step_id`, `step_type`, `result`, `inputs`, `outputs`, `error_info`, `started_at`, `duration_s` |

`inputs` / `outputs` are JSON (`default=str`); times are local `YYYY-mm-dd HH:MM:SS`;
`run_finished_at`, `run_result` and metadata cells are empty in the flushed rows until
`rewrite_csv()`. `run_finished_at`, `host_name`, `platform` and `python_version` were added
2026-11-02; a CSV from before has none of them, and `rows_from_csv()` still reads it (the
page shows the run time as "Time in steps" and the Environment card as not recorded).

## The HTML page (`html_report.py`)

`render_report(rows, first_row, metadata, generated_at)` returns one self-contained page:
inline CSS (`PAGE_CSS`), a small inline script (`PAGE_SCRIPT`), and the CERN logo as a
data URI (`logo_data_uri()`, read with `importlib.resources` from the GUI's copy,
`pypts.hmi.gui/images/CERN_Logo.png` — one file in the package, not two; if it cannot be
read the page simply has no watermark, logged at DEBUG). No external asset of any kind.
Light theme only.

From top to bottom:

- **Masthead** — recipe name; the identity line (each non-empty `report_metadata` value under
  its `humanise()`d name, `serial_number` → "Serial number", then the start time); the
  description; the verdict box, coloured by result (`IN PROGRESS` when no `RunFinished`
  arrived).
- **Metric tiles** — *Steps*, *Failed, error or stopped* (`PROBLEM_RESULTS`, red when above
  0), *Wall time* (`run_finished_at - run_started_at`; "Time in steps", the sum of the step
  durations, when the finish time is unknown), and one **filter chip** per result present,
  worst first. Unticking a chip hides the rows with that result.
- **Run** and **Environment** cards — metadata, recipe version, start and finish;
  `ENVIRONMENT_FIELDS`. A CSV with no environment columns shows one "Not recorded" line.
- **Steps table** — buttons *Problems only*, *All results*, *Show all details*, *Hide all
  details*; a sticky header. Rows are grouped by consecutive `sequence_name`
  (`group_rows()`): each group has a header with its per-result counts. The sequence's own
  row (`step_type == SEQUENCE_STEP_TYPE`) comes after its steps; when it is the group's last
  row and names the group, `split_closing_row()` moves its result and duration onto the
  header instead of a row. Any other sequence row stays as a muted "Sequence finished:" row.
  Every step row is **collapsed**: a summary line (toggle button, result badge, name, type
  without its `Step` suffix, duration via `format_duration()`), and under the name the
  error's headline (`error_headline()`: a traceback's last line, otherwise the first line).
  The hidden detail row holds the full error (scrolled to its end on opening), the inputs
  and outputs side by side as indented JSON (`pretty_json()`; empty objects are left out),
  and the start time and step id. A row with nothing to show has no toggle.
- **Counting** — sequence rows are summaries, not steps: `count_results()` skips them, for
  the tiles, chips and group counts alike.
- **Print** — colours kept (`print-color-adjust: exact`), buttons hidden, every detail row
  shown in full, filtered rows stay hidden (it prints what is on screen).

Safety: every value from the recipe or the test code goes through `html.escape()`; result
names become CSS classes only through `result_class()`, which lets through the
`ResultType` names alone; the script toggles classes and attributes, never writes markup.

Known limit: the grouping follows `sequence_name` as stamped, so a nested sequence shows as
consecutive flat groups, not indented — the CSV records no nesting depth.

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
- `sequence_name` is not restored when a nested sequence ends: the rows after it keep the
  inner sequence's name (e.g. the showcase's `Power on` is stamped `Settle`, not
  `PowerCycle`), so the HTML groups them under the wrong header. Not fixed yet.
- TDMS plots, configurable templates, `report.type` / `report.theme` — planned (roadmap §1.19,
  Phase 4).
