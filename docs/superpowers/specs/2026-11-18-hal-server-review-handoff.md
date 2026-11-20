<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server — everything in one place (parked 2026-11-19)

The one entry point for the HAL server work. Read this first; everything else is linked from
here. **State:** the teardowns are done (the close as it is now: Claude Doc "Teardown and
closing"); the HAL work starts once the user has answered the open questions.
Nothing here gets built until they pick it up again.

## Where everything is

| What | Where | Status |
|---|---|---|
| What is to be done, for review | Claude Doc "HAL server — what is to be done", https://claude.ai/artifact/7HRP7hqmvsdCciJkS1DWe9 | **The one source of truth for decisions and open questions** (the user's rule, 2026-11-19). Decided there: Q1 (the Sequencer closes a run's devices), 8 (idle HAL on an empty bench), 10 (client watchdog), 12 (keep `close`, add `close_device()`), Q2 (stop a HAL PyPTS started, D38 kept). Open: 2, 6, 7, 9, 11, Q3. Read it before this file's *Open questions*, which it overrides |
| How the HAL is built **today** | `src/pypts/hal/hal.md` | The authority on the current code. Not copied here, so it cannot drift |
| The design | `docs/superpowers/specs/2026-11-04-hal-server-design.md` | **Revision 4, draft.** Not ready to plan from (review below) |
| Review of rev 4: 4 blockers, fixes, 12 decisions, 4-phase plan | Claude Doc "HAL server spec rev 4 — review and decisions", https://claude.ai/artifact/UFV3CsG4Zj1vW25y6BnUAW | The 12 decisions are **unanswered**. The section below overrides decisions 3, 4 and 5 |
| How PyPTS closes today | Claude Doc "Teardown and closing", https://claude.ai/artifact/M12WpvrtULC7vNWi7Tx5uK | Current state only; the authority is `core/core.md` → *Shutdown choreography* |
| Older design reports (history) | `resources/internal_reports/hal_architecture_2026-11-02.html`, `hal_server_design_2026-11-04.html`, `hal_server_onepager_2026-11-05.html` | Superseded by rev 4 and this file |

## State

- No implementation plan exists, in the repo or in its history.
- Rev 4 was re-reviewed on 2026-11-18 by four reviewers (spec vs code, internal consistency,
  safety and failure modes, architecture and project rules). Verdict: **not ready to plan
  from**. As written, a normal close of PyPTS can still leave an instrument energised (the
  spec's own anti-goal 1). Blockers: B1 run-log/teardown order, B2 normal close leaving
  devices on, B3 CORE blocked by connect-or-start vs the 15 s HMI watch, B4 holes in the fence.
- The HAL code had not changed since the spec was written (last commit touching
  `src/pypts/hal/`: `cd4862e`) until **teardown change 1 (2026-11-19)** deleted the abandon
  path: `ConnectionDriver._abandon()`, `_abandoned`, `ABANDON_TEARDOWN_TIMEOUT_S`,
  `LocalSetup.abandon()`, `abandon_active_setup()` and the registry lock; `_rescue()` lost its
  time-limit argument. The spec's line numbers for `connection_driver.py`, `local_setup.py`
  and `sequencer.py` no longer hold, and its abandon-path text describes code that is gone.

## Closing with the HAL server — agreed with the user 2026-11-19

The user's rule: handle the standard close and a crash, nothing more; making every other
failure safe is their job. Revision 5 of the spec must take this in.

The HAL server owns the devices. PyPTS's whole part in a close is one `close_all`, sent
without waiting for the answer.

| Case | PyPTS | HAL server |
|---|---|---|
| A run ends | The Sequencer closes the run's devices after the teardown steps, before `RunFinished` (decided) | Tears them down with today's ladder |
| Orderly close (user's use case 1) | After `SequencerStopped`, CORE sends `close_all`, doesn't wait for the answer, carries on with the close | Tears down whatever is still open |
| Crash close (use cases 2, 4) | CORE sends `close_all`, then the Stops, then exits | Same |
| The HAL crashes (use case 5) | Nothing. The next call raises `DriverError`, the step errors, the run goes on | Its driver processes see their Pipe close and run `teardown()` |
| PyPTS killed hard | Nothing can send `close_all` | Does nothing (D36). Not a standard path |

Two requirements make sending `close_all` without waiting safe:

- **The HAL finishes a `close_all` it has received**, even after the client has gone (the
  part of rev 4 decision 4 that stays).
- **The client half-closes the socket after sending** (`shutdown(SHUT_WR)`, then close).
  If CORE closes while unread HAL data is waiting, the OS can reset the connection and drop
  the `close_all` still in flight.

### Changes to rev 4 and to the review's proposals

| Item | Rev 4 or the review | Now |
|---|---|---|
| Decision 3 | When the HAL is marked lost, send `close_all` on one fresh connection | Dropped: do nothing when the HAL crashes |
| Decision 4 | One shared HAL-side shutdown deadline; CORE waits for it before `StopHmi` | Dropped: CORE doesn't wait. Kept: the HAL finishes a teardown it started |
| Decision 5 | A CRITICAL to the operator when a device was not torn down at close | Dropped in PyPTS, which never sees the answer. The HAL's own log records it |
| HAL heartbeat watch, "HAL lost" state (phase 3) | PyPTS watches the HAL and marks it lost | Dropped: a dead HAL shows up as a failed call |
| D41 | CORE sends `close_all` after `RunFinished` from a helper thread, holds the next Start | Dropped if the run closes its own devices (open question 1) |
| S6 | The HAL tears down when its client disconnects (reverses D36) | Dropped: CORE sends `close_all` itself on a crash |
| Phase 3, "the shutdown order and budget" | A close phase with its own budget | One `close_all`, sent without waiting |
| D38 | `shutdown` the HAL only if this PyPTS started it | Kept (answered 2026-11-19) |

Decisions 1, 2 and 6–12 and phases 1, 2 and 4 stay as the review doc has them.

### Open questions for the user

Both answered 2026-11-19 in the "HAL server — what is to be done" doc, which now holds every
open question:

1. **Devices at run end:** the Sequencer's run scope closes them (decision 1 A).
2. **A HAL this PyPTS started:** stopped when PyPTS closes (D38 kept).

## Findings worth remembering

- Driver processes are daemons: when CORE exits they end **without** `teardown()`, so a
  crash close leaves
  devices as they are until the HAL server's `close_all` exists (accepted by the user).
- Driver processes ignore Ctrl+C (`driver_process_main()` calls
  `ignore_keyboard_interrupt()`); the HAL server's own driver processes need the same.
- Closing the console window may end the driver processes without teardown. That is
  reasoning only, not tested.

## Next steps, when the user picks this up

1. Re-read `hal.md` against the code as job 1 left it.
2. Get the user's answers: the 12 decisions in the review doc and the two open questions above.
3. Write revision 5 of the spec from those answers; have it re-checked.
4. Write the implementation plan, phased.

## Drift noticed, not fixed

- `CLAUDE.md` still lists `usage_manual.html` as being in the repo root; it is in
  `docs/Usage_manuals/`.
- The spec's §12.3 note about CLAUDE.md drift (three manuals, a `spikes/**` glob) is stale.
