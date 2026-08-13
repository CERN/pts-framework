# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Step module (src/pypts/step/).

SKELETON ONLY - placeholders declaring intended coverage. step/ is currently
empty; the step implementations live in old_code/steps.py.

Two roadmap items shape this module: the eval() based step factory must be
replaced by a registry, and each step type should own its own schema.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_step_type_is_resolved_without_eval():
    """old_code builds steps with eval(step_type + "(**step_data)").

    That is arbitrary code execution driven by a recipe file.
    """


@pytest.mark.skip(reason=PLACEHOLDER)
def test_unknown_steptype_raises_a_clear_error_listing_available_types():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_each_step_type_declares_its_required_fields():
    """Feeds the verificator, the docs and the Recipe Creator toolbar from one source."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_step_result_captures_errors_with_traceback():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_steps_are_testable_standalone_with_a_fake_context():
    """"Tests executable stand-alone" is an explicit requirement in the spec."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_step_ids_are_stable_and_unique():
    ...
