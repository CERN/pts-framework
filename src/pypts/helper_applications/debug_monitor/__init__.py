# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Debug Monitor - a developer tool that reads the run log.

Run it beside a framework started at DEBUG:

    python -m pypts --mode cli --log-level DEBUG
    python -m pypts.helper_applications.debug_monitor

It shows every message on every link as it happens, which modules are alive, and
when their heartbeats last arrived. It gets all of that from one place: the run
log file the Logger is already writing.

Why a log reader rather than a tap
----------------------------------

A `--mode debug` console existed here once and was removed, because it gave the
software two shapes - the product, and the product plus a tap. Anything only
visible in the second shape is invisible on the machine where it matters. The
message trace moved into the run log instead (roadmap 1.2), and this tool is the
consequence taken seriously: the framework has no idea it exists, and starting it
changes nothing about a run.

What that buys, beyond keeping one build:

  - Ordering is free. Every process funnels its records through the single-writer
    Logger, so the order of the file is the order of the system. A side channel
    would have had to reconstruct that from timestamps taken in four processes.
  - Replay is free. The same parser reads a run that finished last week.

What it costs is written down in trace_parser.py: the payload is `repr()` text,
so per-field structure is gone, and nothing is visible at all unless the run was
started at DEBUG.

The rule that keeps this honest
-------------------------------

**Nothing in `core/`, `sequencer/`, `report/`, `messages/`, `logger/` or `hmi/`
may import this package.** It depends on the framework; the framework must never
depend on it. If a debug type starts appearing in product logic, the tooling has
grown back into the framework and that is a defect, not a feature.

Layout
------

  trace_parser.py  the run log's grammar: text -> LogLine -> TraceEvent. Pure.
  liveness.py      folds parsed lines into who is alive. Pure.
  log_source.py    follows a growing file, and finds the newest one.
  trace_model.py   the Qt model behind the trace table.
  main_window.py   the window itself.
  __main__.py      the entry point.

The first two import no Qt and no running framework, which is why the tests for
them need neither.
"""
