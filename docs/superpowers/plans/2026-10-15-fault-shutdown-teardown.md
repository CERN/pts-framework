# Fault-Shutdown Device Teardown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** During a fault shutdown (a run that will not stop), close each device's driver with a 5 s teardown attempt, then kill it — no rescue reconnection — and show "closing the devices" on the GUI while it happens.

**Architecture:** Three code changes plus docs. (1) `ConnectionDriver.abandon()` loses its `_rescue()` calls and uses a new 5 s constant; the sequencer budget shrinks to 6 s. (2) A new `ClosingDevices` event on the Sequencer→CORE link, relayed by CORE as the existing `StatusChanged` text. (3) CORE holds `StopHmi` back until `SequencerStopped` (mirroring the existing `StopReport` hold) so the frontend is still open to show it. Spec: `docs/superpowers/specs/2026-10-15-fault-shutdown-teardown-design.md`.

**Tech Stack:** Python ≥ 3.11, pytest, ruff (line length 100), mypy. No new dependencies.

## Global Constraints

- Quality gates for every task: `pytest tests`, `ruff check src tests`, `mypy` — all three must pass before each commit (run at least the named test files per task; run all three gates in full in Task 4).
- Logging is `%`-style, never f-strings. Plain old-school Python: `if`/`else` over clever one-liners.
- `match` handlers stay closed with `unhandled()`; link union types are load-bearing — add to them, never restructure them.
- The mid-run rescue (`_read_message` → `_rescue()` on a call timeout during a running sequence) is **out of scope and must keep working**. Do not touch `RESCUE_TIMEOUT_S`, `_rescue()`, or `recover()`.
- No SPDX headers needed: all touched files are under `reuse.toml` globs (`src/pypts/**/*.py`, `tests/**/*.py`).
- Never `git checkout` a file to undo an experiment.
- End every commit message with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Work on branch `architecture_refactor` (current branch).

---

### Task 1: `abandon()` without rescue — 5 s teardown, then kill

**Files:**
- Modify: `src/pypts/hal/connection_driver.py:48-75` (constants), `:195-230` (`abandon()`), `:430-434` (comment in `_read_message`)
- Modify: `src/pypts/sequencer/sequencer.py:25` (import), `:77-80` (constant), `:774-777` (CRITICAL wording)
- Modify: `src/pypts/core/core.py:228-241` (the `SHUTDOWN_TIMEOUT_S` sizing comment only)
- Modify: `tests/unit_tests/hal_test_drivers.py:107-132` (`MarkingDriver`)
- Test: `tests/unit_tests/test_hal_connection.py`, `tests/unit_tests/test_sequencer.py:620-627`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `ABANDON_TEARDOWN_TIMEOUT_S: float = 5.0` in `pypts.hal.connection_driver`; `ConnectionDriver.abandon() -> bool` now returns `False` whenever teardown did not run (busy device, hung teardown, driver refusal) and never starts a second driver process; `ABANDONED_DEVICES_TIMEOUT_S == 6.0` in `pypts.sequencer.sequencer`.

- [ ] **Step 1: Give `MarkingDriver` a way to hang its teardown**

In `tests/unit_tests/hal_test_drivers.py`, replace `MarkingDriver.teardown()` (lines 123-125):

```python
    def teardown(self):
        if self._marks and os.path.exists(self._marks + ".tdhang"):
            time.sleep(60)
        if self._marks:
            self._mark("teardown")
```

and extend the class docstring's last sentence:

```python
    """
    Writes each connect() and teardown() into the file its `marks` key names,
    so a teardown in a fresh driver process can be seen from the test. Its
    connect() hangs while a file named like that one plus `.hang` exists, and
    its teardown() hangs while one named plus `.tdhang` exists.
    """
```

- [ ] **Step 2: Write the two failing tests**

In `tests/unit_tests/test_hal_connection.py`, after `test_an_abandoned_device_cannot_be_opened_or_recovered_again` (ends line 413), add:

```python
def test_abandoning_a_device_whose_teardown_hangs_kills_it_without_reconnecting(
    marking, monkeypatch
):
    """The driver's stability is not PyPTS's job: one teardown attempt, then the kill."""
    connection, marks = marking
    monkeypatch.setattr(connection_driver, "ABANDON_TEARDOWN_TIMEOUT_S", 0.5)
    (marks.parent / (marks.name + ".tdhang")).write_text("", encoding="utf-8")
    began = time.monotonic()

    assert connection.abandon() is False

    # One timeout and the kill - nowhere near the hang, and no rescue's 10 s.
    assert time.monotonic() - began < 5.0
    assert not connection.is_open()
    # The hung teardown never marked, and nothing ever connected again.
    assert marks_of(marks) == ["connect"]
```

Then replace the whole of `test_abandoning_a_device_mid_call_kills_it_and_tears_down_on_a_fresh_connection` (lines 416-448) with:

```python
def test_abandoning_a_device_mid_call_kills_it_without_reconnecting(tmp_path):
    """The abandoned run holds the device's lock: abandon() must not wait for it."""
    marks = tmp_path / "marks.txt"
    connection = ConnectionDriver("psu1", MARKING, {"marks": str(marks)}, call_timeout_s=60.0)
    connection.open()
    failures = []

    def stuck_step():
        try:
            connection.hang(60)
        except DriverError as exc:
            failures.append(str(exc))

    zombie = threading.Thread(target=stuck_step)
    zombie.start()
    try:
        deadline = time.monotonic() + 5.0
        while not connection._lock.locked() and time.monotonic() < deadline:
            time.sleep(0.01)
        began = time.monotonic()

        assert connection.abandon() is False

        assert time.monotonic() - began < 5.0
        zombie.join(timeout=5.0)
        assert not zombie.is_alive()
        # The killed call ends the step as a crash; nothing rescues it.
        assert len(failures) == 1
        assert "torn down on a fresh connection" not in failures[0]
        assert marks_of(marks) == ["connect"]
        assert not connection.is_open()
    finally:
        connection.close()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/unit_tests/test_hal_connection.py -v -k "abandoning"`
Expected: the two new/changed tests FAIL (`ABANDON_TEARDOWN_TIMEOUT_S` does not exist; `abandon()` returns `True` and marks show a second `connect`). The two untouched abandon tests still PASS.

- [ ] **Step 4: Implement the HAL change**

In `src/pypts/hal/connection_driver.py`, add after the `RESCUE_TIMEOUT_S` constant (line 56):

```python
#: How long abandon() gives an idle device's teardown() before the driver
#: process is killed. Short on purpose: shutdown is waiting, and a driver
#: that hangs in its own teardown() is reported, not compensated for.
ABANDON_TEARDOWN_TIMEOUT_S = 5.0
```

Replace `abandon()` (lines 195-230) with:

```python
    def abandon(self) -> bool:
        """
        Tear the device down for a run that will not end. Never raises.

        That run may be blocked in a call on this device, holding its lock, so
        nothing here waits for the lock. An idle device is given one teardown()
        within ABANDON_TEARDOWN_TIMEOUT_S; one that hangs is killed, as is a
        busy device's driver process. Nothing reconnects afterwards - a driver
        that did not tear down in time is the caller's CRITICAL to report, not
        this layer's problem to fix.

        Returns:
            True if teardown ran, or nothing was open to tear down.
        """
        self._abandoned = True
        if not self._lock.acquire(blocking=False):
            log.debug("Device '%s' is in a call; killing its driver process.", self.name)
            process = self._process
            if process is not None and process.is_alive():
                process.kill()
            return False
        try:
            if self._conn is None:
                return True
            try:
                self._exchange("teardown", [], {}, ABANDON_TEARDOWN_TIMEOUT_S, trace=True)
            except DriverError as exc:
                # A teardown that timed out was killed by _read_message(), one
                # that crashed is gone, and one the driver refused did not run:
                # in every case teardown did not happen, which is the answer.
                log.warning("Device '%s' did not disconnect cleanly: %s", self.name, exc)
                return False
            return True
        finally:
            self._discard()
            self._lock.release()
```

In `_read_message()`, update the comment block before the `_abandoned` check (lines 430-433) — replace

```python
                    # The stuck process could not tear down, so a fresh one
                    # does. Not before connect() returned (start-up has its
                    # own error), not for a rescue's own process, and not for
                    # an abandoned device: abandon() rescues by itself.
```

with

```python
                    # The stuck process could not tear down, so a fresh one
                    # does. Not before connect() returned (start-up has its
                    # own error), not for a rescue's own process, and not for
                    # an abandoned device: one is reported, never rescued.
```

- [ ] **Step 5: Shrink the sequencer budget and reword the CRITICAL**

In `src/pypts/sequencer/sequencer.py`, change line 25 from

```python
from pypts.hal.connection_driver import RESCUE_TIMEOUT_S
```

to

```python
from pypts.hal.connection_driver import ABANDON_TEARDOWN_TIMEOUT_S
```

Replace the constant and its comment (lines 77-80) with:

```python
#: How long stop() gives an abandoned run's devices, all torn down side by
#: side: one teardown attempt each, and a second for the kills to land.
#: Inside CORE's shutdown budget together with the join above (core.md).
ABANDONED_DEVICES_TIMEOUT_S = ABANDON_TEARDOWN_TIMEOUT_S + 1.0
```

In `tear_down_abandoned_devices()` (lines 774-777), replace the CRITICAL text

```python
            f"Device(s) {', '.join(unsafe)} could not be torn down and may still be energised. "
            f"Check the bench before touching it.",
```

with

```python
            f"Device(s) {', '.join(unsafe)} were stopped without running teardown and may "
            f"still be energised. Check the bench before touching it.",
```

In `tests/unit_tests/test_sequencer.py`, `test_an_abandoned_run_has_its_devices_made_safe_and_the_unsafe_ones_named` (line 625), extend the wording assertions:

```python
    assert "psu1" in unsafe.message
    assert "without running teardown" in unsafe.message
    assert "may still be energised" in unsafe.message
```

- [ ] **Step 6: Update the `SHUTDOWN_TIMEOUT_S` sizing comment**

In `src/pypts/core/core.py` (lines 236-239), replace

```python
    #: blame. Fifteen seconds because the Sequencer may need nearly all of it:
    #: SEQUENCE_JOIN_TIMEOUT_S (2 s) for a running sequence, then up to
    #: ABANDONED_DEVICES_TIMEOUT_S (11 s) tearing down the devices of one that
    #: would not stop. An ordinary shutdown takes a fraction of it. The
```

with

```python
    #: blame. Fifteen seconds holds the worst case with margin: the Sequencer
    #: may need SEQUENCE_JOIN_TIMEOUT_S (2 s) for a running sequence, then up
    #: to ABANDONED_DEVICES_TIMEOUT_S (6 s) tearing down the devices of one
    #: that would not stop. An ordinary shutdown takes a fraction of it. The
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal_connection.py tests/unit_tests/test_hal.py tests/unit_tests/test_sequencer.py -v`
Expected: ALL PASS. In particular `test_a_call_that_times_out_is_torn_down_on_a_fresh_connection` and `test_a_rescue_that_cannot_connect_is_bounded_and_said` (the mid-run rescue) must still pass unchanged.

Run: `ruff check src tests` and `mypy`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/pypts/hal/connection_driver.py src/pypts/sequencer/sequencer.py src/pypts/core/core.py tests/unit_tests/hal_test_drivers.py tests/unit_tests/test_hal_connection.py tests/unit_tests/test_sequencer.py
git commit -m "abandon() tries teardown for 5 s then kills, without the rescue

A fault shutdown no longer reconnects a hung driver to tear it down:
one teardown attempt within ABANDON_TEARDOWN_TIMEOUT_S (5 s), then the
kill, and the device is named in the CRITICAL instead. Fixes the idle
path taking ~20 s against the 11 s budget; the budget is now 6 s. The
mid-run rescue on a call timeout is untouched.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `ClosingDevices` event, relayed as status text

**Files:**
- Modify: `src/pypts/messages/core_sequencer_communication.py:88-128`
- Modify: `src/pypts/sequencer/sequencer.py` (import block lines 37-45, `tear_down_abandoned_devices()` line 770)
- Modify: `src/pypts/core/core.py` (import block lines 65-72, `handle_sequencer_message()` lines 479-483)
- Test: `tests/unit_tests/test_messages.py:163+` (EXAMPLES), `tests/unit_tests/test_sequencer.py:563-627`, `tests/unit_tests/test_core.py`

**Interfaces:**
- Consumes: Task 1's reworded CRITICAL (test assertion order below includes it).
- Produces: `@dataclass ClosingDevices` (no fields) in `pypts.messages.core_sequencer_communication`, member of the `SequencerToCore` union; CORE relays it as `StatusChanged("Stopping: closing the devices...")` — the exact text Task 4 documents.

- [ ] **Step 1: Write the failing tests**

In `tests/unit_tests/test_sequencer.py`, add `ClosingDevices` to the existing import from `pypts.messages.core_sequencer_communication` (the file already imports `SequencerStopped`, `StopSequencer`, etc. — extend that import). Then:

In `test_an_abandoned_sequence_is_reported_critical_before_sequencer_stopped` (line 587), change

```python
    assert [type(m) for m in messages] == [ModuleError, SequencerStopped]
```

to

```python
    assert [type(m) for m in messages] == [ModuleError, ClosingDevices, SequencerStopped]
```

In `test_an_abandoned_run_has_its_devices_made_safe_and_the_unsafe_ones_named` (lines 621-622), change

```python
    assert [type(m) for m in messages] == [ModuleError, ModuleError, SequencerStopped]
    unsafe = messages[1]
```

to

```python
    assert [type(m) for m in messages] == [ModuleError, ClosingDevices, ModuleError, SequencerStopped]
    unsafe = messages[2]
```

In `tests/unit_tests/test_core.py`, after `test_a_second_shutdown_request_sends_nothing_new` (ends line 697), add:

```python
def test_closing_devices_is_relayed_to_the_operator_as_status_text():
    """
    The Sequencer says it is tearing an abandoned run's devices down; the
    operator hears it as one status line, on the frontend that is still open.
    """
    from pypts.messages.core_hmi_communication import StatusChanged
    from pypts.messages.core_sequencer_communication import ClosingDevices

    core = build_core_that_spawns_nothing()

    core.from_sequencer.send(ClosingDevices())
    core.poll_all_sources()

    assert list(core.to_hmi.receive()) == [StatusChanged("Stopping: closing the devices...")]
```

In `tests/unit_tests/test_messages.py`, add `ClosingDevices` to the import from `pypts.messages.core_sequencer_communication` (lines 75-80), and in the `EXAMPLES` table add, directly after the `SequencerStopped` entry (line 258):

```python
    ClosingDevices: ClosingDevices(),
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit_tests/test_sequencer.py tests/unit_tests/test_core.py tests/unit_tests/test_messages.py -v`
Expected: FAIL with `ImportError: cannot import name 'ClosingDevices'`.

- [ ] **Step 3: Declare the message**

In `src/pypts/messages/core_sequencer_communication.py`, after the `SequencerStopped` dataclass (line 93), add:

```python
@dataclass
class ClosingDevices:
    """
    An abandoned run's devices are being torn down, before the goodbye.

    Sent once, when Sequencer.tear_down_abandoned_devices() begins, so the
    operator can be told the shutdown is in its device-teardown phase. CORE
    relays it to the HMI as a StatusChanged line; no answer.
    """
```

and add it to the `SequencerToCore` union, directly after `SequencerStopped` (line 112):

```python
SequencerToCore = (
    SequencerStopped
    | ClosingDevices
    | RunStarted
    ...
```

(only the one line is inserted; the rest of the union is unchanged).

- [ ] **Step 4: Send it and relay it**

In `src/pypts/sequencer/sequencer.py`, add `ClosingDevices` to the import from `pypts.messages.core_sequencer_communication` (lines 37-45). In `tear_down_abandoned_devices()`, insert the send before the teardown starts — replace (line 770)

```python
        unsafe = abandon_active_setup(ABANDONED_DEVICES_TIMEOUT_S)
```

with

```python
        self.core.send(ClosingDevices())
        unsafe = abandon_active_setup(ABANDONED_DEVICES_TIMEOUT_S)
```

In `src/pypts/core/core.py`, add `ClosingDevices` to the import from `pypts.messages.core_sequencer_communication` (lines 65-72). In `handle_sequencer_message()`, add a case directly after the `SequencerStopped` case (lines 481-483):

```python
            case ClosingDevices():
                # The device-teardown phase of a fault shutdown. One line of
                # free text is all a frontend needs to show it.
                self.to_hmi.send(StatusChanged("Stopping: closing the devices..."))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_sequencer.py tests/unit_tests/test_core.py tests/unit_tests/test_messages.py -v`
Expected: ALL PASS — including `test_every_message_type_has_an_example` and the handler-exhaustiveness tests, which is the proof the union, the example and the `case` all landed together.

Run: `ruff check src tests` and `mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/pypts/messages/core_sequencer_communication.py src/pypts/sequencer/sequencer.py src/pypts/core/core.py tests/unit_tests/test_messages.py tests/unit_tests/test_sequencer.py tests/unit_tests/test_core.py
git commit -m "Sequencer announces the device teardown of an abandoned run

New ClosingDevices event on the Sequencer->CORE link, sent when
tear_down_abandoned_devices() begins; CORE relays it to the HMI as
StatusChanged(\"Stopping: closing the devices...\"), which both
frontends already render.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Hold `StopHmi` until the Sequencer has stopped

**Files:**
- Modify: `src/pypts/core/core.py` (`__init__` lines 270-273, `handle_sequencer_message` `SequencerStopped` case lines 481-483, `stop_all_modules()` lines 1009-1014, new `release_stop_hmi()` after `release_stop_report()` line 1022, `check_stop_status()` lines 1051-1052)
- Test: `tests/unit_tests/test_core.py:583-697`

**Interfaces:**
- Consumes: nothing new (Task 2's relay works whether or not this lands, but only this makes the text visible on a real GUI).
- Produces: `Core.stop_hmi_pending: bool` and `Core.release_stop_hmi() -> None`, exact mirrors of `stop_report_pending` / `release_stop_report()`.

- [ ] **Step 1: Update and write the failing tests**

In `tests/unit_tests/test_core.py`:

Rename `test_shutdown_holds_stop_report_until_the_sequencer_has_stopped` (line 583) to `test_shutdown_holds_stop_report_and_stop_hmi_until_the_sequencer_has_stopped`, extend its docstring, and change its body (lines 595-605) to:

```python
    """
    The Report is stopped LAST. Stopping it first threw away every step of a run
    aborted by shutdown: the Report closed within one 10 ms tick while the
    Sequencer was still unwinding, so the tail it emitted was never drained.

    StopHmi is held with it: the Sequencer may still be abandoning a run, and
    the status line and CRITICALs it sends on the way must reach a frontend
    that is still open, not one already told to close.
    """
    core = build_core_that_spawns_nothing()

    core.from_hmi.send(ShutdownRequested())
    core.poll_all_sources()

    assert list(core.to_sequencer.receive()) == [StopSequencer()]
    assert list(core.to_hmi.receive()) == []
    assert list(core.to_report.receive()) == []

    core.from_sequencer.send(SequencerStopped())
    core.poll_all_sources()

    assert list(core.to_hmi.receive()) == [StopHmi()]
    assert list(core.to_report.receive()) == [StopReport()]
```

In `test_shutdown_deadline_releases_the_held_stop_report` (line 632): add `StopHmi` to the local import from `pypts.messages.core_hmi_communication`, and after the existing report assertion (line 651) add:

```python
    assert list(core.to_hmi.receive()) == [StopHmi()]
```

In `test_a_second_shutdown_request_sends_nothing_new` (line 682): add `SequencerStopped` to the local import from `pypts.messages.core_sequencer_communication`, and replace the body after the two `ShutdownRequested` sends (lines 696-697) with:

```python
    assert list(core.to_sequencer.receive()) == [StopSequencer()]

    core.from_sequencer.send(SequencerStopped())
    core.poll_all_sources()

    assert list(core.to_hmi.receive()) == [StopHmi()]
```

`test_core_routes_hmi_exit_to_every_submodule` (line 655) needs **no change**: it only drains the queues after `SequencerStopped`, so its assertions hold on the new choreography too — verify it still passes.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit_tests/test_core.py -v -k "shutdown or routes_hmi_exit or second_shutdown"`
Expected: the renamed hold test and the second-request test FAIL (`to_hmi` already contains `StopHmi()` in phase 1, and contains two after the second poll). The deadline test FAILS on the new `StopHmi` assertion.

- [ ] **Step 3: Implement the hold**

In `src/pypts/core/core.py`:

After the `stop_report_pending` attribute (lines 270-273), add:

```python
        #: True between "shutdown asked" and "the HMI has been told to stop".
        #: StopHmi is held back like StopReport: the Sequencer may still be
        #: abandoning a run, and the status line and CRITICALs it sends on the
        #: way must reach a frontend that is still open.
        self.stop_hmi_pending = False
```

In `stop_all_modules()`, replace (lines 1009-1014)

```python
        self.to_sequencer.send(StopSequencer())
        self.to_hmi.send(StopHmi())
        # StopReport is held back: the Sequencer may still be finishing an
        # aborted sequence whose events must reach the Report first. It is
        # released by SequencerStopped, or by the shutdown deadline.
        self.stop_report_pending = True
```

with

```python
        self.to_sequencer.send(StopSequencer())
        # StopReport and StopHmi are held back: the Sequencer may still be
        # finishing an aborted sequence whose events must reach the Report,
        # and may still be abandoning a run whose status line and CRITICALs
        # must reach a frontend that is still open. Both are released by
        # SequencerStopped, or by the shutdown deadline.
        self.stop_report_pending = True
        self.stop_hmi_pending = True
```

After `release_stop_report()` (ends line 1022), add:

```python
    def release_stop_hmi(self) -> None:
        """Send the held StopHmi, exactly once."""
        if not self.stop_hmi_pending:
            return
        self.stop_hmi_pending = False
        log.debug("Releasing the held StopHmi.")
        self.to_hmi.send(StopHmi())
```

In `handle_sequencer_message()`, extend the `SequencerStopped` case (lines 481-483):

```python
            case SequencerStopped():
                self.modules[SEQUENCER].running = False
                self.release_stop_report()
                self.release_stop_hmi()
```

In `check_stop_status()`, replace (lines 1051-1052)

```python
        # The Sequencer never answered; stop holding the Report for it.
        self.release_stop_report()
```

with

```python
        # The Sequencer never answered; stop holding the Report and the HMI.
        self.release_stop_report()
        self.release_stop_hmi()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_core.py tests/unit_tests/test_messages.py -v`
Expected: ALL PASS.

Run: `pytest tests` (the functional tests drive a real shutdown and must still complete), `ruff check src tests`, `mypy`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/core/core.py tests/unit_tests/test_core.py
git commit -m "Hold StopHmi with StopReport until the Sequencer has stopped

The frontend used to be told to close in the same tick the shutdown
began, so nothing the Sequencer said while abandoning a run - the
closing-devices status line, the CRITICALs - could reach an open
window. StopHmi now mirrors the StopReport hold: released by
SequencerStopped, or by the shutdown deadline. An ordinary shutdown
is unchanged - the Sequencer answers within milliseconds.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Documentation sync and full quality gates

**Files:**
- Modify: `src/pypts/hal/hal.md` (the "An abandoned run" and "The rescue" bullets, ~lines 131-147; the constants anywhere they are named, e.g. line 29)
- Modify: `src/pypts/sequencer/sequencer.md` (the abandon description ~line 85, the constants table ~line 129, the module's outgoing-messages list)
- Modify: `src/pypts/core/core.md` (shutdown choreography: the StopHmi hold; routing: `ClosingDevices` → `StatusChanged`; the `SHUTDOWN_TIMEOUT_S` rationale)
- Modify: `src/pypts/messages/messages.md` (catalogue entry for `ClosingDevices` on the Sequencer→CORE link)
- Modify: `usage_manual.html` (what the operator sees on a fault shutdown)
- Check, modify only if stale: `src/pypts/hmi/hmi.md`, `src/pypts/hmi/gui/gui.md`, `pypts_implementation_status.html`
- Modify: `docs/superpowers/specs/2026-10-15-fault-shutdown-teardown-design.md` (status line → implemented)

**Interfaces:**
- Consumes: the final code of Tasks 1-3 — every statement below must be verified against it, not written from this plan.
- Produces: nothing for other tasks; this closes the change.

- [ ] **Step 1: Update the module context files**

Read each file first; write what the code now does. The facts to land (verify each in the source before writing it):

- `hal.md` abandoned-run bullet: an idle device gets one `teardown()` within `ABANDON_TEARDOWN_TIMEOUT_S` (5 s) and is killed if it hangs; a device in a call has its process killed at once; **nothing reconnects** — the names of devices whose teardown did not run come back for one CRITICAL ("stopped without running teardown"). The budget is `ABANDONED_DEVICES_TIMEOUT_S` (6 s).
- `hal.md` rescue bullet: remove "and not after `abandon()` (`_abandoned`), which rescues by itself" — replace with "and not after `abandon()` (`_abandoned`): an abandoned device is reported, never rescued." The mid-run rescue description itself is unchanged.
- `sequencer.md`: the constants table row for `ABANDONED_DEVICES_TIMEOUT_S` (`ABANDON_TEARDOWN_TIMEOUT_S` + 1 = 6.0 s, "one teardown attempt each"); the stop description gains "sends `ClosingDevices` before the teardown starts"; the CRITICAL wording where quoted.
- `core.md`: shutdown choreography now holds **both** `StopReport` and `StopHmi` until `SequencerStopped` or the deadline (say why: the abandonment messages must reach an open frontend); routing table gains `ClosingDevices` → relayed as `StatusChanged("Stopping: closing the devices...")`; the 15 s budget rationale cites 2 s + 6 s.
- `messages.md`: add `ClosingDevices` to the Sequencer→CORE catalogue (EVT, no fields, relayed as `StatusChanged`).
- Delete every sentence these files held about the abandon-path rescue; no stale sentence beside a corrected one.

- [ ] **Step 2: Update the user-facing HTML**

In `usage_manual.html`, find the shutdown / fault-shutdown description (search for "energised", "abandoned", "shutdown") and update it: on a fault shutdown the status line shows "Stopping: closing the devices...", each device gets a 5 s teardown attempt and is then stopped, and a device stopped without teardown is named in a CRITICAL telling the technician to check the bench. Keep the file's existing structure and tone; change only sentences the code change made wrong or incomplete.

In `pypts_implementation_status.html`, grep for "rescue", "abandon", "StopHmi" — correct any statement Tasks 1-3 made stale; add nothing speculative.

In `src/pypts/hmi/hmi.md` and `src/pypts/hmi/gui/gui.md`, grep for "StopHmi" and "shutdown" — the handshake description ("request_shutdown → CORE stops everything → StopHmi → on_stop()") is still true; only amend if a sentence claims StopHmi is sent immediately.

- [ ] **Step 3: Mark the spec implemented**

In `docs/superpowers/specs/2026-10-15-fault-shutdown-teardown-design.md`, change `**Status:** approved` to `**Status:** implemented (2026-10-15)`.

- [ ] **Step 4: Full quality gates**

Run, in full, and paste the outcomes into the task report:

```bash
pytest tests
ruff check src tests
mypy
```

Expected: all three clean. Then the documentation check: re-read every document touched above against the final code — every identifier a document names must exist in the source.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hal/hal.md src/pypts/sequencer/sequencer.md src/pypts/core/core.md src/pypts/messages/messages.md usage_manual.html docs/superpowers/specs/2026-10-15-fault-shutdown-teardown-design.md
git add -u
git commit -m "Document the fault-shutdown teardown: 5 s close, kill, no rescue

hal.md, sequencer.md, core.md, messages.md, usage_manual.html brought
in line with the abandon() rework, the ClosingDevices status line and
the held StopHmi.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- Spec coverage: §1 → Task 1; §2 (message + hold, as amended) → Tasks 2-3; §3 (reworded CRITICAL) → Task 1 step 5; §4 (tests) → Tasks 1-3; §5 (docs) → Task 4.
- The status text `"Stopping: closing the devices..."` is spelled identically in Task 2 steps 1 and 4 and in Task 4 — it is the contract between them.
- Tasks are ordered so every commit leaves `pytest tests`, `ruff`, `mypy` green: the union, its EXAMPLES entry and CORE's `case` land in one commit (Task 2), because `test_messages.py` enforces all three together.
