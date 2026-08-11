# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the CLI HMI (src/pypts/hmi/cli/).

SKELETON ONLY - placeholders declaring intended coverage. The CLI runs in the
launcher process; only the GUI keeps a process boundary.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_known_commands_are_dispatched_to_core():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_unknown_command_is_reported_without_crashing():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_eof_on_stdin_is_treated_as_exit():
    """Non interactive stdin - a pipe or a CI run - must shut down cleanly."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_stop_from_core_ends_the_cli_without_waiting_for_input():
    """Today the main thread is parked in input() and only notices after Enter."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_exit_codes_follow_the_specification():
    """0/1/2/3 per the CLI module page."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_version_flag_prints_the_package_version():
    ...
