# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The CORE <-> Report link. The Report is a thread of the Core process.

Most of the CORE->Report traffic is run events forwarded from the Sequencer:
RunStarted opens the run's folder and its incremental CSV, each StepExecuted
appends one row, RunFinished closes the CSV, and the GenerateReport CORE sends
right after it turns the rows into the run's HTML report. The Report answers
with ReportGenerated, which CORE relays to the operator as ReportReady.

The link never leaves the Core process, which is why it may carry StepExecuted
- the rich step record the HMI boundary must never see.
"""

from dataclasses import dataclass

from pypts.messages.common_messages import Heartbeat, ModuleError
from pypts.messages.run_events import RunFinished, RunStarted, SequenceStarted, StepExecuted

# --- CORE -> Report: commands -------------------------------------------------


# Sender: core.py handle_sequencer_message(), right after it forwards
# RunFinished. Receiver: report.py generate_report().
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


# Sender: report.py generate_report(). Receiver: core.py
# handle_report_message(), which relays it to the operator as ReportReady.
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

CoreToReport = (
    RunStarted
    | SequenceStarted
    | StepExecuted
    | RunFinished
    | GenerateReport
    | ExportReport
    | StopReport
)

ReportToCore = ReportStopped | ReportGenerated | ReportExported | Heartbeat | ModuleError
