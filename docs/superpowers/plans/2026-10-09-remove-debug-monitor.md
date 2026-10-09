# Remove the Debug Monitor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the Debug Monitor helper application (`pypts.helper_applications.debug_monitor`) and every hook the framework has into it — CLI flag, API parameter, launcher process handling, comments and documentation — leaving the framework's run behaviour otherwise unchanged.

**Architecture:** The Monitor is a separate program the launcher spawns with `subprocess.Popen([... "-m", DEBUG_MONITOR_MODULE, log])`; nothing in the framework imports it. Removal is therefore: cut the launcher's spawn + flag + `Engine.monitor_process`, cut the `debug_monitor` parameter threaded through `start_engine()` / `Pts` / `open_gui()` / `headless_main()`, delete the package and its tests, then clean comments and docs that justify things "for the Monitor".

**Tech Stack:** Python 3.11, argparse, pytest, ruff, mypy.

**Spec:** this conversation, 2026-10-09. Decisions taken by the user:
1. `--debug-monitor` / `--no-debug-monitor` — **removed entirely** (an old script passing it gets a usage error).
2. `debug_monitor=` parameter on `start_engine`, `Pts`/`HeadlessPts`, `open_gui`, `headless_main` — **removed**.
3. CORE's "machine-read" heartbeat DEBUG lines — **lines kept unchanged**, only the comments/docs saying the Monitor parses them are removed.
4. `pypts_implementation_status.html` §1.4 / §1.4.1 — **condensed into one short "removed" entry**.

## Global Constraints

- **No commits, no staging.** The user commits everything themselves (memory: feedback-no-commits). Skip any commit step.
- Never `git checkout` a file to undo an experiment.
- Logging stays `%`-style; INFO+ for the technician, DEBUG for developers (`logger/logging_rules.md`).
- Do **not** change `[logging] level = DEBUG` default in `configuration_schema.py` / `config_template.ini` — that is a separate roadmap item (§1.6). Only its comment changes.
- Do **not** change `CONFIG_VERSION`.
- Do **not** edit historical records: `docs/superpowers/plans/2026-10-07-*.md`, `resources/internal_reports/*.html`. They describe the past.
- Documentation moves with the code in the same change (CLAUDE.md rule). Delete what is no longer true; no stale sentence beside a corrected one.
- Quality gates: `pytest tests`, `ruff check src tests`, `mypy`, plus a documentation re-read.

## Review Focus

1. **Old flag on the command line** — `python -m pypts --no-debug-monitor` must exit with `USAGE_EXIT_CODE` (3), not crash with a traceback. Pinned by a test in Task 1.
2. **Restart after "Restore default settings"** — `restart_pypts()` re-runs `sys.orig_argv`; the restart test must still pass with the monitor flag gone from its fixture argv. Pinned in Task 1.
3. **Headless hand-over** — `headless_main` is called with 3 positional args now; the fake in `test_headless.py` must match the new signature or the test silently passes for the wrong reason. Pinned in Task 1.
4. **Unused imports after the cut** — `subprocess` is still used by `restart_pypts()`; `time` and `Path` in `startup.py` may become unused. Ruff (`F401`) catches it; check, don't guess.
5. **Stale cross-references** — any document still naming `debug_monitor/`, `MONITOR_LOG_WAIT_S`, `start_debug_monitor` or `--debug-monitor`. Task 4 ends with a grep that must return only the historical files.

---

### Task 1: Cut the launcher wiring, CLI flag and API parameter

**Files:**
- Modify: `src/pypts/launcher/startup.py` (module docstring lines 25-36; constants lines 75-86; `Engine.monitor_process` line 115; argparse block lines 157-170; resolution lines 180-184; `headless_main(...)` call line 191; comment lines 196-199; `start_engine(...)` call line 217; `restart_pypts` docstring line 247-248; `start_engine` signature/docstring lines 282-294; spawn lines 391-394; `stop_engine` lines 461-468; whole `start_debug_monitor()` lines 536-581)
- Modify: `src/pypts/api/embedding.py` (`Pts.__init__` lines 372-380; `open_gui` lines 464 and 503)
- Modify: `src/pypts/api/headless.py` (lines 56-76)
- Test: `tests/unit_tests/test_startup.py`, `tests/unit_tests/test_headless.py`

**Interfaces:**
- Produces: `start_engine(mode: str, log_level_name: str | None = None) -> Engine`; `headless_main(recipe: str, sequence: str | None = None, log_level: str | None = None) -> int`; `Pts.__init__(self, log_level: str | None = None)`; `open_gui(recipe=None, *, start=False, sequence=None, log_level=None)`. `Engine` no longer has `monitor_process`.

- [ ] **Step 1: Update the tests to the new shape**

`tests/unit_tests/test_startup.py`, in `a_main_that_runs_nothing()`:

```python
    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", "pypts", "--mode", "gui"])
    monkeypatch.setattr(startup, "start_engine", lambda mode, level: "engine")
```

and in `test_main_restarts_pypts_with_the_same_command_line_once_it_has_stopped`:

```python
    assert calls == ["stopped", [sys.executable, "-m", "pypts", "--mode", "gui"]]
```

Delete `test_start_debug_monitor_gives_up_when_the_log_never_appears` entirely (lines 285-310).

`tests/unit_tests/test_headless.py`, replace `test_headless_mode_hands_over_to_headless_main` with:

```python
def test_headless_mode_hands_over_to_headless_main(monkeypatch):
    calls = []

    def fake_headless_main(recipe, sequence, log_level):
        calls.append((recipe, sequence, log_level))
        return 1

    monkeypatch.setattr(headless, "headless_main", fake_headless_main)

    code = run_main(
        monkeypatch, "--mode", "headless", "--recipe", "b.yml", "--sequence", "Cal",
        "--log-level", "INFO",
    )

    assert code == 1
    assert calls == [("b.yml", "Cal", "INFO")]


@pytest.mark.parametrize("flag", ["--debug-monitor", "--no-debug-monitor"])
def test_the_removed_debug_monitor_flag_is_a_usage_error(monkeypatch, flag):
    assert run_main(monkeypatch, "--mode", "headless", "--recipe", "b.yml", flag) == 3
```

(`run_main` returns `SystemExit.code`; argparse rejections exit `USAGE_EXIT_CODE` = 3, as `test_an_unknown_option_exits_three` already pins.)

- [ ] **Step 2: Run them, expect failures**

Run: `pytest tests/unit_tests/test_startup.py tests/unit_tests/test_headless.py -v`
Expected: the hand-over test FAILS (`headless_main` still called with 4 args → `TypeError`), the new flag test FAILS (flag still accepted), the restart test FAILS (`start_engine` lambda gets 3 args).

- [ ] **Step 3: Cut `startup.py`**

1. Module docstring: delete the two paragraphs at lines 25-36 ("The Debug Monitor is started beside the run…" and "It is the one thing the launcher starts…").
2. Delete `DEBUG_MONITOR_MODULE`, `MONITOR_LOG_WAIT_S`, `MONITOR_LOG_POLL_S` with their `#:` comments (lines 75-86).
3. `Engine`: delete `monitor_process: subprocess.Popen | None = None`.
4. Delete the `parser.add_argument("--debug-monitor", ...)` block.
5. Delete the `# None means the flag was not given…` block and the `debug_monitor = …` resolution.
6. `sys.exit(headless_main(args.recipe, args.sequence, args.log_level))`.
7. In the PySide6 comment, replace the last two sentences ("That bench is exactly what --no-debug-monitor exists for, so it has to be able to run.") with: `A CLI run on such a bench has to be able to start.`
8. `engine = start_engine(args.mode, args.log_level)`.
9. `restart_pypts` docstring: "…so config.ini is recreated from the template by the bootstrap that already does it, and a new run log comes with it."
10. `start_engine` signature → `def start_engine(mode: str, log_level_name: str | None = None) -> Engine:` and delete the `debug_monitor:` Args line.
11. Delete the spawn block (the two `# Debug monitor is…` comment lines and `if debug_monitor: engine.monitor_process = …`).
12. `stop_engine`: delete the two comment lines and the `monitor_process = …` / `if …: log.debug("Debug Monitor (pid %d) left running…")` block.
13. Delete the whole `start_debug_monitor()` function.
14. Run `ruff check src/pypts/launcher/startup.py`; remove whatever imports it reports unused (`time` is expected; `subprocess` stays for `restart_pypts`; check `Path`).

- [ ] **Step 4: Cut the API**

`src/pypts/api/embedding.py`:

```python
    def __init__(self, log_level: str | None = None) -> None:
        """
        Args:
            log_level: "DEBUG", "INFO", ... - overrides [logging] level in config.ini.
        """
        self._saved_logging = _save_root_logging()
        try:
            self._engine = startup.start_engine(self.MODE, log_level)
```

In `open_gui`: delete the `debug_monitor: bool = False,` parameter and change the call to `engine = startup.start_engine("gui", log_level)`.

`src/pypts/api/headless.py`:

```python
def headless_main(
    recipe: str, sequence: str | None = None, log_level: str | None = None
) -> int:
    """
    Run one sequence of one recipe and return the process exit code.

    Args:
        recipe: path to the recipe file.
        sequence: which sequence; None runs the recipe's main sequence.
        log_level: overrides [logging] level in config.ini, as --log-level.
    """
```

and `pts = HeadlessPts(log_level=log_level)`.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/unit_tests/test_startup.py tests/unit_tests/test_headless.py tests/unit_tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Grep for leftovers in code**

Run: `grep -rn "debug_monitor\|monitor_process\|MONITOR_LOG" src tests --include=*.py | grep -v helper_applications/debug_monitor/ | grep -v test_debug_monitor.py`
Expected: no output.

---

### Task 2: Delete the package, its tests and its lint exemptions

**Files:**
- Delete: `src/pypts/helper_applications/debug_monitor/` (whole directory incl. `__pycache__`: `__init__.py`, `__main__.py`, `liveness.py`, `log_source.py`, `main_window.py`, `trace_model.py`, `trace_parser.py`)
- Delete: `tests/unit_tests/test_debug_monitor.py`
- Modify: `pyproject.toml` lines 157-164

- [ ] **Step 1: Confirm nothing outside imports it**

Run: `grep -rn "helper_applications.debug_monitor\|helper_applications import debug_monitor" src tests run_*.py`
Expected: matches only inside the package and its test (Task 1 already removed the launcher's string).

- [ ] **Step 2: Delete**

```bash
rm -rf src/pypts/helper_applications/debug_monitor
rm tests/unit_tests/test_debug_monitor.py
```

- [ ] **Step 3: `pyproject.toml`** — delete the `"…/debug_monitor/trace_model.py"`, `"…/debug_monitor/main_window.py"` N802 lines **and** their `# Qt overrides camelCase virtuals…` comment if no other entry sits under it; delete the `test_debug_monitor.py` and `debug_monitor/trace_parser.py` E501 lines **and** their `# Sample log records…` comment if nothing else sits under it. Check the surrounding lines before deleting a comment.

- [ ] **Step 4: Verify**

Run: `pytest tests -q` → all pass (count drops by the ~32 Monitor tests). `ruff check src tests` → clean. `mypy` → clean.

---

### Task 3: Remove Monitor justifications from comments and docstrings

No behaviour change. Each edit rewrites the sentence so it stays true without the Monitor; never leave a dangling "see liveness.py".

**Files:**
- `src/pypts/core/core.py:749` — `# The Monitor's other machine-read line - see do_periodic_tasks().` → delete the comment (the DEBUG line stays).
- `src/pypts/core/core.py:814-817` — replace the four-line "Machine-read: the Debug Monitor's liveness tab…" comment with: `# The mechanism, for the developer: which module, on its own line, with the measurements below it.`
- `src/pypts/core/core.py:893-896` — replace "Machine-read, and shaped the way the timeout line above is shaped: … See helper_applications/debug_monitor/liveness.py." with: `# Shaped like the timeout line above: the prefix and the module name, measurements below.`
- `src/pypts/utilities/heartbeat_manager.py:18-21` — delete the paragraph "This module imports almost nothing on purpose. The Debug Monitor needs…". (Keeping the module light is harmless; the reason no longer exists.)
- `src/pypts/utilities/local_storage.py:46-48` — "the Logger writes local time with no offset, so a UTC file name would be the one timestamp in the system that did not match the others."
- `src/pypts/config_handler/configuration_schema.py:100-102` — "# DEBUG for the duration of the refactor, so every run carries the message trace. This reverts to INFO before v1.0 - see the TODO in the roadmap."
- `src/pypts/hmi/gui/gui.py:103-105` — "#: What Edit > Edit Recipe starts, spelled as `-m` takes it. A string rather than an import: the operator screen must not import the helper applications."
- `src/pypts/hmi/gui/gui.py:1050-1052` — drop ", as the launcher starts the Debug Monitor".
- `src/pypts/hmi/gui/log_tail.py:24-26` — "…every message twice, sent and received. The operator panel filters to `PANEL_LOG_LEVEL` and up." Line ~56: replace "they are what the Debug Monitor is for" with "they are developer detail, read in the log file".
- `src/pypts/sequencer/sequencer.py:323-324` — "…own timestamp, and the GUI's log panel does not have to treat the second and third as continuations of a traceback."
- `tests/unit_tests/test_core.py:55-56` — "The operator's sentence and the developer's DEBUG line are both written once per outage."
- `tests/unit_tests/test_hmi_gui.py:911` — "# Developer detail stays out of the operator's panel."
- `tests/unit_tests/test_console_output.py:21-22` — "Qt widget text is deliberately not checked - window titles and column placeholders may carry em-dashes and arrows, they never touch a byte stream, …". The planted sample string at line 137 can stay (it is just test data) — optionally rename to `"Window — not checked, never printed"`.

- [ ] **Step 1:** Make the edits above (read each surrounding block first; fit the wording to it).
- [ ] **Step 2:** Run `grep -rniE "debug.?monitor|\bMonitor\b" src tests run_pypts.py` → expected: no output.
- [ ] **Step 3:** `pytest tests -q`, `ruff check src tests`, `mypy` → clean.

---

### Task 4: Documentation

**Files:**
- `CLAUDE.md` — line 102: `helper_applications/  recipe_creator (incl. verificator), example_finder`; delete lines 129-130 (`--no-debug-monitor` and `python -m pypts.helper_applications.debug_monitor` run examples); delete line 134 ("Nothing in the framework may import `helper_applications/debug_monitor/`.").
- `README.md` lines 28-30, 43 — drop "plus the Debug Monitor" and the `--no-debug-monitor` line and the sentence at 43.
- `run_pypts.py:12` — `python run_pypts.py --log-level DEBUG`.
- `usage_manual.html` — delete the note at lines 99-100; delete the `--no-debug-monitor` / `--debug-monitor` options row (131-132); fix the sentence at 252; delete the "Debug Monitor" helper-tool row (365-366) and the "Debug Monitor is empty" troubleshooting row (381).
- `docs/source/troubleshooting.rst:13` — delete the "Debug Monitor is empty" bullet.
- `src/pypts/launcher/launcher.md` — delete the **Debug Monitor** bullet (22-24); `start_engine(mode, log_level_name)` in the table (35); delete the `MONITOR_LOG_WAIT_S` row (57); delete the "Never import debug_monitor" rule (62); remove `--debug-monitor/--no-debug-monitor` from the options list and the default sentence (67-70); line 88 → drop "a Debug Monitor opens again on the new run log; the old window stays open".
- `src/pypts/api/api.md` — line 39 `Pts(log_level=None)`; delete line 101; check the `open_gui` / `headless_main` signatures in the file and remove `debug_monitor` there too.
- `src/pypts/core/core.md:59` — remove the "Debug Monitor (`…/liveness.py`) — keep their prefix and…" constraint; keep a plain description of the DEBUG heartbeat lines if the surrounding text needs it.
- `src/pypts/hmi/gui/gui.md:478-491` — remove the Monitor sentences and the "Nothing here imports debug_monitor" bullet.
- `src/pypts/logger/logging_rules.md` lines 83, 187, 291 — remove "the Debug Monitor's parser and"; "neither `log_tail` nor the Debug Monitor" → "`log_tail` does not"; rewrite 291 without the Monitor.
- `src/pypts/utilities/utilities.md` lines 82, 95, 99, 135 — remove each Monitor rationale (heartbeat constants, local time, log discovery naming).
- `pypts_implementation_status.html`:
  - Replace everything from the `<h3 id="1-4-debug-monitor…">` (line 258) up to, not including, the `<h3 id="1-5-…">` (line 300) with:

    ```html
    <h3 id="1-4-debug-monitor-removed">1.4 Debug Monitor — <strong>removed</strong> (2026-10-09)</h3>
    <blockquote><p><strong>Status: removed.</strong> A developer-only helper application (<code>pypts.helper_applications.debug_monitor</code>) that read the run log and showed the message trace and module liveness; the launcher started it beside every gui/cli run (<code>--debug-monitor</code>, on by default during the refactor). Removed once the messaging was stable: the package, its tests, the launcher flag and the <code>debug_monitor</code> parameter of <code>start_engine()</code>, <code>Pts</code>, <code>open_gui()</code> and <code>headless_main()</code> are gone. The message trace itself is unchanged and still read directly from the run log at DEBUG. Design history: git, and <code>resources/internal_reports/architecture_refactor_summary.html</code>.</p></blockquote>
    <hr>
    ```
  - Line 210-211 (the §1.4 DONE item): append "<em>Removed 2026-10-09 — see §1.4.</em>".
  - Line 316 (§1.6): drop ", and the Debug Monitor (§1.4) always has something to read"; line 320: "produces a log carrying the trace across all seven links."
  - Lines 336-337, 573, 943: reword or drop each Monitor mention (943 references §1.4.1 for "spawn is pinned" — point it at the launcher instead: "(`pin_spawn_start_method()`)").
  - Add a dated changelog/progress entry in the file's usual place recording the removal and the test count from Task 5.
- `TODO.txt` — if the user's inbox has an item for this, mark it `[x]` with a note; never delete.

- [ ] **Step 1:** Make the edits.
- [ ] **Step 2:** `grep -rniE "debug.?monitor|start_debug_monitor|MONITOR_LOG" --include=*.md --include=*.html --include=*.rst --include=*.py --include=*.txt --include=*.toml .`
  Expected: only `docs/superpowers/plans/2026-10-07-*.md`, `resources/internal_reports/*.html`, this plan, and the deliberate "removed" entry in `pypts_implementation_status.html`.

---

### Task 5: Quality gates and report

- [ ] `pytest tests` — all pass; note the new pass/skip counts.
- [ ] `ruff check src tests` — clean.
- [ ] `mypy` — clean.
- [ ] Manual smoke: `python -m pypts --mode cli` starts with one window/console and no Monitor; `python -m pypts --no-debug-monitor` exits 3 with argparse's message.
- [ ] Documentation check: re-read every file touched in Task 4 against the final code. Report which were updated, and any drift found but not fixed.
- [ ] Do **not** commit — hand over to the user.
