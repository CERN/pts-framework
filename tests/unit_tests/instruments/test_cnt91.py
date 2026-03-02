# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the pypts CNT-91 driver extensions.

These tests cover only the behaviour *added* by the pypts subclass:

* :meth:`~pypts.instruments.pendulum.CNT91.buffer_frequency_time_series`
  with the *trigger_level* keyword argument.
* :meth:`~pypts.instruments.pendulum.CNT91.configure_pulse_output`.

The full upstream CNT-91 protocol (gate time, continuous mode, arming,
buffer readout, etc.) is tested by pymeasure's own test suite which runs
against ``pymeasure.instruments.pendulum.CNT91``.  Since the pypts class
inherits that driver unchanged, there is no value in duplicating those tests
here.

All tests use :func:`pymeasure.test.expected_protocol`, which verifies the
exact byte sequences sent to and received from the instrument without
requiring physical hardware.
"""

import pytest
from pymeasure.test import expected_protocol

from pypts.instruments.pendulum import CNT91


# ---------------------------------------------------------------------------
# buffer_frequency_time_series — trigger_level extension
# ---------------------------------------------------------------------------

class TestBufferFrequencyTimeSeriesWithTriggerLevel:
    """Tests for the trigger_level extension of buffer_frequency_time_series."""

    def test_trigger_level_channel_a(self):
        """A trigger level on channel A prefixes ':INP1:LEV <v>' to the sequence."""
        with expected_protocol(
            CNT91,
            [
                (b":INP1:LEV 2.4", None),
                (b"*CLS", None),
                (b"FORM ASC", None),
                (b":CONF:ARR:FREQ:BTB 10,(@1)", None),
                (b"INIT:CONT 0.0", None),
                (b":ACQ:APER 0.1", None),
                (b":INIT", None),
            ],
        ) as inst:
            inst.buffer_frequency_time_series("A", 10, gate_time=0.1, trigger_level=2.4)

    def test_trigger_level_channel_b(self):
        """A trigger level on channel B prefixes ':INP2:LEV <v>' to the sequence."""
        with expected_protocol(
            CNT91,
            [
                (b":INP2:LEV -0.5", None),
                (b"*CLS", None),
                (b"FORM ASC", None),
                (b":CONF:ARR:FREQ:BTB 10,(@2)", None),
                (b"INIT:CONT 0.0", None),
                (b":ACQ:APER 0.1", None),
                (b":INIT", None),
            ],
        ) as inst:
            inst.buffer_frequency_time_series("B", 10, gate_time=0.1, trigger_level=-0.5)

    def test_no_trigger_level_sends_no_inp_command(self):
        """Without trigger_level, no ':INP' command is sent."""
        with expected_protocol(
            CNT91,
            [
                (b"*CLS", None),
                (b"FORM ASC", None),
                (b":CONF:ARR:FREQ:BTB 10,(@1)", None),
                (b"INIT:CONT 0.0", None),
                (b":ACQ:APER 0.1", None),
                (b":INIT", None),
            ],
        ) as inst:
            inst.buffer_frequency_time_series("A", 10, gate_time=0.1)

    def test_trigger_level_unsupported_channel_raises(self):
        """trigger_level on a channel without input level control raises ValueError."""
        with expected_protocol(CNT91, []) as inst:
            with pytest.raises(ValueError, match="channels 'A' and 'B'"):
                inst.buffer_frequency_time_series(
                    "INTREF", 10, gate_time=0.1, trigger_level=1.0
                )


# ---------------------------------------------------------------------------
# configure_pulse_output
# ---------------------------------------------------------------------------

class TestConfigurePulseOutput:
    """Tests for the configure_pulse_output method."""

    @pytest.mark.parametrize("enabled, stat", [(True, "ON"), (False, "OFF")])
    def test_enabled_flag(self, enabled, stat):
        """The enabled flag maps to 'ON'/'OFF' in the OUTP:PULS:STAT command."""
        with expected_protocol(
            CNT91,
            [
                (f"OUTP:PULS:STAT {stat}".encode(), None),
                (b"OUTP:PULS:SOUR TIME", None),
                (b"OUTP:PULS:PER 1.0", None),
                (b"OUTP:PULS:WIDT 0.01", None),
            ],
        ) as inst:
            inst.configure_pulse_output(enabled=enabled)

    def test_custom_period_width_source(self):
        """Custom period, width, and source are forwarded verbatim."""
        with expected_protocol(
            CNT91,
            [
                (b"OUTP:PULS:STAT ON", None),
                (b"OUTP:PULS:SOUR MEAS", None),
                (b"OUTP:PULS:PER 2.0", None),
                (b"OUTP:PULS:WIDT 0.5", None),
            ],
        ) as inst:
            inst.configure_pulse_output(period=2.0, width=0.5, source="MEAS")

    def test_width_equal_to_period_raises(self):
        """width == period is rejected before any command is sent."""
        with expected_protocol(CNT91, []) as inst:
            with pytest.raises(ValueError, match="strictly less than"):
                inst.configure_pulse_output(period=1.0, width=1.0)

    def test_width_greater_than_period_raises(self):
        """width > period is rejected before any command is sent."""
        with expected_protocol(CNT91, []) as inst:
            with pytest.raises(ValueError, match="strictly less than"):
                inst.configure_pulse_output(period=0.01, width=1.0)
