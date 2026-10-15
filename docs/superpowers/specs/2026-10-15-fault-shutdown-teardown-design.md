# Fault-shutdown device teardown: close 5 s, then kill, no rescue

**Date:** 2026-10-15
**Status:** approved

## Problem

When a run will not stop, the Sequencer abandons it and tears its devices down
(`Sequencer.tear_down_abandoned_devices()` → `LocalSetup.abandon()` →
`ConnectionDriver.abandon()`). Today the idle-device path tries `teardown()` with a 10 s
timeout and, when that hangs, runs a rescue (fresh driver process, `connect()`,
`teardown()`) with 10 s more — up to ~20 s against the caller's 11 s join budget
(`ABANDONED_DEVICES_TIMEOUT_S`). At second 11 the join gives up, a "may still be
energised" CRITICAL fires while the rescue is still running, and CORE's exit then kills
the rescue mid-teardown. The 15 s `SHUTDOWN_TIMEOUT_S` can blow too (2 + 20 > 15).

## Decision

During a fault shutdown, the framework stops compensating for a hung driver. The
stability of the hardware driver is the driver's responsibility: try a normal close
briefly, then kill, report honestly, and show the operator on the GUI that devices are
being closed. The **mid-run** rescue (a device call exceeding its timeout while the run
continues, `_read_message`) is explicitly **out of scope** and stays as it is.

## Design

### 1. HAL — `ConnectionDriver.abandon()` loses the rescue

- New constant `ABANDON_TEARDOWN_TIMEOUT_S = 5.0` in `connection_driver.py`.
- **Idle device:** `teardown()` is tried with that timeout. On timeout,
  `_read_message()` already kills the driver process and (because `_abandoned` is set)
  raises without rescuing; `abandon()` returns `False`. No `_rescue()` call.
- **Busy device** (lock held by the stuck call): the driver process is killed
  immediately, as today, and `abandon()` returns `False`. No `_rescue()` call.
- `_rescue()`, `RESCUE_TIMEOUT_S`, and the `_read_message` mid-run rescue are untouched.
- `ABANDONED_DEVICES_TIMEOUT_S` (sequencer) becomes `ABANDON_TEARDOWN_TIMEOUT_S + 1.0
  = 6.0 s`. The worst case now fits the budget; the original overrun bug disappears.
- `SHUTDOWN_TIMEOUT_S = 15.0` stays; only its sizing comment in `core.py` is updated.

### 2. GUI feedback — one new event, relayed as status text

(Amended 2026-10-15 after reading the code, both points approved.)

- New dataclass `ClosingDevices()`, sent by the Sequencer when
  `tear_down_abandoned_devices()` begins (before the per-device threads start). It rides
  **one** link — Sequencer→CORE — and CORE relays it as the existing
  `StatusChanged("Stopping: closing the devices…")`, the same pattern as
  `ReportGenerated` → `StatusChanged("Report generated: …")`. Both frontends already
  render `StatusChanged` (`show_status()`: GUI status label, CLI print), so no frontend
  code changes.
- **Hold StopHmi:** CORE today sends `StopHmi` immediately in `stop_all_modules()`, so
  the GUI would close before teardown starts and never show the text. `StopHmi` is now
  held back and released by `SequencerStopped` or by the shutdown deadline — exactly
  mirroring the existing `StopReport` hold (`stop_report_pending` /
  `release_stop_report()`). An ordinary shutdown is unaffected: the Sequencer answers in
  milliseconds. Side benefit: the abandonment CRITICALs now reach the GUI before it
  closes.

### 3. Honest reporting stays

A device killed without teardown remains a CRITICAL, reworded to match the new reality:
"Device(s) X were stopped without running teardown and may still be energised. Check the
bench before touching it." The framework no longer compensates for a hung driver, but
the operator still hears exactly what state the bench is in. The existing CRITICAL about
the run being abandoned is unchanged.

### 4. Tests

- A driver whose `teardown()` hangs: `abandon()` returns `False` within ~5 s, the driver
  process is dead, and **no second driver process was spawned**.
- Busy-device path: the process is killed, no rescue spawned, `False` returned.
- Message round-trips for `ClosingDevices` on both links (union completeness via
  `test_messages.py` and the shared-protocol tests).

### 5. Documentation (same change)

`hal/hal.md` (abandon/rescue sections), `sequencer/sequencer.md` (constant table and
abandon description), `core/core.md` (routing of `ClosingDevices`, `SHUTDOWN_TIMEOUT_S`
comment rationale), `messages/messages.md` (new message catalogue entry),
`hmi/hmi.md` and `hmi/gui/gui.md` (status text), `usage_manual.html` (what the operator
sees on a fault shutdown).
