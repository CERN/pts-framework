<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# hardware_layer — HAL stub

`hal.py` is an empty stub. No functionality is implemented here yet.

## Planned role (Phase 3+)

The HAL will own device-lifecycle management: opening and closing connections to physical
hardware (SSH sessions, instrument drivers, serial ports). Step types that need a
persistent connection (`SSHConnectStep`, `SSHCloseStep` from the old engine) will be
re-expressed as HAL operations rather than step types.

The HAL runs inside the Core process and is accessed by the step layer via the `Runtime`
object's device seam (not yet designed).

## Current state

`hal.py` contains only a module docstring. Nothing imports it.

## Roadmap

Phase 3. See `resources/roadmap/pypts_roadmap.md` for the planned design.
