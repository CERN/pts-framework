# Plan 001: Make a failed run-folder creation impossible to misattribute to the previous run

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 800db1c..HEAD -- src/pypts/report/report.py tests/unit_tests/test_report.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `800db1c`, 2026-08-21

## Why this matters

If `make_run_dir()` raises in `Report.start_run()` (unwritable reports dir, a
recipe name long enough to blow the Windows ~260-char path limit), the
`@catch_and_report_errors()` decorator swallows the exception and the Report
keeps the **previous** run's `run_dir`, `run_info` and `rows`. The new run's
steps are then dropped with only a warning, `finish_run()` stamps the new run's
verdict onto the old state, and `generate_report()` **rewrites the previous
run's `report.html` inside the previous run's folder** and announces that stale
path to the operator via `ReportGenerated` → `ReportReady`. On a test bench that
is one run's results attributed to another run's artefacts — the worst kind of
report corruption, and the only trace is two log warnings. The fix is to reset
the run state *before* attempting the mkdir, so a failure leaves the Report in
the clean "no run open" state its other methods already guard against.

Context that lowers risk: this framework has **no deployed benches yet**
(maintainer's statement, 2026-08-21), so nothing downstream consumes the CSV or
folder layout — behavior changes here are cheap right now.

## Current state

Relevant files:

- `src/pypts/report/report.py` — the Report module (a thread of the Core
  process). The bug lives in `start_run()` (lines 144–161) and the hardening
  target is `make_run_dir()` (lines 163–175).
- `tests/unit_tests/test_report.py` — the test file; already contains the
  helpers to use (`build_report`, `drive`, `sent_to_core`, `a_step_executed`,
  `csv_rows`).

`start_run()` as it exists today (`report.py:144-161`) — note that
`self.run_dir` is assigned from `make_run_dir()` **before** the old
`run_info`/`run_result`/`rows`/`current_sequence` are cleared:

```python
@catch_and_report_errors()
def start_run(self, event: RunStarted) -> None:
    """Open this run's folder and its CSV, header written and flushed."""
    self.close_csv()
    self.run_dir = self.make_run_dir(event.recipe_name)
    self.run_info = event
    self.run_result = None
    self.rows = []
    self.current_sequence = ""

    csv_path = self.run_dir / "report.csv"
    # SIM115 silenced because the file *must* outlive this method: it
    # grows for the whole run, and close_csv() owns the close.
    self.csv_file = open(csv_path, "w", newline="", encoding="utf-8")  # noqa: SIM115
    self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=list(CSV_COLUMNS))
    self.csv_writer.writeheader()
    self.csv_file.flush()
    log.info("Recording run results to: %s", csv_path)
```

`make_run_dir()` as it exists today (`report.py:163-175`) — no length cap, no
empty-name guard:

```python
def make_run_dir(self, recipe_name: str) -> Path:
    """
    One folder per run: <reports_dir>/<timestamp>_<recipe name>.
    """
    safe_name = "".join(c if c.isalnum() else "_" for c in recipe_name)
    base = time.strftime("%Y%m%d_%H%M%S", time.localtime()) + "_" + safe_name
    run_dir = self.output_dir / base
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = self.output_dir / f"{base}_{suffix}"
    run_dir.mkdir(parents=True)
    return run_dir
```

The downstream guards that make "run_dir is None" the safe state already exist
and must not be weakened:

- `record_step()` (`report.py:182-186`) drops a row with a warning when
  `csv_writer is None`.
- `finish_run()` (`report.py:210-212`) returns with a warning when
  `run_dir is None`.
- `generate_report()` (`report.py:229-231`) returns with a warning when
  `run_dir is None or run_info is None`.

The error still reaches the operator when `start_run` fails: the
`@catch_and_report_errors()` decorator (defined in
`src/pypts/utilities/error_handling.py`) sends a `ModuleError` to CORE through
`self.core`, and CORE shows anything above WARNING to the frontend. That
behavior is free — do not add extra reporting.

Repo conventions that apply here (from `CLAUDE.md`):

- Logging is `%`-style, never f-strings: `log.warning("Dropping %s", name)`.
  Ruff rule `G004` enforces it.
- Plain, old-school Python: prefer `if`/`else` over clever one-liners.
- Tests drive the Report exactly as CORE does — through the inbox and
  `poll_core()` — and assert on disk artefacts. Model new tests on the
  existing ones in `tests/unit_tests/test_report.py` (see its `drive()` and
  `build_report()` helpers, lines 28–63).

## Commands you will need

Run from the repo root `C:\Git\pts-framework` (Windows). All three quality
gates must pass before the work is called done.

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `.venv\Scripts\python.exe -m pytest tests -q` | `... passed, 45 skipped`, exit 0 |
| Report tests only | `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_report.py -q` | all pass |
| Lint | `.venv\Scripts\python.exe -m ruff check src tests` | no NEW findings (see note) |
| Typecheck | `.venv\Scripts\python.exe -m mypy` | `Success: no issues found` |

Notes:
- If pytest errors with `PermissionError ... pytest-of-Dzbanan`, the machine's
  pytest temp root is broken — add
  `--basetemp=C:\Git\pts-framework\.pytest-tmp` to the pytest command (the
  directory is disposable; do not commit it).
- `ruff check src tests` currently reports **6 pre-existing findings** at the
  planned-at commit (3 in `logger/log.py`, `report/report.py:10` I001,
  `sequencer/sequencer.py:146` E501, `sequencer/sequencer.py:213` BLE001).
  Those are not yours to fix in this plan **except** `report/report.py:10`
  (I001, unsorted imports): since you are editing this file anyway, run
  `.venv\Scripts\python.exe -m ruff check --fix src/pypts/report/report.py`
  as part of Step 1 so the file you touch leaves clean. Success = ruff reports
  at most the remaining 5 findings, none of them in `report.py`.

## Scope

**In scope** (the only files you should modify):

- `src/pypts/report/report.py`
- `tests/unit_tests/test_report.py`
- `resources/roadmap/pypts_roadmap.md` (one status line, Step 4)
- `plans/README.md` (your status row)

**Out of scope** (do NOT touch, even though they look related):

- `src/pypts/core/core.py` — the routing of `ReportGenerated`/`ReportReady` is
  correct; the bug is entirely inside the Report's state handling.
- `src/pypts/utilities/error_handling.py` — the swallow-and-report behavior of
  `@catch_and_report_errors()` is a deliberate design (roadmap §1.10); do not
  change it to "fix" this bug.
- The CSV column set (`CSV_COLUMNS`) and the HTML layout — unchanged.
- `src/pypts/old_code/` — frozen legacy, never modified.

## Git workflow

- Branch off `architecture_refactor`: `advisor/001-report-run-state` (or commit
  directly to `architecture_refactor` if the operator prefers — their call).
- Commit style in this repo is a short lowercase summary line (see `git log
  --oneline`: "added reporting !", "review continues"). One commit is enough.
- Do NOT push or open an MR unless the operator instructed it.

## Steps

### Step 1: Reset run state before attempting the run folder

In `src/pypts/report/report.py`, rewrite the top of `start_run()` so every
piece of per-run state is cleared **before** `make_run_dir()` can raise. Target
shape:

```python
@catch_and_report_errors()
def start_run(self, event: RunStarted) -> None:
    """Open this run's folder and its CSV, header written and flushed."""
    # Clear the previous run's state first: if make_run_dir() raises below,
    # the decorator swallows it, and stale state would silently attribute
    # this run's verdict and HTML to the previous run's folder.
    self.close_csv()
    self.run_dir = None
    self.run_info = None
    self.run_result = None
    self.rows = []
    self.current_sequence = ""

    self.run_dir = self.make_run_dir(event.recipe_name)
    self.run_info = event

    csv_path = self.run_dir / "report.csv"
    ...  # rest unchanged
```

Keep the existing `# noqa: SIM115` comment on the `open()` line. Also apply the
I001 autofix to this file's import block (see the ruff note above).

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_report.py -q`
→ all existing tests still pass.

### Step 2: Harden `make_run_dir` against pathological recipe names

Still in `report.py`, change `make_run_dir()` so that:

1. `safe_name` is truncated to at most 60 characters after the
   character-replacement pass (keeps the full folder path far from the
   Windows ~260-char limit for any realistic `reports_dir`).
2. An empty result (recipe name was empty or all non-alphanumeric characters
   that produced only underscores is fine — only guard the fully-empty case)
   falls back to the literal `"recipe"`.

Target shape for the first lines:

```python
safe_name = "".join(c if c.isalnum() else "_" for c in recipe_name)[:60]
if not safe_name:
    safe_name = "recipe"
```

Do not change the timestamp format or the collision-suffix loop.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_report.py -q`
→ all pass.

### Step 3: Add the regression tests

In `tests/unit_tests/test_report.py`, using the existing helpers
(`build_report`, `drive`, `sent_to_core`, `a_step_executed`, `csv_rows`) and
the existing test style (plain functions, `tmp_path`), add:

1. `test_a_failed_run_dir_does_not_resurrect_the_previous_run(tmp_path, monkeypatch)`
   — the regression test for the core bug:
   - Run a full first run: `drive(report, A_RUN, a_step_executed(), RunFinished(...), GenerateReport())`
     (copy the message construction from the existing tests in this file).
     Record the first run's `report.run_dir` and the mtime/content of its
     `report.html`.
   - Monkeypatch `report.make_run_dir` (instance attribute) to raise
     `OSError("disk says no")`.
   - Drive a second `RunStarted`, one `StepExecuted`, a `RunFinished` and a
     `GenerateReport`.
   - Assert: `report.run_dir is None`; the first run's `report.html` content
     is **unchanged**; no `ReportGenerated` message for the second run appears
     in `sent_to_core(report)` after the failure (a `ModuleError` from the
     decorator is expected and fine — filter by type).
2. `test_run_dir_name_is_capped_and_never_empty(tmp_path)` — parametrize (or
   loop over) recipe names `""`, `"!!!"`, `"x" * 250`, `"Wärme Prüfung"`:
   drive a `RunStarted(recipe_name=...)` and assert a run folder was created
   under `tmp_path`, its name is at most `len("YYYYMMDD_HHMMSS_") + 60`
   characters, and `report.csv` exists inside it. (Note: `"ä".isalnum()` is
   True in Python — non-ASCII letters pass through; that is accepted, the
   assertion is only on length and existence.)
3. `test_stop_closes_the_csv_and_answers_report_stopped(tmp_path)` — drive a
   `RunStarted` then a `StopReport` message; assert `report.csv_file is None`,
   `report.running is False`, and the last message in `sent_to_core(report)`
   is a `ReportStopped`. (`StopReport` and `ReportStopped` are imported from
   `pypts.messages.core_report_communication`.)

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_report.py -q`
→ all pass, including 3 new tests.

### Step 4: Record it in the roadmap

`CLAUDE.md` requires status updates in the same change. In
`resources/roadmap/pypts_roadmap.md`, section **§1.19** ("The Report is real"),
append one TODO-list entry at the end of its "New TODOs this opened" list:

```
- [x] **DONE (plans/001):** `start_run()` resets the run state *before*
      creating the run folder, so a failed `make_run_dir` (long name, unwritable
      directory) leaves the Report in the "no run open" state instead of
      silently rewriting the previous run's report.html; run-folder names are
      capped at 60 chars and never empty.
```

**Verify**: `git diff --stat` → exactly the four in-scope files modified.

## Test plan

Covered by Step 3. Pattern to follow: the existing tests at the top of
`tests/unit_tests/test_report.py` (message in via `drive()`, assertions on disk
and on `sent_to_core()`). No new fixtures needed.

## Done criteria

ALL must hold:

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` exits 0 (pass count grows
      by 3; skips stay at 45)
- [ ] `.venv\Scripts\python.exe -m ruff check src tests` reports no findings in
      `src/pypts/report/report.py` and no new findings elsewhere
- [ ] `.venv\Scripts\python.exe -m mypy` → `Success: no issues found`
- [ ] In `start_run()`, no read of `event` and no assignment of
      `self.run_info` happens before the state-clearing block
- [ ] `git status` shows only the four in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `start_run()` / `make_run_dir()` code does not match the excerpts above
  (drift since `800db1c`).
- An existing test in `test_report.py` fails after Step 1 for a reason you
  cannot trace to the reordering (it would mean something depends on the stale
  state — that dependency must be understood, not patched around).
- The fix appears to require changing `catch_and_report_errors` or
  `core.py` — both are out of scope by design.

## Maintenance notes

- Plan 002 changes *when* the Report is told to stop during shutdown; it does
  not touch `start_run()`. The two plans are independent.
- The roadmap (§1.19 TODO) plans a `serial_number` column and TDMS work for the
  Report later; both will edit `start_run`'s vicinity — the "clear state first"
  invariant established here must survive those edits. A reviewer should check
  exactly that in any future Report MR.
- Deliberately deferred: `exist_ok`/TOCTOU tightening of the collision-suffix
  loop (two Reports never run concurrently in one process today), and any retry
  or fallback-directory behavior on mkdir failure (policy, not mechanism).
