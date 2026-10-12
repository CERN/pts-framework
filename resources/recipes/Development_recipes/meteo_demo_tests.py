# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The test functions meteo_demo.yml calls. A weather station on the internet,
reached exactly like a bench instrument: by logical name, through get_device().

Nothing here knows the station is a web API, which URL it calls or how its
answer is laid out - that is the driver's business
(src/pypts/hal/drivers/weather.py). Swap the [hardware.meteo1] section for a
real sensor whose driver offers the same verbs and these functions do not change.

Each function returns a dict; the recipe's `outputs` judge its keys.
"""

from pypts.hal import get_device


def cern_temperature():
    """The air temperature at CERN now, in degrees Celsius."""
    station = get_device("meteo1")
    return {"temperature_c": station.temperature()}


def cern_wind():
    """Wind speed and direction at CERN now."""
    reading = get_device("meteo1").current_conditions()
    return {
        "wind_speed_kmh": reading["wind_speed_kmh"],
        "wind_direction_deg": reading["wind_direction_deg"],
    }
