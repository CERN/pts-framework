<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# stream_handler — placeholder (not implemented)

**No code.** The package holds an empty `__init__.py` and this file. Nothing imports it.
Building it is **roadmap Phase 3** (`pypts_implementation_status.html` → *Phase 3 — Frontends
to spec*).

## Planned role

A singleton stream layer for live data from instruments during a run — continuous readings,
acquisitions — CSV storage first (TDMS / HDF5 later, as storage-backend plugins), fed by an
acquisition logger channel, and drawn live by the GUI's XYGraph widget.

**Design constraint:** bulk data never travels through a message queue. Inside the engine it
is passed by reference; if it must reach the GUI (another process), use shared memory or a
file-path handoff.

## Spikes

Two unintegrated spikes were moved out of the shipping package because nothing imported them
and both were broken at import:

- `spikes/stream_handler/StreamContainer.py` — the singleton container (it executed and
  printed at import).
- `spikes/GUI/XYGraph/` — the live-plot widget (undefined names that raise if reached).

Both need **rewriting rather than moving back**; they are reference material, not code to
promote as is.
