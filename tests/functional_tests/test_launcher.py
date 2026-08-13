# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Functional tests for booting and shutting the application down
(src/pypts/launcher/startup.py).

SKELETON ONLY - placeholders declaring intended coverage. These drive the real
entry point, `python -m pypts`, rather than importing modules.

Both platforms matter here. Windows spawns its child processes and Linux forks
them, which is where most of the platform differences in this project come
from, so anything asserted below should be asserted on both.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_cli_mode_boots_and_exits_with_code_zero():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_gui_mode_boots_offscreen_and_exits_with_code_zero():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_every_expected_process_is_started():
    """launcher -> {Logger, Core, HMI}, Core -> {Sequencer, Report}."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_no_process_is_left_behind_after_exit():
    """Known bug: Core is terminated abruptly and its submodules are orphaned.

    They keep spinning their event loops with no parent.
    """


@pytest.mark.skip(reason=PLACEHOLDER)
def test_shutdown_is_ordered_core_before_logger():
    """Otherwise the records that explain the shutdown never reach the file."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_core_starts_promptly_when_stdin_is_a_pipe():
    """Open finding: with a redirected pipe on stdin the spawned Core child does

    not reach core_main until the launcher's input() unblocks. Reproduces on
    unmodified HEAD, so it predates the logger work. Matters for CI.
    """
