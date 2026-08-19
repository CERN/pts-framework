# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the CLI HMI (src/pypts/hmi/cli/).

Mostly placeholders declaring intended coverage. The CLI runs in the
launcher process; only the GUI keeps a process boundary.
"""

import queue

import pytest

from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import LoadRecipe, ShutdownRequested, StartSequence
from pypts.messages.run_events import StopSequence

PLACEHOLDER = "placeholder - test not implemented yet"


def test_known_commands_are_dispatched_to_core(monkeypatch):
    """Each shell verb sends its message; `stop_sequence` aborts the run while
    plain `stop` stays an exit alias."""
    from pypts.hmi.cli.cli import CLI

    outbox: queue.Queue = queue.Queue()
    inbox: queue.Queue = queue.Queue()
    cli = CLI(QueueWrapper(outbox), QueueWrapper(inbox))

    lines = iter(
        [
            "load_recipe recipes/wait_recipe.yml",
            "start_sequence Main",
            "stop_sequence",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(lines))
    cli._command_loop()

    sent = []
    while True:
        try:
            sent.append(outbox.get_nowait())
        except queue.Empty:
            break
    assert sent == [
        LoadRecipe(recipe_path="recipes/wait_recipe.yml"),
        StartSequence(sequence_name="Main"),
        StopSequence(),
        ShutdownRequested(),
    ]


@pytest.mark.skip(reason=PLACEHOLDER)
def test_unknown_command_is_reported_without_crashing():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_eof_on_stdin_is_treated_as_exit():
    """Non interactive stdin - a pipe or a CI run - must shut down cleanly."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_stop_from_core_ends_the_cli_without_waiting_for_input():
    """Today the main thread is parked in input() and only notices after Enter."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_exit_codes_follow_the_specification():
    """0/1/2/3 per the CLI module page."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_version_flag_prints_the_package_version():
    ...
