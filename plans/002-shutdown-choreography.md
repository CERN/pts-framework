# Plan 002: Shutdown keeps the aborted run's report, and an abandoned sequence is reported, not hidden

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 800db1c..HEAD -- src/pypts/core/core.py src/pypts/sequencer/sequencer.py tests/unit_tests/test_core.py tests/unit_tests/test_sequencer.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (changes shutdown ordering; the 2 s / 5 s timeout budgets must stay consistent)
- **Depends on**: none (plan 003's tests build on the contract this plan establishes)
- **Category**: bug
- **Planned at**: commit `800db1c`, 2026-08-21

## Why this matters

Two defects in the same choreography:

1. **The stop order loses the aborted run's report.** `Core.stop_all_modules()`
   sends `StopReport` *first*. The Report acts on it within one 10 ms tick
   (`running = False`, CSV closed, `ReportStopped` answered). The Sequencer is
   only stopped next and spends up to 2 s letting the running sequence unwind —
   during which the step layer keeps emitting `StepExecuted`, and finally
   `RunFinished`, which Core forwards to `to_report` followed by
   `GenerateReport`. Nobody is draining that queue any more. Net effect:
   quitting the application (or closing the GUI window) mid-run silently
   discards every step that ran during the abort and never writes
   `report.html` — the exact scenario an operator hits when a run misbehaves
   and they close the app.

2. **An abandoned sequence thread is reported as a clean stop.** When the
   2 s join in `stop_running_sequence()` times out, the Sequencer logs one
   ERROR line and `stop()` still sends `SequencerStopped`. Core then exits
   "All modules stopped cleanly" while a daemon thread is mid-step, possibly
   driving hardware; teardown steps never ran, so the bench state is unknown —
   and nothing above a log line says so.

Scope decision (maintainer, 2026-08-21): **honesty, not policy.** The fix makes
the shutdown hold `StopReport` until the Sequencer has actually stopped (or the
existing deadline expires), and makes an abandoned sequence a CRITICAL
`ModuleError` the operator sees. What Core *does* about a wedged sequence
beyond reporting it remains the roadmap's open policy TODO (§1.11 / §4
"Error-handling policy") — do not invent policy here.

## Current state

Relevant files:

- `src/pypts/core/core.py` — the mediator. `stop_all_modules()` (lines
  554–574), `handle_sequencer_message()` (lines 353–389),
  `check_stop_status()` (lines 576–611), `__init__` state (lines 192–215),
  `SHUTDOWN_TIMEOUT_S = 5.0` (line 153).
- `src/pypts/sequencer/sequencer.py` — `stop()` (lines 256–264),
  `stop_running_sequence()` (lines 266–283), `SEQUENCE_JOIN_TIMEOUT_S = 2.0`
  (line 52).
- `tests/unit_tests/test_core.py` — has `build_core_that_spawns_nothing()`
  (lines 40–56), the pattern for driving one handler with no threads.
- `tests/unit_tests/test_sequencer.py` — has the `sequencer` fixture
  (lines 78–97), `drain()` (100–107), `blocks_until()` (110–117) and
  `start_a_blocking_sequence()` (120+) helpers.

`Core.stop_all_modules()` today (`core.py:554-574`):

```python
def stop_all_modules(self) -> None:
    """
    Ask every module to stop. Each answers with its own *Stopped event.

    Idempotent, because shutdown is legitimately requested twice: ...
    """
    if self.shutting_down:
        return
    self.shutting_down = True

    # The clock starts here rather than at the first unanswered check, so
    # the budget covers the whole shutdown and not just the tail of it.
    self.shutdown_deadline = time.time() + self.SHUTDOWN_TIMEOUT_S

    log.info("Shutdown requested, stopping all modules.")
    self.to_report.send(StopReport())
    self.to_sequencer.send(StopSequencer())
    self.to_hmi.send(StopHmi())
```

`Core.handle_sequencer_message()`, the branch that matters (`core.py:353-371`):

```python
def handle_sequencer_message(self, message: SequencerToCore) -> None:
    match message:
        case SequencerStopped():
            self.module_running[SEQUENCER] = False
        case RunStarted() | SequenceStarted():
            self.to_report.send(message)
            self.to_hmi.send(message)
        case RunFinished():
            self.to_report.send(message)
            self.to_report.send(GenerateReport())
            self.to_hmi.send(message)
        ...
```

`Core.check_stop_status()` deadline tail (`core.py:595-611`):

```python
    if not any(self.module_running.values()):
        log.info("All modules stopped cleanly")
        self.running = False
        return

    if self.shutdown_deadline is None or time.time() < self.shutdown_deadline:
        return

    # Reached once: self.running is cleared below, ...
    late = sorted(name for name, running in self.module_running.items() if running)
    log.error(
        "Modules did not stop within %.0fs and are being abandoned: %s",
        self.SHUTDOWN_TIMEOUT_S,
        ", ".join(late),
    )
    self.running = False
```

The Report's `StopReport` handling (`report/report.py:324-329`) — acts within
one tick, which is why sending it early kills the drain:

```python
@catch_and_report_errors()
def stop(self) -> None:
    self.running = False
    self.close_csv()
    log.info("Stopping module.")
    self.core.send(ReportStopped())
```

`Sequencer.stop()` and `stop_running_sequence()` today
(`sequencer.py:256-283`):

```python
@catch_and_report_errors()
def stop(self) -> None:
    """
    Shut the module down, bringing a running sequence with it.
    """
    self.running = False
    log.info("Stopping module.")
    self.stop_running_sequence()
    self.core.send(SequencerStopped())

def stop_running_sequence(self) -> None:
    """
    Ask a running sequence to stop, and wait for its thread to end.
    """
    thread = self.sequence_thread
    if thread is None or not thread.is_alive():
        return

    log.info("Waiting for the running sequence to stop.")
    self.stop_requested = True
    thread.join(timeout=SEQUENCE_JOIN_TIMEOUT_S)

    if thread.is_alive():
        log.error(
            "The running sequence did not stop within %.0fs; abandoning it.",
            SEQUENCE_JOIN_TIMEOUT_S,
        )
```

Facts you need about the surrounding machinery:

- The four engine links are plain `queue.Queue` (in-process); ordering **per
  queue** is guaranteed. When Core forwards `RunFinished` + `GenerateReport`
  to `to_report` and only afterwards sends `StopReport` on the same queue, the
  Report is guaranteed to process them in that order. That single-queue
  ordering is the whole mechanism this plan relies on.
- The abort tail always arrives **before** `SequencerStopped` on
  `from_sequencer` when the sequence thread ends within the 2 s join: the
  sequence thread emits `RunFinished` via `runtime.emit == self.core.send`
  before it exits, and `stop()` only sends `SequencerStopped` after the join
  returns. Same-queue ordering again.
- `report_problem(instance, message, severity=..., operation=...)` from
  `src/pypts/utilities/error_handling.py` sends a `ModuleError` to Core
  without raising; Core's `handle_module_error()` logs at the severity's
  level and forwards anything above WARNING to the frontend
  (`core.py:486-511`). `ErrorSeverity` lives in
  `pypts.messages.common_messages`. The Sequencer already calls
  `report_problem(self, ..., operation=...)` in `run_sequence()`
  (`sequencer.py:149-154`) — copy that call shape.
- `SEQUENCE_JOIN_TIMEOUT_S` (2.0) is deliberately below Core's
  `SHUTDOWN_TIMEOUT_S` (5.0) so the Sequencer's answer arrives inside Core's
  budget. Do not change either number.

Repo conventions (from `CLAUDE.md`): `%`-style logging only; handlers are
`match` closed with `unhandled()`; fixed lifecycle log wording (`Stopping
module.` etc.) must not be altered; plain readable Python.

## Commands you will need

Run from the repo root `C:\Git\pts-framework` (Windows).

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `.venv\Scripts\python.exe -m pytest tests -q` | all pass, 45 skipped, exit 0 |
| Focused | `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_core.py tests/unit_tests/test_sequencer.py -q` | all pass |
| Lint | `.venv\Scripts\python.exe -m ruff check src tests` | no NEW findings (6 pre-existing at `800db1c`; if plan 001 ran first, 5) |
| Typecheck | `.venv\Scripts\python.exe -m mypy` | `Success: no issues found` |

If pytest errors with `PermissionError ... pytest-of-Dzbanan`, add
`--basetemp=C:\Git\pts-framework\.pytest-tmp` (disposable, do not commit).

Note: `sequencer.py` carries 2 pre-existing ruff findings (`:146` E501,
`:213` BLE001). They are in `execute_sequence()`, which you are not editing —
leave them; fixing them is not this plan.

## Scope

**In scope** (the only files you should modify):

- `src/pypts/core/core.py`
- `src/pypts/sequencer/sequencer.py`
- `tests/unit_tests/test_core.py`
- `tests/unit_tests/test_sequencer.py`
- `resources/roadmap/pypts_roadmap.md` (status lines, Step 5)
- `plans/README.md` (your status row)

**Out of scope** (do NOT touch):

- `src/pypts/report/report.py` — the Report's immediate-stop behavior is
  correct once Core stops telling it too early.
- `src/pypts/messages/` — **no new message types**; the fix uses only existing
  messages. If you believe a new message is needed, that is a STOP condition.
- The timeout constants `SEQUENCE_JOIN_TIMEOUT_S`, `SHUTDOWN_TIMEOUT_S`,
  `THREAD_JOIN_TIMEOUT_S` — values unchanged.
- `WaitStep`'s uninterruptible sleep and any "interruptible wait" mechanism —
  known roadmap TODO, separate work.
- What Core *does* about a wedged sequence beyond logging/notifying — open
  policy TODO, not yours.

## Git workflow

- Branch off `architecture_refactor`: `advisor/002-shutdown-choreography`.
- Commit style: short lowercase summary (match `git log --oneline`). One or two
  commits (core half / sequencer half) both fine.
- Do NOT push or open an MR unless the operator instructed it.

## Steps

### Step 1: Hold `StopReport` until the Sequencer has stopped

In `core.py`:

1. In `__init__` (next to `self.shutting_down = False`, line 193), add:

   ```python
   #: True between "shutdown asked" and "the Report has been told to stop".
   #: The Report is stopped LAST so it can drain the aborted run's tail
   #: (StepExecuted / RunFinished / GenerateReport) before it closes.
   self.stop_report_pending = False
   ```

2. In `stop_all_modules()`, replace the three sends:

   ```python
   log.info("Shutdown requested, stopping all modules.")
   self.to_sequencer.send(StopSequencer())
   self.to_hmi.send(StopHmi())
   # StopReport is held back: the Sequencer may still be finishing an
   # aborted sequence whose events must reach the Report first. It is
   # released by SequencerStopped, or by the shutdown deadline.
   self.stop_report_pending = True
   ```

3. In `handle_sequencer_message()`, extend the `SequencerStopped` case:

   ```python
   case SequencerStopped():
       self.module_running[SEQUENCER] = False
       self.release_stop_report()
   ```

4. Add the small helper next to `stop_all_modules()`:

   ```python
   def release_stop_report(self) -> None:
       """Send the held StopReport, exactly once."""
       if not self.stop_report_pending:
           return
       self.stop_report_pending = False
       self.to_report.send(StopReport())
   ```

5. In `check_stop_status()`, in the deadline-expired branch, release the held
   stop **before** the abandon log line, so a Sequencer that never answered
   does not also strand the Report:

   ```python
   # The Sequencer never answered; stop holding the Report for it.
   self.release_stop_report()
   late = sorted(...)
   ```

Why this is safe: `SequencerStopped` arrives on `from_sequencer` *after* the
aborted run's `RunFinished` (same queue, sent later), and Core forwards
messages in arrival order, so by the time `release_stop_report()` puts
`StopReport` on `to_report`, the `RunFinished` + `GenerateReport` are already
queued ahead of it. The Report therefore writes the CSV tail and the HTML, and
only then stops.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_core.py -q`
→ if any existing test fails, read it: a test asserting the *old* immediate
`StopReport` must be updated to the new contract (assert `to_report` is empty
until `SequencerStopped` is delivered). At `800db1c` no test reads the
outboxes after `stop_all_modules()`, so expect no failures.

### Step 2: Core-side tests for the new contract

In `tests/unit_tests/test_core.py`, using `build_core_that_spawns_nothing()`
and the message-driving style of
`test_a_sequencer_event_is_routed_to_the_hmi` (drive handlers via
`core.from_hmi.send(...)` / `core.poll_all_sources()`, read outboxes via
`.receive()` or `get_nowait()`), add:

1. `test_shutdown_holds_stop_report_until_the_sequencer_has_stopped` —
   send `ShutdownRequested` on `from_hmi`, poll; assert `to_sequencer` got
   `StopSequencer`, `to_hmi` got `StopHmi`, and `to_report` is **empty**.
   Then send `SequencerStopped` on `from_sequencer`, poll; assert `to_report`
   now contains exactly one `StopReport`.
2. `test_the_aborted_runs_tail_reaches_the_report_before_stop` — send
   `ShutdownRequested`; then, on `from_sequencer`, send a
   `RunFinished(result=ResultType.STOP, outcomes=())` followed by
   `SequencerStopped`; poll once. Drain `to_report` and assert the order is:
   `RunFinished`, `GenerateReport`, `StopReport`.
3. `test_shutdown_deadline_releases_the_held_stop_report` — send
   `ShutdownRequested`, poll (so `stop_report_pending` is set); force
   `core.shutdown_deadline = time.time() - 1`; call
   `core.check_stop_status()`; assert `to_report` contains `StopReport` and
   the abandon ERROR was logged (`caplog`, message contains "abandoned").
4. `test_a_second_shutdown_request_sends_nothing_new` — send
   `ShutdownRequested` twice, poll; assert `to_sequencer` holds exactly one
   `StopSequencer` and `to_hmi` exactly one `StopHmi`.

Imports needed: `ShutdownRequested` from
`pypts.messages.core_hmi_communication`; `StopSequencer`, `SequencerStopped`
from `pypts.messages.core_sequencer_communication`; `StopReport`,
`GenerateReport` from `pypts.messages.core_report_communication`; `StopHmi`
from `pypts.messages.core_hmi_communication`; `RunFinished`, `ResultType` from
`pypts.messages.run_events` / `pypts.messages.common_messages`.
(Check the exact import homes with grep before writing — `StopSequence` vs
`StopSequencer` are different messages; you want `StopSequencer`.)

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_core.py -q`
→ all pass, including 4 new tests.

### Step 3: Report the abandoned sequence as CRITICAL

In `sequencer.py`:

1. Add `ErrorSeverity` to the imports from
   `pypts.messages.common_messages` (it currently imports `ResultType` from
   there), and confirm `report_problem` is already imported from
   `pypts.utilities.error_handling` (it is, line 45).

2. In `stop_running_sequence()`, replace the `if thread.is_alive():` tail:

   ```python
   if thread.is_alive():
       # The bench may be mid-step with teardown never run: the operator
       # must hear this, not just the log. What CORE *does* about it is
       # the open error-policy TODO; this only makes the abandonment loud.
       report_problem(
           self,
           f"The running sequence did not stop within "
           f"{SEQUENCE_JOIN_TIMEOUT_S:.0f}s and is being abandoned; "
           f"teardown steps have not run and the bench state is unknown.",
           severity=ErrorSeverity.CRITICAL,
           operation="Sequencer.stop_running_sequence",
       )
   ```

   (This replaces the bare `log.error(...)` — `report_problem` reaches Core as
   a `ModuleError`, which Core logs at CRITICAL and forwards to the frontend,
   so the operator sees it. Check `report_problem`'s exact signature in
   `utilities/error_handling.py` before writing the call; if it does not
   accept `severity=` or `operation=`, STOP — the error-handling layer has
   drifted from this plan.)

3. `stop()` still sends `SequencerStopped` after `stop_running_sequence()`
   returns — **unchanged**. The CRITICAL report is sent on `self.core`
   *before* `SequencerStopped` (same queue), so Core processes the report
   first, then releases the Report, which is exactly the order wanted.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_sequencer.py -q`
→ all existing tests pass.

### Step 4: Sequencer-side test for the abandon report

In `tests/unit_tests/test_sequencer.py`, model on
`start_a_blocking_sequence()` (which installs a fake `execute_sequence` that
ignores the stop flag and blocks on an Event):

`test_an_abandoned_sequence_is_reported_critical_before_sequencer_stopped(sequencer, monkeypatch)`:

- `instance, outbox, inbox = sequencer`
- `monkeypatch.setattr("pypts.sequencer.sequencer.SEQUENCE_JOIN_TIMEOUT_S", 0.05)`
- Start a blocking sequence via the existing helper (do **not** set its
  release event yet, so the join times out).
- Call `instance.stop()`.
- `messages = drain(outbox)`; filter out `Heartbeat`s. Assert the remaining
  order contains a `ModuleError` with
  `severity is ErrorSeverity.CRITICAL` and `operation ==
  "Sequencer.stop_running_sequence"`, followed by a `SequencerStopped`.
- Finally set the release event so the fixture teardown can join the thread.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_sequencer.py -q`
→ all pass, including the new test (it should take ~0.1 s, not 2 s — the
monkeypatched timeout is what keeps the suite fast; if it takes 2 s, the
monkeypatch target is wrong).

### Step 5: Record it in the roadmap

In `resources/roadmap/pypts_roadmap.md`, section **§1.5** ("Topology change"),
find the open TODO "**A fault in either thread now takes CORE with it.**" and
append a sibling entry after it:

```
- [x] **DONE (plans/002):** shutdown is ordered: `StopReport` is held until
      `SequencerStopped` (or the shutdown deadline), so a run aborted by
      shutdown still gets its CSV tail and its report.html; and a sequence
      thread that outlives the 2 s join is reported to the operator as a
      CRITICAL ModuleError ("bench state unknown") instead of only an ERROR
      log line. Policy for *acting* on it stays the §1.11 TODO.
```

**Verify**: `git diff --stat` → exactly the six in-scope files modified.

## Test plan

Steps 2 and 4 above (5 new tests). Patterns: `build_core_that_spawns_nothing`
(`test_core.py:40-56`) for Core; the `sequencer` fixture + `blocks_until`
(`test_sequencer.py:78-117`) for the Sequencer. Full suite must stay green.

## Done criteria

ALL must hold:

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` exits 0; pass count grows
      by 5; skips stay at 45
- [ ] `.venv\Scripts\python.exe -m ruff check src tests` — no NEW findings
- [ ] `.venv\Scripts\python.exe -m mypy` → `Success: no issues found`
- [ ] `grep -n "StopReport()" src/pypts/core/core.py` shows it sent only from
      `release_stop_report()` (one send site)
- [ ] `grep -n "log.error" src/pypts/sequencer/sequencer.py` no longer shows
      the "abandoning it" line (replaced by `report_problem`)
- [ ] `git status` shows only the six in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any excerpt in "Current state" does not match the live code (drift since
  `800db1c`).
- `report_problem()` in `utilities/error_handling.py` does not accept
  `severity=` and `operation=` keyword arguments.
- You find yourself wanting to add a new message type to `src/pypts/messages/`
  — the design intent is that existing messages suffice; a new one is a
  design conversation, not an executor decision.
- An existing test asserts the old `StopReport`-first order for a documented
  reason you cannot reconcile (i.e. the comment in the test claims the order
  is load-bearing for something this plan has not considered).
- The new sequencer test cannot be made to pass without touching
  `execute_sequence()` or the timeout constants.

## Maintenance notes

- Plan 003's Core tests assume THIS plan's contract (StopReport held until
  `SequencerStopped` / deadline). Execute 002 before 003.
- If a `RunFinished` never arrives because the sequence thread is truly wedged
  (abandon path), the Report now stops with a truncated CSV and **no HTML for
  that run** — deliberate: the CRITICAL error explains why, and inventing a
  partial HTML would be policy. When the error-handling policy TODO (§1.11) is
  taken up, "should Core ask the Report to generate anyway after an abandon"
  belongs to that discussion.
- A reviewer should scrutinize: (1) that `release_stop_report()` is called on
  *both* paths (SequencerStopped and deadline), (2) that no path can send
  `StopReport` twice, (3) that the CLI clean-exit run
  (`--mode cli`, `exit` at the prompt) still logs
  "All modules stopped cleanly" — the no-run-in-flight shutdown gains one
  queue round-trip (Sequencer answers within ~10-20 ms), which is invisible
  but worth confirming once by hand.
