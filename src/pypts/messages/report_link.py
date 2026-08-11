# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The CORE <-> Report link.

A straight port of the old enums, with one change: the two notifications now
carry the path of the artefact they produced. They used to carry nothing at all,
which meant CORE could learn that a report existed but not where - and the CLI
has to print that path to be useful.
"""

from dataclasses import dataclass

from pypts.messages.common import Heartbeat, ModuleError

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
