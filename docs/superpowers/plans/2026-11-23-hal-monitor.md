<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL monitor — a small standalone status window — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.
> Steps use checkbox (`- [ ]`) syntax. **Never `git add`, `git mv`, `git commit`, `git stash`,
> `git checkout`, `git reset`** — the user commits everything himself. **Never `ruff format`.**

**Goal:** a small PySide6 window that shows a running HAL server's status, refreshes on its own,
and can close all devices, stop the HAL, start one, and show the HAL's latest log lines.

**Architecture:** `pyhal.monitor`, a subpackage of `pyhal` that only the monitor imports (it
imports PySide6; `import pyhal` must stay import-light and never import it). A `MonitorLink`
(no Qt) talks to the HAL over connections of its own that **never send a parting request**, so
closing the window never touches the bench (D36). The window polls `status` on a timer through
the link on a worker thread, never on the GUI thread. `run_hal_monitor.py` in the repo root
starts it with PyPTS's `bench.ini` for the Start button, like `run_hal.py`.

**Tech Stack:** Python ≥ 3.11, PySide6 (already a `pts-framework` dependency), pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-04-hal-server-design.md` rev 5 — §7.3 (`status` is
answered by the connection thread, never queued), §8 (what the panel shows), D8, D49 (Close all
devices, Stop HAL). User decisions 2026-11-23: a **standalone** window now (View → HAL in PyPTS
later may open the same window); **PySide6**; first version has auto refresh, Close all + Stop,
Start HAL, a log view.

## Global Constraints

- `pyhal` never imports `pypts` (quality test). `pyhal/monitor/` may import PySide6; nothing
  outside `pyhal/monitor/` imports it, and `import pyhal; from pyhal import PSU` still imports
  neither `socket`, `pyhal.client` nor `PySide6` (existing test `test_import_pyhal_stays_light`).
- The monitor never sends `close_all` or `shutdown` except when its user presses a button and
  confirms; closing the window, a failed poll or an exit sends nothing.
- No socket call on the GUI thread. Every network action runs on a worker (`QThreadPool` /
  `QRunnable` or a `threading.Thread`) and reports back through a Qt signal.
- Refresh every `REFRESH_S = 1.0` s; a poll that has not answered in `POLL_TIMEOUT_S = 2.0` s
  shows the HAL as not reachable. The HAL drops a silent client after 5 s, so a persistent
  connection polling every second never needs a beat.
- Plain old-school Python (CLAUDE.md); `%`-style logging; line length 100; ruff + mypy clean.
- Default port `pyhal.client.DEFAULT_PORT` (29555); `--port` overrides.

## Review Focus

1. The HAL goes away and comes back: the window shows "not reachable" within one poll timeout
   and picks the new HAL up on its own (Task 1 test `test_the_link_reconnects_to_a_new_hal`).
2. Closing the window while a HAL runs with open devices: the devices stay open (Task 2 test
   `test_closing_the_window_leaves_the_bench_alone`).
3. Close all / Stop pressed while a long device call runs: the GUI stays responsive (actions on a
   worker), and the result is shown when the HAL answers (Task 2 test
   `test_actions_do_not_block_the_gui`).
4. A log file that rotates (a new HAL start): the log view follows the new `hello.log`.
5. Start pressed with no bench file given: the button is disabled, with a tooltip saying why.

---

### Task 1: The link — status, actions, start, log (no Qt)

**Files:**
- Create: `src/pyhal/monitor/__init__.py` (docstring only: what the package is, that it imports
  PySide6 and is not imported by `pyhal`), `src/pyhal/monitor/link.py`
- Modify: `src/pyhal/client.py` — make the start of a detached HAL a public function the link
  can call: `start_hal(bench: str | os.PathLike[str], port: int = DEFAULT_PORT, *, log_level:
  int | None = None, log_dir: str | None = None) -> int` (the started process's pid; starts and
  returns as soon as the HAL answers `hello` with its nonce, or raises `DriverError` with the
  startup-file tail — today's `_start_hal` logic, without making a `HalClient`). `_start_hal`
  uses it; behaviour of `connect()` unchanged.
- Test: `tests/unit_tests/test_pyhal_monitor_link.py` (a `HalServer` in a thread on a free port,
  as `test_pyhal_server.py` does), and one functional test for `start_hal` in
  `tests/functional_tests/test_pyhal_standalone.py`.

**Interfaces:**
- Produces `pyhal.monitor.link.MonitorLink(port: int = DEFAULT_PORT)` — thread-safe (one lock):
  - `status() -> messages.StatusReport | None` — on one persistent connection of its own,
    opened on first use and reopened after any failure (connect, read `hello`, send `Status`,
    read the answer, each bounded by `POLL_TIMEOUT_S`); None when no HAL answers. Remembers the
    last `hello` as `hello: messages.Hello | None`.
  - `close_all() -> list[str]` — on a short connection of its own: hello, `CloseAll`, wait for
    `ClosedAll` (no deadline: a close ladder can take ~50 s per device; it runs on a worker),
    return `not_torn_down`. Raises `DriverError` when no HAL answers or it refuses.
  - `stop() -> list[str]` — `CloseAll` then `Shutdown` on one short connection (as `python -m
    pyhal --stop`), returns the names not torn down.
  - `start(bench: str, log_dir: str | None = None) -> int` — `client.start_hal(bench, port,
    log_dir=log_dir)`; refuses with `DriverError("A HAL server already answers on port N.")`
    when one answers.
  - `close() -> None` — closes the persistent connection without sending anything.
  - `log_tail(sink: Callable[[int, str], None]) -> client.LogTail | None` — a `LogTail` on the
    last `hello.log`, or None before any hello.
- [ ] **Step 1: Failing tests:** `test_status_reports_the_hal_and_its_devices` (fields as the
  server sends them; a device opened by another client shows state "open");
  `test_status_is_none_when_no_hal_answers`; `test_the_link_reconnects_to_a_new_hal` (stop server
  A, start B on the same port → `status()` returns B's pid); `test_close_all_returns_what_was_not_torn_down`;
  `test_stop_ends_the_hal`; `test_closing_the_link_sends_nothing` (an open MarkingDriver stays
  open: its marks file has no `teardown` after `close()`); `test_start_refuses_when_a_hal_answers`;
  functional `test_start_hal_starts_a_detached_hal_and_returns_its_pid`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS, plus
  `tests/unit_tests/test_pyhal_client.py` and `tests/functional_tests/test_pyhal_standalone.py`
  (the `_start_hal` refactor) and `tests/quality_tests`.

### Task 2: The window

**Files:**
- Create: `src/pyhal/monitor/window.py` (`MonitorWindow(QMainWindow)`), `src/pyhal/monitor/__main__.py`
  (`python -m pyhal.monitor [--port N] [--bench FILE] [--log-dir DIR]`), `run_hal_monitor.py` in
  the repo root (puts `src` on the path; without `--bench` passes PyPTS's `bench.ini` the way
  `run_hal.py` does — reuse `run_hal.arguments_with_the_bench` or the same `bench_config()` call;
  an unusable bench only disables Start, it does not stop the monitor).
- Modify: `pyproject.toml` `[tool.mypy]` only if needed to keep PySide6 stubs quiet for the new
  files (follow how `src/pypts/hmi` is handled).
- Test: `tests/unit_tests/test_pyhal_monitor_window.py` (pytest-qt, `qtbot`; a `HalServer` in a
  thread on a free port; offscreen platform as the conftest sets).

**Interfaces:** consumes `MonitorLink` (Task 1).

The window, plain and developer-facing, title `HAL monitor — 127.0.0.1:<port>`:
- **Header:** state as a coloured word — `running` (green), `not reachable` (grey), `busy`
  (amber while a request runs); then pid, version, bench file, log file, clients connected,
  "running <operation> on <device> since <time>" or "idle", queued requests, last refresh time.
- **Devices table:** one row per bench device — name, device type, state (configured / open /
  failed, failed in red), last error (tooltip with the full text).
- **Buttons:** *Close all devices* and *Stop HAL* (each with a confirmation dialog naming what
  will happen — "Every open device is torn down, also those of other clients."), *Start HAL*
  (enabled only when no HAL answers and a bench file is known; tooltip names the bench, or says
  "No bench file: start the monitor with --bench FILE"). While an action runs its button is
  disabled and the status line says so; its result (devices not torn down, or the error) is shown
  in the status bar and, when something was not torn down, in a warning dialog.
- **Log view:** a read-only text area with the HAL log's latest records (`LogTail` on the
  `hello.log`, re-created when the HAL's pid changes), at most `LOG_VIEW_MAX_LINES = 500` lines,
  each `HH:MM:SS LEVEL message`, WARNING amber, ERROR red; a level filter (DEBUG / INFO /
  WARNING) — default INFO.
- **Timer:** `REFRESH_S`; a refresh that is still running is not started twice.
- Closing the window stops the timer, the log tail and the link — and sends nothing to the HAL.

- [ ] **Step 1: Failing tests:** `test_the_window_shows_the_hal_and_its_devices`;
  `test_the_window_shows_not_reachable_and_offers_start`; `test_closing_the_window_leaves_the_bench_alone`;
  `test_close_all_asks_first_and_shows_the_result` (monkeypatch the confirmation to Yes);
  `test_actions_do_not_block_the_gui` (a `sleep 2` call running; press Close all; the event loop
  keeps turning — e.g. a `QTimer` tick counted during the wait); `test_start_is_disabled_without_a_bench`;
  `test_the_log_view_shows_new_records_and_filters_by_level`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; quality tests PASS.
- [ ] **Step 5: By hand:** `python run_hal_monitor.py` with no HAL running → "not reachable",
  Start works, devices appear; open a device from a script → its row shows "open"; Close all →
  it shows "configured". Record what was seen in the report (screenshots not needed).

### Task 3: Documents

- `src/pyhal/pyhal.md`: a section *The monitor* (what it shows, the buttons, that it never sends
  a parting request, `python -m pyhal.monitor`, `run_hal_monitor.py`), the *Files* rows, the
  import-lightness note (PySide6 only in `pyhal.monitor`).
- `docs/Usage_manuals/usage_manual.html`: the monitor in the HAL passage.
- `CLAUDE.md`: the *Running* block gets `python run_hal_monitor.py`.
- Spec rev 5 §8: one paragraph — a standalone monitor exists (user decision 2026-11-23); View →
  HAL in phase 4 may open it rather than build its own panel.
- `docs/Usage_manuals/pypts_implementation_status.html`: entry 1.100.
- [ ] **Step:** `pytest tests` → PASS (full suite).
