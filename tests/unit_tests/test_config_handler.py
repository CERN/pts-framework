# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Config Handler module (src/pypts/config_handler/).

SKELETON ONLY - placeholders declaring intended coverage.

Two open roadmap items sit here: the config currently lives in the temp
directory (easy to lose, awkward for benches with fixed configs), and it is
rewritten by every process that imports the handler rather than written once by
the launcher. config_template.ini also still hardcodes POSIX paths under
[Paths] (/tmp/pypts/...), which are wrong on Windows.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_config_is_created_from_the_template_when_missing():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_read_config_key_returns_none_for_an_unknown_key():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_operating_system_section_is_filled_in_at_creation():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_no_path_in_the_template_is_platform_specific():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_config_is_written_once_by_the_launcher_and_read_only_elsewhere():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_user_edits_survive_a_restart():
    ...
