# Run Log in the Report Folder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One folder setting. The session log lives in `reports_dir`; every run's lines are logged into that run's own report folder; the run folder is no longer renamed.

**Architecture:** The Sequencer (Core process, the thread that produces a run's lines) creates the run folder and asks the Logger to start a *run log* in it **before** it sends `RunStarted`, and to end it **before** it sends `RunFinished`. The Logger remembers which file it was writing when the run log started and returns to it (appending) when it ends — so the session log is right even after a GUI unload switched it. `RunStarted` carries the folder and the run log path, so the Report writes into the same folder and the GUI's log panel follows the run log without clearing.

**Tech Stack:** Python 3.11 logging, multiprocessing queues, PySide6, pytest.

**Spec:** this conversation, 2026-10-09. Decisions taken by the user:
1. Merge `paths.logs_dir` into `paths.reports_dir`; the run log goes **inside each run folder**; startup/idle lines go to a session log in the reports root.
2. Old `logs_dir = …` lines in existing config.ini: **warn once** (existing unknown-key rule; no special code).
3. **The Sequencer owns** the run folder and the log switch.
4. GUI log panel: **continuous** — no clearing at run start/end.
5. **Stop renaming** the run folder at run end (`rename_run_dir()` is deleted).

Resulting layout:

```
<reports_dir>/
  pypts_20261009_102625.log          session log: startup, load, idle, between runs
  20261009_102700_demo/
    report.csv
    report.html
    pypts_20261009_102700.log        this run's lines only
```

## Global Constraints

- No commits, no staging (user commits).
- `CONFIG_VERSION` unchanged: a key is removed, nothing new is mandatory.
- Everything on HMI↔CORE stays pickle-safe: new `RunStarted` fields are `str`.
- Every handler `match` closed with `unhandled()`; new LoggerControl members go into the union **and** the Logger's `match`.
- Logging `%`-style; INFO for the operator, DEBUG for developers (`logging_rules.md`).
- Documentation moves with the code (CLAUDE.md). Message changes touch `messages/messages.md`; CORE routing is unchanged (RunStarted/RunFinished are already relayed to Report and HMI) but `core/core.md` is re-read.
- Scripted edits keep each file's line endings (repo is `eol=lf`).

## Review Focus

1. **Session log after an unload** — S1 at startup, unload switches to S2 (GUI-decided), then a run: the run's end must return to **S2**, not S1. Pinned by a Logger test (Task 1).
2. **Run folder cannot be created** (read-only reports dir) — the run must still run; log stays in the session log; Report falls back to making its own folder (and warns if that fails too). Pinned in Task 2.
3. **No Logger** (unit tests, standalone) — `start_run_log()` / `end_run_log()` return False and change nothing; the Sequencer still runs. Pinned in Task 1.
4. **GUI panel order across the switch** — pre-switch session lines must appear before run lines, and run lines (incl. the three "Run summary" lines) before post-run session lines. Pinned in Task 4.
5. **Run log file not created yet when RunStarted reaches the GUI** — the Logger creates it asynchronously; the panel waits (bounded, like `_wait_for_new_log`) rather than failing. Pinned in Task 4.

---

### Task 1: Logger — run log start/end

**Files:**
- Modify: `src/pypts/messages/to_logger_communication.py` — add `StartRunLog(log_file_path: str)` and `EndRunLog()`; add both to `LoggerControl`.
- Modify: `src/pypts/logger/log.py` — Logger handles both; module functions `start_run_log(path) -> bool`, `end_run_log() -> bool`.
- Test: `tests/unit_tests/test_logger.py`, `tests/unit_tests/test_messages.py` (union/pickle coverage, if it enumerates LoggerControl).

**Interfaces — Produces:**
- `start_run_log(log_file_path: str) -> bool` — False (no change) when there is no Logger.
- `end_run_log() -> bool` — same.
- Logger: `StartRunLog(path)` → remember `self.log_file_path` as `self.session_log_file_path`, `switch_file(path)`. `EndRunLog()` → if a session path is remembered, `switch_file(session)` and forget it; otherwise ignore (DEBUG-free: Logger diagnostics go through `_report`).

Behaviour notes:
- `switch_file` already opens with `mode="a"`, so returning to the session log appends.
- A `StartRunLog` while a run log is already open (should not happen) keeps the *original* session path, so a second end still returns to the session log.
- The calling process's `_log_file_path` is **not** changed by `start_run_log()` — `get_log_path()` keeps naming the session log, which is what the GUI's unload switch and log panel rely on.

- [ ] Step 1: tests (fail first) in `test_logger.py`, driving a `Logger` the way the existing switch tests do (read them first and mirror their setup):
  - run log receives records sent between `StartRunLog` and `EndRunLog`; the session file gets those before and after, appended (session file holds "before" then "after").
  - after `SwitchLogFile(S2)` then `StartRunLog(R)` / `EndRunLog()`, records after the end land in **S2**.
  - `EndRunLog()` with no run log open writes nothing anywhere new and does not raise.
  - `start_run_log()` / `end_run_log()` return False with no Logger (after `init_logging()` without a queue).
- [ ] Step 2: run → FAIL (ImportError on the new names).
- [ ] Step 3: implement messages + Logger cases + functions.
- [ ] Step 4: `pytest tests/unit_tests/test_logger.py tests/unit_tests/test_messages.py` → PASS.

---

### Task 2: Config, launcher, Sequencer owns the run folder, Report follows it, no rename

**Files:**
- `src/pypts/config_handler/configuration_schema.py` — delete `"logs_dir"`.
- `src/pypts/config_handler/config_handler.py` — drop `logs_dir` from the derived paths; docstring examples `paths.logs_dir` → `paths.reports_dir`. Same in `config_handler/__init__.py`.
- `src/pypts/config_handler/config_template.ini` — delete `logs_dir =`.
- `src/pypts/hmi/gui/settings_dialog.py` — remove `paths.logs_dir` from the Folders group, labels and help.
- `src/pypts/launcher/startup.py` — `get_log_file_path(config.get_parameter("paths.reports_dir"))`.
- `src/pypts/utilities/local_storage.py` — rename parameter `logs_dir` → `folder` (docstring: the reports folder for the session log, a run folder for a run log); add `make_run_folder(reports_dir, recipe_name) -> Path` (moved from `Report.make_run_dir` together with `safe_name_part`, unchanged naming: `<YYYYmmdd_HHMMSS>_<safe recipe name>`, `_2`… on collision, `mkdir(parents=True)`). `report.py` imports both from here.
- `src/pypts/messages/run_events.py` — `RunStarted` gains `run_dir: str = ""` and `run_log_path: str = ""` (empty = not made).
- `src/pypts/sequencer/sequencer.py`:
  - seam `self.reports_dir: Callable[[], str] = reports_dir_from_config` (like `read_hardware_sections`; `reports_dir_from_config` reads `paths.reports_dir`).
  - in `execute_sequence()`, before `RunStarted`: `run_dir = make_run_folder(self.reports_dir(), recipe.name)`; on `OSError` → `report_problem(..., severity WARNING)` "The results folder could not be created …" and continue with `run_dir=""`. If made: `run_log = get_log_file_path(run_dir)`; `log.info("This run is logged in %s", run_log)`; `start_run_log(run_log)`; first line in the run log: `log.info("Run log of recipe '%s', sequence '%s'.", …)`.
  - `RunStarted(..., run_dir=str(run_dir), run_log_path=run_log if started else "")`.
  - at the end: `log_run_summary(...)` **moves before** `RunFinished` (so the summary is in the run log), then `end_run_log()`, then `log.info("The run's log is %s", run_log)` (lands in the session log), then send `RunFinished`.
  - `end_run_log()` also on every early exit after `start_run_log()` (use `try/finally` around the body that follows the start).
- `src/pypts/report/report.py`:
  - `start_run()`: `run_dir = Path(event.run_dir) if event.run_dir else make_run_folder(self.output_dir, event.recipe_name)` (fallback keeps direct-use and tests working, and covers Review Focus 2).
  - delete `rename_run_dir()` and its call in `finish_run()`; delete `make_run_dir()` (moved).
- Tests: `test_config_handler.py` (lines ~107, 154, 162, 706 use `logs_dir` — re-point to `reports_dir` or delete the logs line), `test_settings.py` (~120, 181, 356), `test_utilities.py` (~439 lambda param name), `test_report.py` (rename tests deleted; `make_run_dir` monkeypatch → `make_run_folder`; new test: a `RunStarted` with `run_dir` writes into that folder and creates no other), `test_sequencer.py` (fixture sets `instance.reports_dir = lambda: str(tmp_path)`; new tests: RunStarted carries an existing `run_dir`; a failing folder → WARNING problem and the run still finishes; summary is logged before RunFinished is sent), `test_messages.py` if it builds RunStarted.

- [ ] Step 1: write/adjust the tests above; run → FAIL.
- [ ] Step 2: implement.
- [ ] Step 3: `pytest` on the touched test files → PASS; `ruff`, `mypy`.

---

### Task 3: Frontend hooks

**Files:** `src/pypts/hmi/hmi_client.py`; test `tests/unit_tests/test_hmi_client.py`.

- `case RunStarted(...)`: keep `show_run_started(name, description)`; then, if `message.run_log_path`, call new hook `follow_run_log(path: str)` (default: `log.debug`).
- `case RunFinished(...)`: keep `show_run_finished(...)`; then call new hook `run_log_finished()` (default: nothing).
- [ ] Test: a client subclass records the hook calls for a RunStarted with/without a path and for RunFinished → FAIL → implement → PASS.

---

### Task 4: GUI log panel follows the run log, continuously

**Files:** `src/pypts/hmi/gui/gui.py`; test `tests/unit_tests/test_hmi_gui.py`.

State: `self.log_tail` (session, as today) + `self.run_log_tail: LogTail | None` + `self._run_log_pending: str | None` + `self._run_log_deadline: float | None` + `self._run_log_finished: bool`.

- `follow_run_log(path)`: drain and close any previous run tail; set pending path + deadline (`NEW_LOG_WAIT_S`); `_run_log_finished = False`.
- `run_log_finished()`: `_run_log_finished = True`.
- `poll_log()` each tick:
  1. if pending and the file exists → open it as `run_log_tail` (positioned at start); past the deadline → panel line "Could not open the run log: …" and drop pending.
  2. read order: while the run is going (not finished): **session, then run**; after `run_log_finished`: **run, then session**. (The Logger writes all of one file before the other, so this order is always correct.)
  3. once finished and the session tail returned a line, drain the run tail one last time and close it.
- `start_new_log_file()` (unload) and `stop_log_tail()` also drain/close the run tail.
- [ ] Tests (with real files in tmp_path, appending text to simulate the Logger): lines appear in order session-before → run → session-after; panel is never cleared; a run log that appears 2 ticks late is still followed; one that never appears gives the panel message. FAIL → implement → PASS.

---

### Task 5: Documentation

- `config_handler/config_handler.md` (paths table, derived values), `report/report.md` (folder now from RunStarted, no rename, run log inside), `sequencer/sequencer.md` (owns folder + run log, summary before RunFinished, seam), `logger/logging_rules.md` (session log vs run log; §6 lines), `messages/messages.md` (RunStarted fields; StartRunLog/EndRunLog on the logger link), `hmi/hmi.md` (two hooks), `hmi/gui/gui.md` (panel follows run log), `utilities/utilities.md` (`make_run_folder`, `get_log_file_path(folder)`), `launcher/launcher.md`, `core/core.md` (re-read; relay note if it mentions folders), `usage_manual.html` (where logs and reports go; Settings → Folders), `CLAUDE.md` if it names logs_dir, roadmap: new §1.57 entry + any present-tense "renamed with the serial" claim.
- [ ] Sweep: `grep -rn "logs_dir\|rename_run_dir\|make_run_dir"` outside history → only intended hits.

### Task 6: Gates

- [ ] `ruff check src tests`, `mypy`, `pytest tests` (in chunks if a single run gets killed), and a real headless run: session log in reports root, run log in the run folder holding the run's lines and the three summary lines, session log holding "This run is logged in …" and "The run's log is …".
- [ ] No commit.
