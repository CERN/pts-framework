<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server — review handoff, 2026-11-18

Where the HAL server work stands, so a new session (on any machine) can pick it up.
Read this first, then the two review docs below.

## State

- The design is `docs/superpowers/specs/2026-11-04-hal-server-design.md`, **revision 4,
  still a draft**. No implementation plan exists yet, in the repo or in its history.
- Revision 4 was re-reviewed on 2026-11-18 by four reviewers (spec vs code, internal
  consistency, safety and failure modes, architecture and project rules). Verdict: **not
  ready to plan from** — as written, a normal close of PyPTS can still leave an instrument
  energised (the spec's own anti-goal 1).
- The HAL code has not changed since the spec was written: the last commit touching
  `src/pypts/hal/` is `cd4862e`. Cited line numbers in the spec still hold.

## The two review docs (Claude Docs, on claude.ai — the user's answers and comments live there)

1. **HAL server spec rev 4 — review and decisions**
   https://claude.ai/artifact/UFV3CsG4Zj1vW25y6BnUAW
   - 4 confirmed blockers (B1 run-log/teardown order, B2 normal close leaving devices on,
     B3 CORE blocked by connect-or-start vs the 15 s HMI watch, B4 holes in the fence).
   - The fixes that need no decision, going into revision 5.
   - **12 decisions for the user**, each with a recommended option A and a *Choice* column.
   - A proposed 4-phase plan: rename `pypts.hal` → `pyhal`; server + client; PyPTS
     integration; View → HAL.
2. **Teardown and closing — every path, today and in rev 4**
   https://claude.ai/artifact/M12WpvrtULC7vNWi7Tx5uK
   - The close sequence today (checked in the code), 15 scenarios, the 14 close-path
     timeouts, what revision 4 changes.
   - **7 simplification candidates (S1–S7)** with a *Verdict* column. The user found the
     teardown/close handling over-complicated and wants it simplified.

Findings from that walk-through worth remembering:
- Closing the app mid-run gives the run only 2 s (`SEQUENCE_JOIN_TIMEOUT_S`) before it is
  abandoned and the separate 16 s abandon ladder takes over.
- Driver processes do not ignore Ctrl+C: a Ctrl+C in the launcher console tears every
  device down from inside, mid-run (`connection_driver.py` `driver_process_main` `finally`).
- Closing the console window may end the driver processes without teardown — reasoning
  only, not tested.

## Next steps

1. Read both docs, including the user's answers, verdicts and comments.
2. Clarify anything open with the user.
3. Write revision 5 of the spec from those answers; have it re-checked.
4. Write the implementation plan, phased.

## Drift noticed, not fixed

- `CLAUDE.md` still lists `usage_manual.html` as being in the repo root; it is in
  `docs/Usage_manuals/`.
- The spec's §12.3 note about CLAUDE.md drift (three manuals, a `spikes/**` glob) is stale.
