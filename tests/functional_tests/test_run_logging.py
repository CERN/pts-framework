# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Functional tests for logging across a whole run.

SKELETON ONLY - placeholders declaring intended coverage.

These are the end to end counterpart of tests/unit_tests/test_logger.py: they
assert on the artefact a run leaves behind rather than on the module. The
guarantee is one file per run, written by exactly one process, with no record
lost and none torn - on Windows and on Linux.

Background: before the single writer design, several processes appended to the
same file. On Windows that costs 0.5 to 15 percent of records per run, because
the C runtime emulates append as seek-then-write; on Linux O_APPEND is atomic
but records larger than the stream buffer can still interleave.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_a_run_produces_exactly_one_log_file():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_every_module_appears_in_that_file():
    """MainProcess, Core, Sequencer, Report and the HMI."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_no_line_in_the_log_is_malformed():
    """Torn records are the symptom of more than one writer."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_no_record_is_lost_under_concurrent_load():
    """Emit a known number of records from every process and count them back."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_log_file_name_is_decided_once_not_derived_from_the_clock_per_process():
    """The old scheme raced: processes crossing a second boundary split the run."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_the_log_names_itself_and_the_configuration_it_used():
    """
    The first records of a run identify the run log's own path and the
    config.ini it was read from. A log is routinely copied off the machine that
    wrote it, and both paths are unrecoverable once it has been - the Logger
    announces the file name on the console only, because it is the one component
    that cannot log about logging.
    """


@pytest.mark.skip(reason=PLACEHOLDER)
def test_cli_mode_keeps_stdout_clean():
    """Child processes must not print over the interactive prompt."""


@pytest.mark.skip(reason=PLACEHOLDER)
def test_non_ascii_messages_do_not_raise_on_a_non_utf8_locale():
    ...
