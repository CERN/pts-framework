# Plan 004 — Unreadable config.ini reported correctly

**Status: DONE** (branch `exec/004-config-unreadable`, commit `5d6a13e`)

## What was done

- `src/pypts/config_handler/config_handler.py` — `_read_raw()` now opens the file
  explicitly with `open()` + `parser.read_file()` instead of `parser.read()`.
  An `OSError` (file exists but cannot be opened) now raises its own
  `ConfigSchemaError("exists but cannot be opened: …")` instead of silently returning `{}`
  and being misreported as "structure version 0".
- `tests/unit_tests/test_config_handler.py` — one new test:
  `test_an_unopenable_file_is_reported_as_unopenable_not_version_zero`.
- `src/pypts/config_handler/config_handler.md` — one sentence added to the discard-reason
  enumeration.
- `resources/roadmap/pypts_roadmap.md` §1.3 — one `[x]` entry added.
