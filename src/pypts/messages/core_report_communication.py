# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The CORE <-> Report link. The Report is a thread of the Core process.

Four of this link's six messages are marked `NOT SENT YET` - the marker used
throughout `messages/`, meaning the receiving end is written and works and
nothing constructs the message. This is the emptiest link in the system: today
the only thing CORE ever puts on it is `StopReport`, so the Report thread runs
its event loop, heartbeats and resolves its output directory without ever being
asked for anything. Both ends unblock together when the report layer is ported -
roadmap Phase 4, and the CSV/HTML logic to port is in `old_code/report.py`.
"""

from dataclasses import dataclass

from pypts.messages.common_messages import Heartbeat, ModuleError

# --- CORE -> Report: commands -------------------------------------------------


# NOT SENT YET - receiver: report.py generate_report(). CORE has no trigger for
# this at all: it should send it on RunFinished, which is itself never sent.
@dataclass(frozen=True, slots=True)
class GenerateReport:
    """Build the report for the run that just finished."""


# NOT SENT YET - receiver: report.py export_report(). No trigger in CORE either;
# the operator command that would ask for it does not exist yet.
@dataclass(frozen=True, slots=True)
class ExportReport:
    """Write the generated report out in its configured format."""


@dataclass(frozen=True, slots=True)
class StopReport:
    """Shut the module down. Report answers with ReportStopped."""


# --- Report -> CORE: events ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportStopped:
    """The Report's event loop has ended."""


# NOT SENT YET - receiver: core.py handle_report_message(), which turns it into
# a StatusChanged for the operator. Sent once generate_report() is more than a
# warning.
@dataclass(frozen=True, slots=True)
class ReportGenerated:
    """A report was built. `report_path` is absolute."""

    report_path: str


# NOT SENT YET - receiver: core.py handle_report_message(), same treatment.
@dataclass(frozen=True, slots=True)
class ReportExported:
    """A report was written out. `report_path` is absolute."""

    report_path: str


# --- The link ------------------------------------------------------------------

CoreToReport = GenerateReport | ExportReport | StopReport

ReportToCore = ReportStopped | ReportGenerated | ReportExported | Heartbeat | ModuleError
