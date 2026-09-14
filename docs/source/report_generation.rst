.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Report Generation
=================

The Report is a **thread inside the CORE process**, not a separate daemon. It receives
typed messages from CORE via a ``QueueWrapper`` (the CORE↔Report link).

Run lifecycle
-------------

1. CORE receives ``RunSequence`` → sends ``RunStarted`` to the Report thread.
2. Report creates ``<reports_dir>/<timestamp>_<recipe_name>/report.csv`` and writes the
   CSV header.
3. As steps finish, CORE forwards ``StepFinished`` events → Report appends a row.
4. CORE forwards ``RunFinished`` → Report records the overall result.
5. CORE sends ``GenerateReport`` → Report writes ``report.html`` and sends
   ``ReportReady`` back to CORE, which forwards it to the HMI.
6. On shutdown, CORE holds ``StopReport`` until the Sequencer has stopped (plan 002),
   so the aborted run's tail (CSV rows + HTML) is always written before the Report stops.

Output location
---------------

Configured in ``config.ini`` under ``[paths] reports_dir``. Each run creates its own
subfolder: ``<reports_dir>/<YYYYMMDD_HHMMSS>_<recipe_name>/``.

Files per run:

- ``report.csv`` — one row per step; written incrementally.
- ``report.html`` — generated after the run; styled summary.

Difference from old architecture
---------------------------------

The old architecture used a ``report_listener`` daemon thread reading a ``SimpleQueue``
and writing a single ``./pts_reports/report.csv`` (overwritten each run). The new
architecture uses a per-run folder, typed messages, and the Report is stopped cleanly
via the message protocol rather than a sentinel object on the queue.
