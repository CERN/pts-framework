# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Hardware Abstraction Layer (src/pypts/hardware_layer/).

SKELETON ONLY - placeholders declaring intended coverage. hal.py is currently a
single comment line; Phase 5 of the roadmap builds it.

Agreed design: the HAL is a plain library imported by the Sequencer - no
process, no event loop, no queue - which is also what keeps it usable
standalone outside the framework.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_device_base_defines_connect_teardown_recover():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_family_bases_expose_the_standard_verbs():
    """PowerSupply, DAQ, Load and friends."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_devices_are_resolved_by_logical_name_from_the_config():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_hal_is_importable_without_the_framework_running():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_a_driver_only_depends_on_the_stable_api():
    """Drivers import pypts.api, never pypts.core."""
    ...
