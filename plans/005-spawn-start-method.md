# Plan 005 — Launcher pins spawn start method

**Status: DONE** (branch `exec/005-spawn`, commit `8e94168`)

## What was done

- `src/pypts/launcher/startup.py` — `main()` calls
  `set_start_method("spawn")` (guarded with `get_start_method(allow_none=True) != "spawn"`)
  as its very first statement, before argparse and before the first `Queue()`.
- `tests/unit_tests/test_startup.py` — one new test:
  `test_main_pins_the_spawn_start_method_before_building_anything` (pin present +
  idempotent).
- `resources/roadmap/pypts_roadmap.md` — one `[x]` entry added.

## Still owed

Linux end-to-end run to confirm child processes start cleanly under spawn. No CI job
covers this; recorded in the roadmap entry.
