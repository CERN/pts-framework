# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for climatic chamber utilities."""

import pytest
from pypts.clim_chamber import calculate_chamber_steps


class TestCalculateChamberSteps:
    def test_single_step(self):
        result = calculate_chamber_steps(
            t_steps=1, t_step=5, t_min=20,
            rh_steps=1, rh_step=10, rh_min=50,
        )
        assert result["temperatures"] == [20]
        assert result["humidities"] == [50]

    def test_multiple_temperature_steps(self):
        result = calculate_chamber_steps(
            t_steps=3, t_step=10, t_min=0,
            rh_steps=1, rh_step=10, rh_min=50,
        )
        assert result["temperatures"] == [0, 10, 20]
        assert result["humidities"] == [50, 50, 50]

    def test_multiple_humidity_steps(self):
        result = calculate_chamber_steps(
            t_steps=1, t_step=5, t_min=20,
            rh_steps=3, rh_step=10, rh_min=30,
        )
        assert result["temperatures"] == [20, 20, 20]
        assert result["humidities"] == [30, 40, 50]

    def test_grid_pattern(self):
        """Each temperature is tested with each humidity - grid of combinations."""
        result = calculate_chamber_steps(
            t_steps=2, t_step=10, t_min=20,
            rh_steps=3, rh_step=5, rh_min=40,
        )
        # 2 temps x 3 humidities = 6 total points
        assert len(result["temperatures"]) == 6
        assert len(result["humidities"]) == 6

        # First temperature (20) should be paired with all humidities
        assert result["temperatures"][:3] == [20, 20, 20]
        assert result["humidities"][:3] == [40, 45, 50]

        # Second temperature (30) with all humidities
        assert result["temperatures"][3:] == [30, 30, 30]
        assert result["humidities"][3:] == [40, 45, 50]

    def test_zero_steps(self):
        result = calculate_chamber_steps(
            t_steps=0, t_step=10, t_min=20,
            rh_steps=3, rh_step=5, rh_min=40,
        )
        assert result["temperatures"] == []
        assert result["humidities"] == []

    def test_negative_starting_temperature(self):
        result = calculate_chamber_steps(
            t_steps=3, t_step=10, t_min=-20,
            rh_steps=1, rh_step=5, rh_min=50,
        )
        assert result["temperatures"] == [-20, -10, 0]
