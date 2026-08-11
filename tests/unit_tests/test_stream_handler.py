# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Stream Handler module (src/pypts/stream_handler/).

SKELETON ONLY - placeholders declaring intended coverage. StreamContainer plus
an XYGraph spike exist but are not integrated; Phase 3 promotes them.

Design constraint from the roadmap: bulk data (waveforms, acquisitions) never
travels through a message queue. In engine it is passed by reference; if it has
to reach the GUI, use shared memory or a file path handoff.
"""

import pytest

PLACEHOLDER = "placeholder - test not implemented yet"


@pytest.mark.skip(reason=PLACEHOLDER)
def test_streams_register_and_unregister():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_container_is_a_singleton_within_one_process():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_bulk_samples_never_cross_a_message_queue():
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_samples_are_persisted_to_the_configured_backend():
    """CSV first; TDMS and HDF5 later, through the same interface."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_ring_buffer_drops_oldest_when_full_and_says_so():
    ...
