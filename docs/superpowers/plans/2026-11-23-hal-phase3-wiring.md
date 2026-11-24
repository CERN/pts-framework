# HAL server, phase 3 — PyPTS uses the HAL server: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PyPTS reaches its devices through the standalone HAL server instead of in-process, and
the in-process path (`LocalSetup`) is removed.

**Architecture:** A new `core/hal_link.py` in CORE connects to the HAL (or starts it, with or
without its monitor window, per `[hal] show_window`) on a worker thread at startup, re-logs the
HAL's log lines as `HAL: ...`, and runs the close on both of CORE's closes. The Sequencer wraps
each run in `with pyhal.run_scope():` where `LocalSetup` is today. Test code keeps calling
`pyhal.get_device()`. No new HMI↔CORE messages: View → HAL is phase 4.

**Tech Stack:** Python ≥ 3.11, standard library sockets (phase 2's `pyhal.client`), PySide6 for
the monitor, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-04-hal-server-design.md` (rev 5): §6.1-6.4, §9, §10,
§12. Phase 2's plan (`2026-11-23-hal-phase2-server.md`) for what exists already.

## Decisions already taken (2026-11-23)

| # | Decision |
|---|---|
| P1 | New key `[hal] show_window`, bool, **default `true`**, in the Settings dialog. |
| P2 | Every schema key is mandatory, so the new key **raises `CONFIG_VERSION` to `5.0.0`** (old `config.ini` files are discarded with the version notice until updated or recreated). |
| P3 | `show_window = true`: when PyPTS has to start a HAL, it starts the **monitor in serve mode**, which starts the HAL. **PyPTS still counts as its starter** (the start nonce goes through the monitor), so PyPTS's close sends `shutdown`; the window then **closes itself** (`--exit-with-hal`). |
| P4 | `show_window` matters only when PyPTS starts the HAL. A HAL found running is used as it is; no window is opened for it. |
| P5 | Tests run during phase 3 (user allowed it for this work). |

## Global Constraints

- `pyhal` never imports `pypts` (`tests/quality_tests/test_pyhal_independence.py`).
- `import pyhal` stays light (no `socket`, no PySide6): `test_import_pyhal_stays_light`.
- Logging `%`-style; INFO and above for the technician, developer detail at DEBUG
  (`logger/logging_rules.md`; check its fixed lifecycle phrases before adding INFO lines).
- `match`/`case` closed with `unhandled()` wherever a message union is matched.
- A thread entry point never calls `init_logging()`.
- The close is on the closing thread itself, never handed to a worker (spec §6.4 step 4).
- `CORE_SHUTDOWN_TIMEOUT_S` and the `BENCH_MAY_BE_ENERGISED` text stay as they are (§6.4).
- Documentation moves with the code in the same task (CLAUDE.md); no git commit steps (the
  user commits).
- Code style: plain, `if`/`else` over conditional expressions, line length 100, ruff + mypy clean.

## Review Focus

1. **PyPTS closed within seconds of starting, while the HAL is still starting** (up to
   `HAL_START_TIMEOUT_S` = 15 s): the close must not block CORE's event loop past the HMI's
   15 s heartbeat limit. → Task 4 test `test_close_during_the_startup_connect_does_not_block`.
2. **A run started before the startup connect finished** (headless runs start at once): the
   run's first `get_device()` waits for the connect and then works. → Task 1 test
   `test_run_scope_waits_for_a_pending_connect`, Task 5 test.
3. **The HAL is not reachable at all** (start failed, port taken by something else): PyPTS
   starts, the run's `get_device()` fails with the reason, the step is an ERROR, the run
   finishes. → Task 4 `test_a_failed_connect_is_what_get_device_reports`.
4. **The test suite never touches the real HAL port or the real bench**, including engines
   started in spawned processes. → Task 4 `PYPTS_HAL` switch, set in `tests/conftest.py`;
   Task 7 full-suite run checks no `pyhal` process is left (`Get-CimInstance` check).
5. **The window start where the HAL inside it cannot start** (bad bench): PyPTS gives up after
   `HAL_START_TIMEOUT_S` with the startup file's tail; the window stays open showing the failure.
   → Task 2 test `test_connect_with_window_reports_a_failed_start`.

---

### Task 1: The client waits for a pending connect; a reason without a connect

**Files:**
- Modify: `src/pyhal/client.py` (module state beside `_connect_problem`; `connect()`,
  `connect_only()`, `run_scope()`)
- Test: `tests/unit_tests/test_pyhal_client.py`
- Docs: `src/pyhal/pyhal.md` (*The client*)

**Interfaces:**
- Produces:
  - `connect_pending() -> None` — marks that a connect is about to run on another thread
    (spec §6.2 step 8). Called by CORE before it starts its connect thread.
  - `note_unavailable(reason: str) -> None` — no connect will be made; `reason` is what
    `get_device()` raises from now on. Also ends a pending connect.
  - `CONNECT_WAIT_S = HAL_SHUTDOWN_WAIT_S + HAL_START_TIMEOUT_S` — the longest `run_scope()`
    waits for a pending connect.
  - `connect()` and `connect_only()` end a pending connect when they return or raise.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_scope_waits_for_a_pending_connect(start_hal):
    hal = start_hal()            # the existing threaded-server fixture of this file
    client.connect_pending()
    connected = threading.Event()
    def late_connect():
        time.sleep(0.5)
        client.connect_only(hal.port, scope=False)
        connected.set()
    threading.Thread(target=late_connect).start()
    with client.run_scope():
        assert connected.is_set()
        device = client.get_device("loop1")
        assert device.echo("x") == "x"

def test_note_unavailable_is_what_get_device_raises():
    client.note_unavailable("bench.ini was discarded at startup, so this start has no devices: bad")
    with client.run_scope():
        with pytest.raises(DriverError, match="bench.ini was discarded at startup"):
            client.get_device("loop1")

def test_run_scope_without_a_pending_connect_does_not_wait():
    started = time.monotonic()
    with client.run_scope():
        pass
    assert time.monotonic() - started < 0.5
```

(Use the file's existing fixtures and cleanup that reset the client module state; add
`connect_pending`'s state to that reset.)

- [ ] **Step 2: Run them, expect FAIL** — `pytest tests/unit_tests/test_pyhal_client.py -k "pending or unavailable" -v` → `AttributeError: ... connect_pending`.
- [ ] **Step 3: Implement** — a module `threading.Event` `_connect_settled`, set at import;
  `connect_pending()` clears it, `note_unavailable()` sets `_connect_problem` and the event,
  `connect()` / `connect_only()` set it in a `finally`. `run_scope()` waits on it (at most
  `CONNECT_WAIT_S`; past that it goes on and `get_device()` raises what it has) before
  `_begin_scope()`. Update the module docstring's *Connect or start* paragraph.
- [ ] **Step 4: Run** `pytest tests/unit_tests/test_pyhal_client.py -v` → PASS.

---

### Task 2: Starting the HAL with its window

**Files:**
- Modify: `src/pyhal/client.py` (`connect()`, `start_hal()`, `_start_hal()`, `_start_and_connect()`, `_launch()`)
- Modify: `src/pyhal/monitor/__main__.py`, `src/pyhal/monitor/window.py`, `src/pyhal/monitor/link.py` (`start()`)
- Test: `tests/unit_tests/test_pyhal_client.py`, `tests/unit_tests/test_pyhal_monitor_window.py`,
  `tests/functional_tests/test_pyhal_standalone.py`
- Docs: `src/pyhal/pyhal.md` (*The client*, *The monitor*)

**Interfaces:**
- Produces:
  - `connect(bench, port=DEFAULT_PORT, *, scope=True, log_sink=None, log_level=None, log_dir=None, show_window: bool = False) -> HalClient`
    — when nothing answers and `show_window`, it launches
    `python -P -m pyhal.monitor --bench B --port P --serve --exit-with-hal --nonce N [--log-level L] [--log-dir D]`
    (same detach flags, PYTHONPATH and startup file as `_launch()`) instead of `python -m pyhal`,
    then waits for a `hello` exactly as today. `started_hal` is `hello.nonce == N`.
  - `start_hal(bench, port=DEFAULT_PORT, *, log_level=None, log_dir=None, nonce: str | None = None) -> int`
    — `nonce` given: the HAL is started with it (instead of a fresh one).
  - `MonitorLink.start(bench: str, log_dir: str | None = None, *, log_level: int | None = None, nonce: str | None = None) -> int`
  - `MonitorWindow(port, *, bench=None, log_dir=None, serve=False, log_level: int | None = None, nonce: str | None = None, exit_with_hal: bool = False)`
  - `python -m pyhal.monitor` options `--log-level LEVEL` (as `python -m pyhal` parses it),
    `--nonce TEXT` (needs `--serve`), `--exit-with-hal` (needs `--serve`).
  - **`exit_with_hal`:** once a poll has seen a HAL answer, the first poll that finds none
    closes the window, with no Stop (there is nothing left to stop) and no question.

- [ ] **Step 1: Write the failing tests**
  - `test_start_hal_uses_a_given_nonce` (client, real `python -m pyhal` on a free port as the
    existing `start_hal` tests do): `pid = client.start_hal(bench, port, nonce="abc")`, then a raw
    connection's `hello.nonce == "abc"`.
  - `test_the_monitor_options_need_serve` (`monitor.__main__._build_parser` / `main`):
    `--nonce x` and `--exit-with-hal` without `--serve` → `SystemExit` code 2.
  - `test_exit_with_hal_closes_the_window_when_the_hal_goes` (window, threaded server): a serve
    window with `exit_with_hal=True` on a running HAL; `_stop(hal)`; `qtbot.waitUntil(lambda: not window.isVisible())`; `window.wait_before_exit()` sends nothing (the HAL is gone; no
    `Stopping the HAL` INFO in `caplog`).
  - `test_serve_start_passes_the_nonce` (window): monkeypatched `client.start_hal` records its
    `nonce` kwarg; a serve window built with `nonce="abc"` on a free port → recorded `"abc"`.
  - Functional (`test_pyhal_standalone.py`, a real process tree, marked as its siblings are):
    `test_connect_with_window_starts_the_monitor_and_owns_the_hal` — `connect(bench, port, scope=False, show_window=True)` with `QT_QPA_PLATFORM=offscreen` in the environment;
    `hal.started_hal is True`; a process whose command line holds `pyhal.monitor` exists; `hal.close()` → the port stops answering and the monitor process exits within 30 s.
  - Functional: `test_connect_with_window_reports_a_failed_start` — a bench file that is not
    INI; `connect(..., show_window=True)` raises `DriverError` whose text starts
    `The HAL server could not be started:` within `HAL_START_TIMEOUT_S + 5`; afterwards kill the
    leftover monitor process (the test's own cleanup, by pid from the startup file or
    `Get-CimInstance`).
- [ ] **Step 2: Run them, expect FAIL.**
- [ ] **Step 3: Implement.** `_launch()` gets `module: str` (`"pyhal"` or `"pyhal.monitor"`)
  and `nonce: str | None`; the monitor command adds `--serve --exit-with-hal`. For the monitor,
  `CREATE_NO_WINDOW` stays (it only hides a console; the Qt window shows). The `_start_and_connect()` "exited for good" check stays as it is (a monitor that
  exits early is a failed start). `MonitorWindow._start_pressed()` passes `log_level` and
  `nonce` to `link.start()`. `exit_with_hal` lives in `_show_status()`: `_seen_hal` set on a
  report, and a `None` report with `_seen_hal` and `exit_with_hal` → `self.close()` with
  `_stop_on_exit` left False.
- [ ] **Step 4: Run** `pytest tests/unit_tests/test_pyhal_client.py tests/unit_tests/test_pyhal_monitor_window.py tests/functional_tests/test_pyhal_standalone.py -v` → PASS.

---

### Task 3: The `[hal] show_window` setting

**Files:**
- Modify: `src/pypts/config_handler/configuration_schema.py` (`SCHEMA`, `CONFIG_VERSION`, its comment)
- Modify: `src/pypts/config_handler/config_template.ini` (`config_version = 5.0.0`, new `[hal]` section with a comment)
- Modify: `src/pypts/hmi/gui/settings_dialog.py` (its page placement, label, tooltip; next-start note if the dialog marks keys that apply at the next start)
- Test: `tests/unit_tests/test_config_handler.py`, `tests/unit_tests/test_settings_dialog.py` (or wherever the dialog's tests are — find them with `rg settings_dialog tests`)
- Docs: `config_handler/config_handler.md` (version history, *Who uses it* row for `core/hal_link.py`), `usage_manual.html` (Settings), `hmi/gui/gui.md` if it lists the pages

**Interfaces:**
- Produces: `ConfigHandler().get_parameter("hal.show_window") -> bool`, default `True`.

- [ ] **Step 1: Write the failing tests**
  - `test_hal_show_window_defaults_to_true`: a config built from defaults →
    `get_parameter("hal.show_window") is True`.
  - `test_a_version_4_file_is_discarded`: a file with `config_version = 4.0.0` → DISCARDED,
    problem text names `5.0.0`.
  - Settings dialog: the key appears on a page with the label `HAL: show its window` and a
    tooltip that says it applies when PyPTS starts the HAL, from the next start.
  - The existing `test_schema_and_template_agree` covers the template.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** `"hal": {"show_window": Field("bool", "true")}`; the template
  comment: `# Whether a HAL that PyPTS starts opens its monitor window. A HAL already running is used as it is. Read at start.`
  `CONFIG_VERSION = "5.0.0"` with one more sentence in its history comment. New page title
  `Hardware` in the dialog's section titles if pages are per section.
- [ ] **Step 4: Run** `pytest tests/unit_tests/test_config_handler.py <dialog tests> -v` → PASS.

---

### Task 4: `core/hal_link.py`

**Files:**
- Create: `src/pypts/core/hal_link.py`
- Modify: `tests/conftest.py` (`os.environ.setdefault("PYPTS_HAL", "off")` beside `QT_QPA_PLATFORM`, so spawned engines inherit it)
- Create: `tests/unit_tests/test_hal_link.py`
- Docs: `core/core.md` (new *The HAL link* section, files table), `logger/logging_rules.md` (HAL lines arrive as `HAL: ...` at their own level)

**Interfaces:**
- Consumes: Task 1 `connect_pending()`, `note_unavailable()`; Task 2 `connect(..., show_window=)`;
  Task 3 `hal.show_window`; `pypts.config_handler.bench_config.bench_config()` / `BenchOutcome`.
- Produces:
  - `HAL_SWITCH_ENV = "PYPTS_HAL"`; the value `off` means no connect and
    `HAL_OFF = "The HAL is turned off for this process (PYPTS_HAL=off)."` as the reason.
  - `CLOSE_WAIT_S = 5.0` — the longest the close waits for a startup connect still running.
  - `class HalLink:`
    - `__init__(self, log_level: int, *, show_window: bool, port: int = DEFAULT_PORT) -> None`
    - `start(self) -> None` — on the calling thread: the switch (off → `note_unavailable(HAL_OFF)`, return), the bench (`DISCARDED` →
      `note_unavailable("bench.ini was discarded at startup, so this start has no devices: <problem>")`, return); else `connect_pending()` and a daemon thread `HAL connect` that calls
      `pyhal.client.connect(bench.path, port, scope=False, log_sink=self._sink, log_level=log_level, show_window=show_window)`.
    - `close(self) -> None` — the close of spec §6.4, on the calling thread, idempotent,
      never raises: join the connect thread at most `CLOSE_WAIT_S`; connected → `client.close()`
      (it already does steps 1 and 3: scope counter, long connection, `shutdown` if started else
      `close_all`, half-close); thread still running → set `_closed` so the thread, when its
      connect returns, closes that client at once itself.
    - `_sink(self, level: int, message: str) -> None` — `log.log(level, "HAL: %s", message)`.
  - Log lines (CORE's logger `pypts.core.hal_link`): INFO `Started the HAL server.` /
    `Connected to the HAL server.` (found running) / WARNING
    `The HAL server could not be reached: <reason>` ; pid, port, bench path, window at DEBUG.

- [ ] **Step 1: Write the failing tests** (`test_hal_link.py`; a threaded `HalServer` on a free
  port as `test_pyhal_monitor_window.py`'s fixture does; `monkeypatch.delenv("PYPTS_HAL")` where a
  connect is wanted; the client module state reset after each test):
  - `test_the_switch_off_makes_no_connect_and_says_why`
  - `test_a_discarded_bench_is_what_get_device_reports` (patch `bench_config` to a DISCARDED outcome)
  - `test_it_connects_to_a_running_hal_and_relogs_its_lines` — `caplog` gets a record
    starting `HAL: ` at the HAL record's own level after a device call.
  - `test_close_sends_close_all_to_a_hal_it_found` — the server keeps running; a device opened
    through the link is closed (`info` on a spare connection: `is_open is False`).
  - `test_close_sends_shutdown_to_a_hal_it_started` — patch `client._start_hal` path by making
    `connect` start the threaded server (as the window tests patch `start_hal`) and set
    `started_hal = True`; after `close()` the server exits.
  - `test_close_during_the_startup_connect_does_not_block` — `connect` patched to sleep 30 s;
    `close()` returns within `CLOSE_WAIT_S + 1`.
  - `test_a_failed_connect_is_what_get_device_reports` — nothing on the port, `connect`
    patched to raise `DriverError("x")`; WARNING logged; in a `run_scope()` `get_device()` raises `x`.
- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: pypts.core.hal_link`).
- [ ] **Step 3: Implement** `src/pypts/core/hal_link.py` to the interface above.
- [ ] **Step 4: Run** `pytest tests/unit_tests/test_hal_link.py -v` → PASS.

---

### Task 5: CORE runs the link; the Sequencer runs `run_scope()`

**Files:**
- Modify: `src/pypts/core/core.py` (`core_main()` passes `log_level`; `Core.__init__` makes the
  `HalLink`; `Core.start()` starts it before `start_submodules()`; `handle_sequencer_message`
  `SequencerStopped` with `shutting_down` → `self.hal_link.close()` before `send_stop(REPORT)`;
  `close_at_once()` → `self.hal_link.close()` first, before the Stops, also when nothing is left running;
  the `BENCH_MAY_BE_ENERGISED` comment: the devices are on the HAL, which gets `close_all` but is not waited for)
- Modify: `src/pypts/sequencer/sequencer.py` (`run_body()`: `with pyhal.run_scope():`; remove
  `bench_sections()`, `read_hardware_sections`, the `LocalSetup` / `anchor_driver_files` /
  `bench_config` imports that only they used)
- Test: `tests/unit_tests/test_core.py`, `tests/unit_tests/test_sequencer.py`
- Docs: `core/core.md` (startup, *Shutdown choreography*), `sequencer/sequencer.md`,
  `config_handler/config_handler.md` (*Who uses it*: the Sequencer row loses `bench_config()`)

**Interfaces:**
- Consumes: Task 4 `HalLink`. `Core.__init__(self, to_hmi, from_hmi, *, log_level: int = DEFAULT_LOG_LEVEL)`.
- Produces: `Core.hal_link: HalLink`.

- [ ] **Step 1: Write the failing tests**
  - `test_core`: `test_the_orderly_close_closes_the_hal_link_on_sequencer_stopped` and
    `test_the_crash_close_closes_the_hal_link_before_the_stops` — `core.hal_link` replaced by a
    recorder; the order of `close` vs the `StopSequencer` / `StopReport` sends is asserted.
  - `test_sequencer`: rewrite `test_a_run_reaches_its_devices_and_closes_them_at_the_end` on a
    threaded `HalServer` with the loopback bench and `client.connect_only(port, scope=False)`:
    the PASS / ERROR outcomes as today; after the run a spare connection's `status` shows
    `loop1` not open; `get_device("loop1")` outside the run raises `No HAL scope is active`.
    Delete `test_a_run_that_uses_no_device_never_reads_the_hardware_sections` and
    `test_the_default_reads_bench_ini` (no seam any more); replace the `BreakingLocalSetup`
    test (line ~798) with the same idea on `pyhal.run_scope` patched in `sequencer_module`.
  - `test_a_run_waits_for_the_startup_connect` (Review Focus 2): `connect_pending()`, start the run,
    `connect_only` 0.5 s later on another thread → the device step passes.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** as listed under *Files*.
- [ ] **Step 4: Run** `pytest tests/unit_tests/test_core.py tests/unit_tests/test_sequencer.py -v` → PASS.

---

### Task 6: Remove the in-process path

**Files:**
- Delete: `src/pyhal/local_setup.py`
- Modify: `src/pyhal/dispatch.py` → `get_device()`, `recover_device()`, `device_info()` forward
  to `pyhal.client` (imported at call time, so `import pyhal` stays light); docstring rewritten
- Modify: `src/pyhal/device_control.py` → only `DeviceInfo` stays (its two functions served
  the in-process handle); `src/pyhal/__init__.py` (`LocalSetup` out of `_LAZY_NAMES`, `__all__`,
  the `TYPE_CHECKING` imports)
- Modify: `src/pyhal/connection_driver.py` docstrings that name `LocalSetup` / `device_control`
  (the HAL's `devices.py` is its user now)
- Modify: `src/pypts/stream_handler/stream_session.py` (docstring and comment comparing to
  `LocalSetup`: compare to `pyhal.run_scope()`)
- Test: `tests/unit_tests/test_hal.py` (delete the `LocalSetup` tests, lines ~259-378, and the
  `_FakeConnection` fixture; add `"pyhal.local_setup"` to `test_the_old_modules_are_gone`),
  `tests/unit_tests/test_pyhal_client.py` (the dispatch tests at ~460-500 become
  "`pyhal.get_device` is the client's"), `tests/unit_tests/test_utilities.py` (its
  `"pypts.hal.local_setup"` mention)
- Docs: `src/pyhal/pyhal.md` (the in-process sections and the "until phase 3" lines, Files
  table, *Known gaps*), `stream_handler/stream_handler.md`

- [ ] **Step 1: Change the tests first** as listed; run `pytest tests/unit_tests/test_hal.py tests/unit_tests/test_pyhal_client.py -v` → the new `test_the_old_modules_are_gone` case FAILS.
- [ ] **Step 2: Implement** the deletions and rewrites.
- [ ] **Step 3: Run** `rg -n "LocalSetup|local_setup|read_hardware_sections|bench_sections|No local setup" src tests resources docs CLAUDE.md` → only history (status doc entries, plans, specs). Then `pytest tests/unit_tests -q` → PASS.

---

### Task 7: The documents, the full suite, a real run

**Files (docs, per spec §12.3, each only where it is still wrong):** `CLAUDE.md` (architecture
block and process list: the HAL is a standalone process CORE connects to; *Running*),
`launcher/launcher.md`, `hmi/hmi.md` (nothing if no message changed — say so), `step/step.md`
(values are plain data: tuples come back as lists, numpy refused), `api/api.md`,
`tests/quality_tests/quality_tests.md` if it lists tests, `src/pypts/README.md`,
`docs/Usage_manuals/usage_manual.html` (PyPTS now uses the HAL; the behaviour changes of spec
§12: killed PyPTS leaves devices open, crash close tears down, timeout rescues at once, tuples →
lists, other clients may share a device; the setting), `quick_start.html`, `recipe_guide.html`,
`migration_instructions.html`, `how_to_write_a_driver.html` / `.md`,
`pypts_implementation_status.html` (new entry 1.102, phase 3 done; the TODO in 1.101 marked
done), `resources/recipes/HAL_recipes/*` and showcase recipes only if they say "in-process",
`docs/superpowers/specs/2026-11-04-hal-server-design.md` (one line per builder's call taken:
`PYPTS_HAL`, `CLOSE_WAIT_S`, the window start).

- [ ] **Step 1:** Update the documents; re-read each against the code.
- [ ] **Step 2:** `pytest tests` → all pass (ruff + mypy included). Then
  `Get-CimInstance Win32_Process -Filter "Name like 'python%'"` shows no `pyhal` process left.
- [ ] **Step 3: A real run** (Review Focus 3 and the happy path), user's machine, real bench:
  `python -m pypts --mode headless --recipe resources/recipes/HAL_recipes/<a loopback/meteo demo>.yml`
  with `show_window = false` → exit code 0, the run log has `HAL: ` lines and `Started the HAL server.`;
  after exit no HAL answers on 29555. Then once in the GUI with `show_window = true`: the monitor
  window appears, the run passes, closing PyPTS closes the window.
- [ ] **Step 4:** Report: documents updated, test counts, what was not tried.

## Left to the builder

- Exact wording of the new INFO / WARNING lines, within `logging_rules.md`.
- Where in `test_pyhal_client.py` the reset of `_connect_settled` goes.
- The Settings page placement, if the dialog's pages are not per section.

## Self-review notes

- Spec coverage: §6.1 CORE/hal_link (T4, T5), §6.2 step 8 (T1), §6.3 run_scope in run_body (T5),
  §6.4 the close (T4, T5), §9 bench discarded + log sink + log level + INFO lines (T4), §12
  removals (T5, T6), §12.2 tests (T1-T6), §12.3 docs (T7). Not here: §8 View → HAL (phase 4).
- §12.1 housekeeping was done in phase 1.
