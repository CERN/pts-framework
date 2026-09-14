.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Architecture
============

**Two processes, threads inside the engine.**

The launcher (``python -m pypts``) creates two processes and a Logger:

- **CORE process** — runs the Sequencer and Report as threads; owns all execution state.
- **HMI process** — GUI (PySide6) or CLI; the operator-facing frontend.
- **Logger process** — single writer of the run log.

All communication is message-based. Modules never call each other and never touch
queues directly. Every message is a typed dataclass on a ``QueueWrapper``. The HMI↔CORE
boundary is the only one that crosses a process boundary (pickled); the four
engine links (CORE↔Sequencer, CORE↔Report, heartbeats, Logger) are plain
``queue.Queue`` threads.

Layout::

   src/pypts/
     launcher/startup.py      entry point; creates queues, spawns Logger + CORE + HMI
     core/core.py             mediator: routes every link, manages Sequencer + Report threads
     sequencer/               event loop + execute_sequence(); runs sequences on a worker thread
     recipe/ step/            recipe data layer + step types (ported from old_code)
     report/                  incremental CSV + HTML, one folder per run
     hmi/hmi_client.py        protocol half every frontend shares
     hmi/cli/  hmi/gui/       CLI and PySide6 GUI
     messages/                all typed message dataclasses, one module per link
     config_handler/          per-user config.ini (INI template, versioned, never migrated)
     logger/log.py            Logger process: single log-file writer
     hardware_layer/hal.py    HAL stub (Phase 3+)

Key design rules
----------------

- A sequence runs on its own worker thread inside CORE. The event loop keeps
  turning while it does (heartbeats, ``StopSequence`` delivery).
- Every ``match``/``case`` handler is closed with ``unhandled()``, so a forgotten
  message raises instead of being silently dropped.
- ``@catch_and_report_errors()`` swallows and reports (event loops);
  ``@report_and_reraise()`` reports and re-raises (step execution layer).
- Multiprocessing is pinned to ``"spawn"`` on every platform (plan 005).

For the full message catalogue see ``src/pypts/messages/messages.md``.
For module-level detail see the ``<module>.md`` context files beside each module.
