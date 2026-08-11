# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Report module (src/pypts/report/).

SKELETON ONLY - placeholders declaring intended coverage. generate_report() and
export_report() are stubs; the CSV/HTML logic is in old_code/report.py.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_generate_writes_the_intermediate_result_file():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_results_are_written_incrementally_not_only_at_the_end():
    """A run that dies mid-sequence must still leave the results it produced."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_export_produces_html_from_the_intermediate_file():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_artifacts_are_grouped_in_one_run_folder():
    """Report, logs and raw data per run, in a single traceable folder."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_report_output_path_comes_from_the_config_handler():
    """Also: generated HTML must not land in the repository."""
    ...
