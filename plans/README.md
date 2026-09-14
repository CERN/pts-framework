# Implementation Plans

Generated 2026-08-21 from an audit of `architecture_refactor` at commit `800db1c`.
All five plans executed serially in stacked worktrees; `exec/005-spawn` (`8e94168`)
is the complete result and is a direct fast-forward descendant of `architecture_refactor`.

Quality gates on `exec/005-spawn`: **408 passed / 43 skipped**, ruff = 5 pre-existing
findings, mypy clean. Linux end-to-end run for plan 005 still owed.

## Status

| Plan | Title | Status | Commit |
|------|-------|--------|--------|
| 001 | Report run-state hardening | DONE | `9a9edad` |
| 002 | Shutdown choreography | DONE | `8ae180d` |
| 003 | Shutdown / abort / exit-handshake test net | DONE | `9104e1f` |
| 004 | Unreadable config.ini reported correctly | DONE | `5d6a13e` |
| 005 | Launcher pins spawn start method | DONE | `8e94168` |

## What was deferred

- Functional-test first slice (all 20 `tests/functional_tests/` are skipped placeholders)
- `docs/source/` purge — all Sphinx docs describe pre-refactor engine; rewrite when format lands
- Quality-gate repair (CI ruff/coverage/REUSE gaps, no pytest-timeout, no Windows job)
- Dependency extras split (7 of 11 core deps have zero import sites in the package)
- Monotonic clocks for heartbeat aging and shutdown deadlines
- Redaction seam for step inputs (must be designed before SSH-step port)
- HMI error echo loop guard
- `skip:`/`critical:` recipe keys documentation
- Dead-but-maintained surface: config write API, `report_and_reraise`, six poll-interval literals
- `pyproject.toml:23` has a copy-pasted CERN email for the maintainer
