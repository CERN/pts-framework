"""
Unit tests for the Open-Meteo driver (src/pypts/hal/drivers/weather.py),
in-process, with urllib's urlopen replaced - no network is needed.
"""

import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from pypts.hal import DriverError
from pypts.hal.base_driver import operations_of
from pypts.hal.drivers import weather as weather_module
from pypts.hal.drivers.weather import OpenMeteoDriver

CURRENT = {
    "current": {
        "time": "2026-10-12T09:45",
        "interval": 900,
        "temperature_2m": 7.6,
        "relative_humidity_2m": 86,
        "surface_pressure": 969.1,
        "wind_speed_10m": 1.8,
        "wind_direction_10m": 180,
    }
}

HOURLY = {
    "hourly": {
        "time": ["2026-10-12T09:00", "2026-10-12T10:00", "2026-10-12T11:00"],
        "temperature_2m": [4.8, 8.5, 11.3],
        "wind_speed_10m": [1.8, 1.8, 2.9],
    }
}


class FakeWeb:
    """Stands in for urlopen: records each URL, answers with the next body."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append((url, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return io.BytesIO(answer)
        return io.BytesIO(json.dumps(answer).encode("utf-8"))

    def query(self, index=-1):
        """The query of one recorded URL, one value per key."""
        query = parse_qs(urlparse(self.urls[index][0]).query)
        return {key: values[0] for key, values in query.items()}


@pytest.fixture
def web(monkeypatch):
    def install(*answers):
        fake = FakeWeb(*answers)
        monkeypatch.setattr(weather_module.urllib.request, "urlopen", fake)
        return fake

    return install


def test_the_weather_driver_is_an_other_with_its_own_verbs():
    assert OpenMeteoDriver.DEVICE_TYPE == "Other"
    assert operations_of(OpenMeteoDriver) == [
        "current_conditions",
        "hourly_forecast",
        "temperature",
        "wind_speed",
    ]


def test_connect_defaults_to_cern_and_takes_one_reading(web):
    fake = web(CURRENT)
    OpenMeteoDriver().connect({})

    query = fake.query()
    assert query["latitude"] == "46.23"
    assert query["longitude"] == "6.05"
    assert "current" in query
    assert fake.urls[0][1] == 10.0


def test_connect_reads_place_and_timeout(web):
    fake = web(CURRENT, CURRENT)
    driver = OpenMeteoDriver()
    driver.connect(
        {"latitude": "46.55", "longitude": "7.98", "place": "Jungfraujoch", "http_timeout_s": "3"}
    )

    reading = driver.current_conditions()
    assert reading["place"] == "Jungfraujoch"
    assert fake.query()["latitude"] == "46.55"
    assert fake.urls[-1][1] == 3.0


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"latitude": "north"}, "latitude must be a number, not 'north'"),
        ({"latitude": "91"}, "latitude must be between -90 and 90"),
        ({"longitude": "-181"}, "longitude must be between -180 and 180"),
        ({"http_timeout_s": "soon"}, "http_timeout_s must be a number"),
    ],
)
def test_bad_settings_are_refused_before_any_request(web, settings, message):
    fake = web()
    with pytest.raises(DriverError, match=message):
        OpenMeteoDriver().connect(settings)
    assert fake.urls == []


def test_current_conditions_renames_the_readings(web):
    web(CURRENT, CURRENT)
    driver = OpenMeteoDriver()
    driver.connect({})

    assert driver.current_conditions() == {
        "place": "46.23, 6.05",
        "time": "2026-10-12T09:45",
        "temperature_c": 7.6,
        "relative_humidity_pct": 86,
        "pressure_hpa": 969.1,
        "wind_speed_kmh": 1.8,
        "wind_direction_deg": 180,
    }


def test_temperature_and_wind_speed_are_single_readings(web):
    web(CURRENT, CURRENT, CURRENT)
    driver = OpenMeteoDriver()
    driver.connect({})

    assert driver.temperature() == 7.6
    assert driver.wind_speed() == 1.8


def test_hourly_forecast_gives_one_entry_per_hour(web):
    fake = web(CURRENT, HOURLY)
    driver = OpenMeteoDriver()
    driver.connect({})

    forecast = driver.hourly_forecast(3)
    assert fake.query()["forecast_hours"] == "3"
    assert forecast == [
        {"time": "2026-10-12T09:00", "temperature_c": 4.8, "wind_speed_kmh": 1.8},
        {"time": "2026-10-12T10:00", "temperature_c": 8.5, "wind_speed_kmh": 1.8},
        {"time": "2026-10-12T11:00", "temperature_c": 11.3, "wind_speed_kmh": 2.9},
    ]


@pytest.mark.parametrize("hours", [0, 385])
def test_a_forecast_length_out_of_range_is_refused(web, hours):
    web(CURRENT)
    driver = OpenMeteoDriver()
    driver.connect({})

    with pytest.raises(DriverError, match="A forecast is 1 to 384 hours"):
        driver.hourly_forecast(hours)


def test_an_unreachable_station_fails_connect(web):
    web(urllib.error.URLError("getaddrinfo failed"))
    driver = OpenMeteoDriver()

    with pytest.raises(DriverError, match=r"Open-Meteo could not be reached: .*getaddrinfo failed"):
        driver.connect({})
    with pytest.raises(DriverError, match="not connected"):
        driver.temperature()


def test_a_refused_request_shows_open_meteo_s_reason(web):
    body = io.BytesIO(json.dumps({"error": True, "reason": "Latitude out of range"}).encode())
    refused = urllib.error.HTTPError("https://x", 400, "Bad Request", None, body)  # type: ignore[arg-type]
    web(refused)

    with pytest.raises(DriverError, match=r"refused the request \(400\): Latitude out of range"):
        OpenMeteoDriver().connect({})


def test_an_answer_that_is_not_json_is_a_driver_error(web):
    web(b"<html>maintenance</html>")

    with pytest.raises(DriverError, match="not JSON"):
        OpenMeteoDriver().connect({})


def test_an_answer_missing_a_reading_is_a_driver_error(web):
    incomplete = {"current": {"time": "2026-10-12T09:45", "temperature_2m": 7.6}}
    web(incomplete)

    with pytest.raises(DriverError, match="without 'relative_humidity_2m'"):
        OpenMeteoDriver().connect({})


def test_teardown_is_harmless_and_disconnects(web):
    web(CURRENT)
    driver = OpenMeteoDriver()
    driver.teardown()
    driver.connect({})
    driver.teardown()

    with pytest.raises(DriverError, match="not connected"):
        driver.current_conditions()
