# Plan 001 — Report run-state hardening

**Status: DONE** (branch `exec/001-report-run-state`, commit `9a9edad`)

## What was done

- `src/pypts/report/report.py` — `start_run()` clears all per-run state *before* calling
  `make_run_dir()`, so a failed mkdir leaves the Report in the clean "no run open" state
  instead of silently rewriting the previous run's `report.html`.
- `src/pypts/report/report.py` — `make_run_dir()` caps `safe_name` to 60 chars and
  substitutes `"recipe"` for an empty result.
- `tests/unit_tests/test_report.py` — three new tests:
  `test_a_failed_run_dir_does_not_resurrect_the_previous_run`,
  `test_run_dir_name_is_capped_and_never_empty`,
  `test_stop_closes_the_csv_and_answers_report_stopped`.
- `resources/roadmap/pypts_roadmap.md` §1.19 — one `[x]` entry added.
- Ruff I001 in `report.py` cleared as a side-effect.
