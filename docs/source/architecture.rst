.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Architecture
============

The launcher (``python -m pypts``) starts three processes, always with ``spawn``:

- **CORE** — the mediator. Runs the Sequencer and the Report as threads and owns all
  execution state. A sequence runs on a worker thread of its own, so the event loop
  keeps turning (heartbeats, stop, pause) while it does.
- **HMI** — the frontend: GUI (PySide6) or CLI.
- **Logger** — the single writer of the run log.

All communication is by typed dataclass messages on a ``QueueWrapper``. Modules never
call each other and never touch queues directly; everything goes through CORE, except
log records, which go straight to the Logger. Only the HMI↔CORE link crosses a process
boundary. Every message handler is a ``match`` closed with ``unhandled()``, so a
forgotten message raises instead of being silently dropped.

Where to read more:

- ``src/pypts/messages/messages.md`` — every link and message.
- ``src/pypts/<module>/<module>.md`` — the context file beside each module.
- ``pypts_implementation_status.html`` — status and roadmap.
