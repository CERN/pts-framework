# Plan 003 — Shutdown / abort / exit-handshake test net

**Status: DONE** (branch `exec/003-test-net`, commit `9104e1f`)

## What was done

- `tests/unit_tests/test_core.py` — two skipped placeholders converted to real tests
  (`test_core_routes_hmi_exit_to_every_submodule`,
  `test_core_records_heartbeats_from_each_module`); one new poison-message survival test.
- `tests/unit_tests/test_sequencer.py` — one new test for mid-run abort with partial outcomes.
- `tests/unit_tests/test_messages.py` — two new tests for `wait_until_stopped` (fast path
  and grace-period timeout).
- `tests/unit_tests/test_startup.py` — four new tests for `stop_core()` (normal, wedged,
  no-process no-op) and monitor log-wait timeout.
- `resources/roadmap/pypts_roadmap.md` Phase 0 checklist — one `[x]` entry added.
- No production code was changed.
