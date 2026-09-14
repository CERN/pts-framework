# Plan 002 — Shutdown choreography

**Status: DONE** (branch `exec/002-shutdown`, commit `8ae180d`)

## What was done

- `src/pypts/core/core.py` — `stop_all_modules()` now holds `StopReport` in a
  `stop_report_pending` flag instead of sending it first. `release_stop_report()` sends it
  exactly once, called from `handle_sequencer_message(SequencerStopped)` and from the
  shutdown deadline path in `check_stop_status()`.
- `src/pypts/sequencer/sequencer.py` — `stop_running_sequence()` replaces the bare
  `log.error(...)` on a timed-out join with `report_problem(..., severity=CRITICAL)` so the
  operator sees an abandoned sequence instead of just a log line.
- `tests/unit_tests/test_core.py` — four new tests covering the held-StopReport contract,
  tail-message ordering, deadline release, and idempotent shutdown.
- `tests/unit_tests/test_sequencer.py` — one new test for the CRITICAL report on abandon.
- `resources/roadmap/pypts_roadmap.md` §1.5 — one `[x]` entry added.
