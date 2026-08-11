# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Functional tests for running a recipe end to end.

SKELETON ONLY - placeholders declaring intended coverage. Nothing here can pass
until the engine is ported out of src/pypts/old_code/ (Phase 1).

The characterization test below is the safety net for that port: record what
old_code produces for an example recipe *before* moving code, then assert the
new engine produces the same. Phase 0 of resources/roadmap/pypts_roadmap.md.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_example_recipe_runs_from_load_to_report():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_results_match_the_old_code_baseline():
    """Characterization: same recipe, same CSV rows as the previous engine."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_a_failing_step_is_reported_and_the_run_ends_as_configured():
    """Continue or abort per recipe configuration - never silently."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_a_recipe_that_fails_validation_is_never_executed():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_user_interaction_step_works_across_the_hmi_process_boundary():
    """The old trick of passing a live SimpleQueue inside an event cannot survive it.

    Needs a request/response message pair.
    """
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_run_artifacts_are_collected_in_one_folder():
    """Report, logs and raw data together, traceable to the run."""
    ...
