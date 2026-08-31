# Plan 003: Put a test net under the shutdown, abort and exit-handshake paths

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 800db1c..HEAD -- src/pypts/core/core.py src/pypts/sequencer/sequencer.py src/pypts/hmi/hmi_client.py src/pypts/launcher/startup.py tests/unit_tests/`
> Plan 002 is EXPECTED to have changed `core.py`, `sequencer.py`,
> `test_core.py` and `test_sequencer.py` — that is not drift. Anything else
> changed: compare the excerpts below against live code first.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (tests only — no production code changes except where a test
  proves a documented claim false, which is a STOP, not a fix)
- **Depends on**: plans/002-shutdown-choreography.md (the Core tests below
  assert 002's contract; running them before 002 will fail by design)
- **Category**: tests
- **Planned at**: commit `800db1c`, 2026-08-21

## Why this matters

The paths that decide whether a bench run ends safely are the least-tested code
in the repo: nothing asserts what `Core.poll()` survives, no test exercises a
mid-run abort's partial outcomes, the CLI's exit handshake
(`wait_until_stopped`) has zero tests, and the launcher's `stop_core()` — the
ordering guarantee the whole shutdown design rests on — is a pure function of
two injectable arguments that simply was never tested (`test_startup.py` covers
only the config popup). These are the safety controls on a hardware bench; this
plan pins them so plans 001/002 and the coming engine ports cannot silently
regress them.

## Current state

All production code below is **read-only** for this plan. Excerpts are from
commit `800db1c`; where plan 002 edits them, the 002-contract version is noted.

- `src/pypts/core/core.py` — `poll()` (lines 289–310) is the mediator's
  survive-anything guarantee:

  ```python
  def poll(self, inbox, handler) -> None:
      try:
          for message in inbox.receive():
              handler(message)
      except UnhandledMessage as exc:
          log.error(str(exc))
      except Exception:
          log.exception("Failure while receiving a message")
  ```

  A message with no `case` raises `UnhandledMessage` (from
  `pypts.messages`); any other exception is logged; either way the loop and
  the remaining queues must keep working.

- `src/pypts/sequencer/sequencer.py` — `execute_sequence()` (lines 172–221)
  runs a real sequence on the calling thread when invoked directly; it emits
  `RunStarted`, delegates to the step layer, and ends with
  `RunFinished(result=..., outcomes=tuple(...))`; `stop_requested` is checked
  **between** steps by `Step.run_steps()` (`src/pypts/step/step.py:295-303`).
  The only existing STOP-result test
  (`test_sequencer.py:371-382` at `800db1c`) sets `stop_requested` *before*
  the run, so zero steps execute — the operator-realistic "abort after step 1
  of 2" shape (partial outcomes) is untested.

- `src/pypts/hmi/hmi_client.py` — `wait_until_stopped()` (lines 184–197):

  ```python
  def wait_until_stopped(self, grace_s: float = SHUTDOWN_GRACE_S) -> None:
      deadline = time.time() + grace_s
      while self.running and time.time() < deadline:
          time.sleep(0.05)
      if self.running:
          log.warning("CORE did not acknowledge the shutdown request; stopping anyway.")
          self.stop()
  ```

  `self.running` is flipped by `stop()`, which runs when the **polling
  thread** (CLI) handles `StopHmi`. In a single-threaded test, deliver
  `StopHmi` by calling `client.poll_core()` from another thread, or simply
  call `client.stop()` from a `threading.Timer` — see Step 3.
  `stop()` sends `HmiStopped()` on `client.core`.

- `src/pypts/launcher/startup.py` — `stop_core()` (lines 323–341):

  ```python
  def stop_core(core_process: Process | None, to_core: QueueWrapper[HmiToCore]) -> None:
      if core_process is None:
          return

      to_core.send(HmiStopped())
      to_core.send(ShutdownRequested())
      core_process.join(timeout=CORE_SHUTDOWN_TIMEOUT_S)

      if core_process.is_alive():
          log.warning("Core did not shut down in time; terminating it.")
          core_process.terminate()
          core_process.join(timeout=CORE_SHUTDOWN_TIMEOUT_S)
  ```

  It only calls `send`, `join(timeout=)`, `is_alive()`, `terminate()` — a
  stub object with scripted `is_alive` answers tests it fully.
  `CORE_SHUTDOWN_TIMEOUT_S = 5.0` (module constant, line 59) — monkeypatch it
  small in tests.

  `start_debug_monitor()` (lines ~272–320) polls for the log file for up to
  `MONITOR_LOG_WAIT_S = 5.0` (line 71) at `MONITOR_LOG_POLL_S = 0.05` and
  returns `None` with a warning when it never appears. Monkeypatch
  `MONITOR_LOG_WAIT_S` to ~0.1 for the timeout test.

- Existing test helpers to reuse:
  - `tests/unit_tests/test_core.py:40-56` — `build_core_that_spawns_nothing()`.
  - `tests/unit_tests/test_sequencer.py:78-107` — the `sequencer` fixture and
    `drain()`.
  - `tests/unit_tests/test_sequencer.py:40-68` — recipe-text constants built
    with `Recipe.from_yaml_text(...)` style (grep the file for how existing
    tests build a `Recipe`; follow that pattern).
  - `tests/unit_tests/test_startup.py` — the monkeypatch style for launcher
    functions.

- Three skipped placeholders in `test_core.py:25-37`
  (`test_core_starts_its_submodules`,
  `test_core_routes_hmi_exit_to_every_submodule`,
  `test_core_records_heartbeats_from_each_module`) — this plan implements the
  second and third and leaves the first skipped (it starts real threads;
  that is functional-test territory).

Repo conventions: plain pytest functions, no classes; descriptive
sentence-style test names; `%`-style logging asserted via `caplog` only where
the log *is* the behavior; drive modules through their real inboxes.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `.venv\Scripts\python.exe -m pytest tests -q` | all pass, exit 0 |
| Focused | `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_core.py tests/unit_tests/test_sequencer.py tests/unit_tests/test_messages.py tests/unit_tests/test_startup.py -q` | all pass |
| Lint | `.venv\Scripts\python.exe -m ruff check src tests` | no NEW findings |
| Typecheck | `.venv\Scripts\python.exe -m mypy` | `Success: no issues found` |

If pytest errors with `PermissionError ... pytest-of-Dzbanan`, add
`--basetemp=C:\Git\pts-framework\.pytest-tmp` (disposable, do not commit).

Wall-clock guard: every new test must finish in well under 1 s. Any real
timeout constant a test waits on gets monkeypatched small first. If a new test
takes multiple seconds, its monkeypatch target is wrong — fix the test, not
the timeout.

## Scope

**In scope** (the only files you should modify):

- `tests/unit_tests/test_core.py`
- `tests/unit_tests/test_sequencer.py`
- `tests/unit_tests/test_messages.py` (only if the exit-handshake tests fit
  better beside the existing `HmiClient` tests there — executor's choice; a
  new `tests/unit_tests/test_hmi_client.py` is equally acceptable)
- `tests/unit_tests/test_startup.py`
- `resources/roadmap/pypts_roadmap.md` (one line, Step 5)
- `plans/README.md` (your status row)

**Out of scope** (do NOT touch):

- ALL production code under `src/pypts/`. If a test you write reveals a real
  defect, that is a STOP-and-report, not a fix — the maintainer decides.
- `tests/functional_tests/` — the process-topology suite is a separately
  rejected-for-now item (see plans/README.md).
- The three `test_hmi_cli.py` stale placeholders — recorded separately, not
  this plan.

## Git workflow

- Branch off `architecture_refactor` (after 002 is merged/landed):
  `advisor/003-shutdown-test-net`.
- Commit style: short lowercase summary. One commit is fine.
- Do NOT push or open an MR unless the operator instructed it.

## Steps

### Step 1: Core — routing fan-out, idempotency, and poison survival

In `tests/unit_tests/test_core.py`, replace the two skipped placeholders
(`test_core_routes_hmi_exit_to_every_submodule`,
`test_core_records_heartbeats_from_each_module`) with real tests, and add the
poison test:

1. `test_core_routes_hmi_exit_to_every_submodule` — delete the
   `@pytest.mark.skip` and implement per plan 002's contract:
   `ShutdownRequested` in via `from_hmi`, one `poll_all_sources()`; assert
   `to_sequencer` received a `StopSequencer` and `to_hmi` a `StopHmi`; then
   `SequencerStopped` in via `from_sequencer`, poll; assert `to_report`
   received a `StopReport`. (If plan 002's own tests already cover exactly
   this, implement this placeholder as a thin variant asserting **all three**
   recipients across the two phases — the placeholder name should stop lying
   as a skip either way.)
2. `test_core_records_heartbeats_from_each_module` — delete the skip; for each
   of the three module names (`HMI`, `SEQUENCER`, `REPORT` from
   `pypts.utilities.heartbeat_manager`), send a
   `Heartbeat(source=name, timestamp=time.time())` through the matching
   inbox (`from_hmi` / `from_sequencer` / `from_report`), poll, and assert
   `core.last_heartbeat[name]` took the sent timestamp.
3. `test_a_poisoned_message_does_not_stop_the_mediator` — put an object that
   belongs to no union (e.g. the string `"not a message"`) on
   `core.from_report`'s underlying queue, followed by a legitimate
   `Heartbeat(source=REPORT, ...)`. Call `core.poll_all_sources()` twice
   (the batch is abandoned on the poison, the survivor is delivered on the
   next tick — that behavior is documented in `poll()`'s docstring).
   Assert: no exception escaped, and `core.last_heartbeat[REPORT]` was
   updated by the second poll. Note: an arbitrary object hits the `case _:
   unhandled(...)` arm → `UnhandledMessage` → the first `except` branch;
   also assert the ERROR was logged (`caplog`).

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_core.py -q`
→ all pass; skip count for this file drops by 2.

### Step 2: Sequencer — a mid-run abort reports the partial outcomes

In `tests/unit_tests/test_sequencer.py`, add
`test_an_abort_between_steps_reports_the_finished_steps(sequencer)`:

- Build a real two-step recipe the way the file's existing engine tests do
  (grep `from_yaml_text` in this file and copy the pattern), with two `Wait`
  steps of `wait_time: '0'`. Deliver it to the sequencer instance the way the
  existing engine tests do (`UseRecipe` through the inbox, or assigning
  `instance.recipe` directly — copy whichever pattern the file uses).
- Make the abort land between the steps **deterministically**: monkeypatch
  `pypts.step.steps.WaitStep._step` so the first call sets the stop flag
  before returning normally. The stop flag is checked by `Step.run_steps()`
  *between* steps, so step 1 completes, step 2 never starts:

  ```python
  calls = []
  real_step = WaitStep._step
  def stopping_step(self, runtime, step_input):
      calls.append(self.name)
      if len(calls) == 1:
          instance.stop_requested = True
      return real_step(self, runtime, step_input)
  monkeypatch.setattr(WaitStep, "_step", stopping_step)
  ```

  Then `instance.execute_sequence("Main")` on the test thread with the
  two-Wait recipe. Assert on `drain(outbox)` (filter `Heartbeat`): exactly one
  `StepStarted`/`StepFinished` pair, and a final
  `RunFinished` with `result is ResultType.STOP` and `len(outcomes) == 1`.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_sequencer.py -q`
→ all pass; the new test runs in < 1 s.

### Step 3: HmiClient — the exit handshake, both branches

Beside the existing `HmiClient` protocol tests (in
`tests/unit_tests/test_messages.py`, around its `HmiClient` section — or a new
`tests/unit_tests/test_hmi_client.py` mirroring its imports), add two tests
against a minimal concrete `HmiClient` (the file already builds one for the
protocol tests; reuse that pattern):

1. `test_wait_until_stopped_returns_as_soon_as_stop_arrives` — start a
   `threading.Timer(0.05, client.stop)` (simulates the polling thread handling
   `StopHmi`); call `client.wait_until_stopped(grace_s=2.0)`; assert it
   returned in well under 1 s (`time.monotonic()` bracket, `< 1.0`), that
   `client.running is False`, and that no
   "did not acknowledge" warning was logged (`caplog`).
2. `test_wait_until_stopped_gives_up_after_the_grace_period` — no timer; call
   `client.wait_until_stopped(grace_s=0.1)`; assert `client.running is False`
   afterward, the warning "CORE did not acknowledge" was logged exactly once,
   and a `HmiStopped` message is on `client.core` (drain it).

**Verify**: focused pytest on the file you edited → all pass.

### Step 4: Launcher — `stop_core()` and the monitor's wait bound

In `tests/unit_tests/test_startup.py` (same monkeypatch style as the existing
three tests):

1. `test_stop_core_asks_before_terminating(monkeypatch)` — build a stub:

   ```python
   class FakeProcess:
       def __init__(self, alive_answers):
           self.alive_answers = list(alive_answers)
           self.joined = []
           self.terminated = False
       def join(self, timeout=None):
           self.joined.append(timeout)
       def is_alive(self):
           return self.alive_answers.pop(0)
       def terminate(self):
           self.terminated = True
   ```

   With `alive_answers=[False]`: call
   `startup.stop_core(fake, QueueWrapper(queue.Queue()))` and assert
   `fake.terminated is False` and exactly one join happened. Drain the queue
   wrapper's underlying queue and assert the order is `HmiStopped`,
   `ShutdownRequested`.
2. `test_stop_core_terminates_a_wedged_core(monkeypatch)` — monkeypatch
   `startup.CORE_SHUTDOWN_TIMEOUT_S` to `0.01`; `alive_answers=[True]`;
   assert `fake.terminated is True` and two joins happened, and the
   "terminating it" warning was logged.
3. `test_stop_core_with_no_process_is_a_no_op` — `stop_core(None, wrapper)`;
   assert the wrapper's queue stays empty.
4. `test_start_debug_monitor_gives_up_when_the_log_never_appears(tmp_path, monkeypatch)`
   — monkeypatch `startup.MONITOR_LOG_WAIT_S` to `0.1`; call
   `startup.start_debug_monitor(tmp_path / "never.log", logging.DEBUG)`
   (check the real signature first — grep `def start_debug_monitor`); assert
   it returns `None`, logs a warning, and — critically — that
   `subprocess.Popen` was never called (monkeypatch
   `startup.subprocess.Popen` to a function that raises `AssertionError`).

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_startup.py -q`
→ all pass (3 existing + 4 new), total runtime < 2 s.

### Step 5: Record it in the roadmap

In `resources/roadmap/pypts_roadmap.md`, Phase 0's list (section
"### Phase 0 — Stabilize the skeleton"), append to the end of the bullet list:

```
- ~~Unit-test net under shutdown/abort/exit paths~~ **Done (plans/003):** Core
  fan-out + poison survival, mid-run abort partial outcomes, the HMI exit
  handshake both ways, and the launcher's `stop_core()`/monitor-wait bounds
  are asserted; two `test_core.py` placeholders became real tests.
```

**Verify**: `git diff --stat` → only in-scope files modified.

## Test plan

This plan *is* the test plan: ~12 new tests across four files, two skipped
placeholders converted to real tests. Full suite green; skip count drops by 2
(from 45 to 43).

## Done criteria

ALL must hold:

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` exits 0; skip count is 43
- [ ] Every new test individually completes in < 1 s (spot-check with
      `--durations=15`: no new test in the slowest list above 1 s)
- [ ] `.venv\Scripts\python.exe -m ruff check src tests` — no NEW findings
- [ ] `.venv\Scripts\python.exe -m mypy` → `Success: no issues found`
- [ ] `git diff --stat` shows zero lines changed under `src/pypts/`
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Plan 002 has not landed (its contract is what Step 1 asserts) — check
  `git log --oneline` / `plans/README.md` first.
- Any test you write fails against the production code as it stands. That is a
  discovered defect: report the failing test and the observed behavior; do
  not change production code and do not weaken the assertion to pass.
- `wait_until_stopped`, `stop_core` or `start_debug_monitor` signatures differ
  from the excerpts (drift).
- The Step 2 monkeypatch approach cannot produce a deterministic
  between-steps abort (e.g. `WaitStep._step` was renamed).

## Maintenance notes

- The rejected-for-now sibling of this plan is the **functional-test first
  slice** (boot `python -m pypts --mode cli` as a real subprocess) — recorded
  in `plans/README.md` under considered-and-rejected. When it is picked up,
  the two known-bug placeholders in `tests/functional_tests/test_launcher.py`
  (lines 39, 52) should become `xfail(strict=True)` rather than skips.
- These tests pin log sentences in a few places ("did not acknowledge",
  "terminating it"). If those lines are ever reworded, the tests fail for
  wording, not behavior — the wider "assert via shared constants" cleanup is
  a known, separately-recorded finding; do not expand into it here.
