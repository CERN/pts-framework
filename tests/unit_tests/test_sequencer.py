# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Sequencer module (src/pypts/sequencer/).

SKELETON ONLY - placeholders declaring intended coverage. The execution engine
still lives in src/pypts/old_code/; run_sequence() is a stub. Phase 1 of
resources/roadmap/pypts_roadmap.md ports it here.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_run_sequence_executes_steps_in_order():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_each_step_result_is_reported_to_core():
    """Per-step STEP_RESULT events, so an HMI can update live."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_a_failing_step_produces_a_step_result_not_a_silent_continue():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_stop_aborts_a_running_sequence():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_sequence_result_is_sent_once_at_the_end():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_sequencer_sends_heartbeats_while_running_a_sequence():
    """A long step must not look like a dead module."""
    ...
