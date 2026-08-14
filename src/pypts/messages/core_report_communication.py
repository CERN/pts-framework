# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""The CORE <-> Report link. The Report is a thread of the Core process."""

from dataclasses import dataclass

from pypts.messages.common_messages import Heartbeat, ModuleError

# --- CORE -> Report: commands -------------------------------------------------


@dataclass(frozen=True, slots=True)
class GenerateReport:
    """Build the report for the run that just finished."""


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


@dataclass(frozen=True, slots=True)
class ReportGenerated:
    """A report was built. `report_path` is absolute."""

    report_path: str


@dataclass(frozen=True, slots=True)
class ReportExported:
    """A report was written out. `report_path` is absolute."""

    report_path: str


# --- The link ------------------------------------------------------------------

CoreToReport = GenerateReport | ExportReport | StopReport

ReportToCore = ReportStopped | ReportGenerated | ReportExported | Heartbeat | ModuleError
