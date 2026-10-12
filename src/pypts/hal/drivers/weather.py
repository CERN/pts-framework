"""
Open-Meteo - a weather station on the internet, read like an instrument.

The showcase driver: no hardware, no API key, standard library only, and yet
everything a real instrument driver does - settings read from its
[hardware.<name>] section, a check at connect(), readings with units fixed by
the driver, and one readable DriverError for every way the far end can fail.
A new driver can follow its shape as well as ssh.py's.

Keys of its [hardware.<name>] section (all text):

    latitude         default 46.23  (CERN, Meyrin)
    longitude        default 6.05
    place            optional label, shown in the readings; default "lat, lon"
    http_timeout_s   default 10, longest one request may take

Data by Open-Meteo (https://open-meteo.com), CC BY 4.0.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pypts.hal.base_driver import DriverError
from pypts.hal.device_types import Other

logger = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_LATITUDE = 46.23
DEFAULT_LONGITUDE = 6.05
DEFAULT_HTTP_TIMEOUT_S = 10.0

#: Open-Meteo's names for the current readings, and the names this driver gives them.
#: The units are Open-Meteo's defaults: degC, %, hPa, km/h, degrees.
CURRENT_FIELDS = {
    "temperature_2m": "temperature_c",
    "relative_humidity_2m": "relative_humidity_pct",
    "surface_pressure": "pressure_hpa",
    "wind_speed_10m": "wind_speed_kmh",
    "wind_direction_10m": "wind_direction_deg",
}

#: The same, for each hour of the forecast.
HOURLY_FIELDS = {
    "temperature_2m": "temperature_c",
    "wind_speed_10m": "wind_speed_kmh",
}

#: The longest forecast Open-Meteo gives (16 days).
MAX_FORECAST_HOURS = 384


class OpenMeteoDriver(Other):
    """The weather at one place, from the Open-Meteo forecast API."""

    def __init__(self) -> None:
        self._latitude = DEFAULT_LATITUDE
        self._longitude = DEFAULT_LONGITUDE
        self._place = ""
        self._timeout_s = DEFAULT_HTTP_TIMEOUT_S
        self._connected = False

    def connect(self, config: dict[str, str]) -> None:
        self._latitude = _read_number(config, "latitude", DEFAULT_LATITUDE)
        self._longitude = _read_number(config, "longitude", DEFAULT_LONGITUDE)
        if not -90.0 <= self._latitude <= 90.0:
            raise DriverError(
                f"Open-Meteo latitude must be between -90 and 90, not {self._latitude}."
            )
        if not -180.0 <= self._longitude <= 180.0:
            raise DriverError(
                f"Open-Meteo longitude must be between -180 and 180, not {self._longitude}."
            )
        self._timeout_s = _read_number(config, "http_timeout_s", DEFAULT_HTTP_TIMEOUT_S)
        place = config.get("place", "").strip()
        if place:
            self._place = place
        else:
            self._place = f"{self._latitude}, {self._longitude}"
        # One reading now, the way an instrument driver asks *IDN?: a station that
        # cannot be reached fails the device at open, not in the middle of a test.
        self._connected = True
        try:
            self.current_conditions()
        except DriverError:
            self._connected = False
            raise

    def teardown(self) -> None:
        # Every request is a connection of its own; nothing stays open between calls.
        self._connected = False

    def current_conditions(self) -> dict[str, Any]:
        """
        The weather now: {"place", "time", "temperature_c", "relative_humidity_pct",
        "pressure_hpa", "wind_speed_kmh", "wind_direction_deg"}. Time is local to the place.
        """
        data = self._request({"current": ",".join(CURRENT_FIELDS)})
        current = _section(data, "current")
        reading: dict[str, Any] = {"place": self._place, "time": current.get("time", "")}
        for api_name, our_name in CURRENT_FIELDS.items():
            reading[our_name] = _field(current, api_name)
        return reading

    def temperature(self) -> float:
        """The air temperature 2 m above ground, in degrees Celsius."""
        return float(self.current_conditions()["temperature_c"])

    def wind_speed(self) -> float:
        """The wind speed 10 m above ground, in km/h."""
        return float(self.current_conditions()["wind_speed_kmh"])

    def hourly_forecast(self, hours: int) -> list[dict[str, Any]]:
        """
        The next `hours` hours, from the current one: a list of
        {"time", "temperature_c", "wind_speed_kmh"}, one entry per hour.
        """
        if not 1 <= hours <= MAX_FORECAST_HOURS:
            raise DriverError(f"A forecast is 1 to {MAX_FORECAST_HOURS} hours, not {hours}.")
        data = self._request({"hourly": ",".join(HOURLY_FIELDS), "forecast_hours": str(hours)})
        hourly = _section(data, "hourly")
        times = hourly.get("time")
        if not isinstance(times, list):
            raise DriverError("Open-Meteo sent a forecast without times.")
        forecast = []
        for index, time_text in enumerate(times):
            entry: dict[str, Any] = {"time": time_text}
            for api_name, our_name in HOURLY_FIELDS.items():
                values = hourly.get(api_name)
                if not isinstance(values, list) or index >= len(values):
                    raise DriverError(f"Open-Meteo sent a forecast without '{api_name}'.")
                entry[our_name] = values[index]
            forecast.append(entry)
        return forecast

    def _request(self, query: dict[str, str]) -> dict[str, Any]:
        """One GET to the forecast API for this place; the decoded answer."""
        if not self._connected:
            raise DriverError("Open-Meteo is not connected.")
        parameters = {
            "latitude": str(self._latitude),
            "longitude": str(self._longitude),
            "timezone": "auto",
        }
        parameters.update(query)
        url = API_URL + "?" + urllib.parse.urlencode(parameters)
        logger.debug("GET %s", url)
        try:
            with urllib.request.urlopen(url, timeout=self._timeout_s) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            # Open-Meteo explains a refused request in a JSON "reason".
            raise DriverError(
                f"Open-Meteo refused the request ({exc.code}): {_reason(exc)}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DriverError(f"Open-Meteo could not be reached: {exc}") from exc
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise DriverError(f"Open-Meteo sent an answer that is not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise DriverError("Open-Meteo sent an answer that is not a JSON object.")
        return data


def _read_number(config: dict[str, str], key: str, default: float) -> float:
    """A number from the section, or the default when the key is absent or empty."""
    text = config.get(key, "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        raise DriverError(f"Open-Meteo {key} must be a number, not '{text}'.") from None


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    """One block of the answer ("current", "hourly"), checked to be there."""
    section = data.get(name)
    if not isinstance(section, dict):
        raise DriverError(f"Open-Meteo sent an answer without '{name}'.")
    return section


def _field(section: dict[str, Any], name: str) -> Any:
    """One reading of a block, checked to be there."""
    if name not in section:
        raise DriverError(f"Open-Meteo sent an answer without '{name}'.")
    return section[name]


def _reason(error: urllib.error.HTTPError) -> str:
    """The reason Open-Meteo gave, or the HTTP one when the body says nothing."""
    try:
        data = json.loads(error.read())
    except (ValueError, OSError):
        return str(error.reason)
    if isinstance(data, dict) and data.get("reason"):
        return str(data["reason"])
    return str(error.reason)
