"""
The local setup: the devices of one run, by logical name.

A LocalSetup reads its devices from `[hardware.<name>]` sections, opens a
device the first time it is asked for it, and closes every device it opened
when it is closed. Entering it (`with setup:`) also makes it the *active*
setup, which is what get_device() asks - the Sequencer enters one per run, and
a script outside PyPTS does the same with
`with LocalSetup.from_ini("bench.ini"):`.

pypts.config_handler is imported inside the one function that needs it: a
driver process imports this module too (through pypts.hal), and has no use
for the configuration.
"""

import configparser
import os
import threading
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any

from pypts.hal.base_driver import DriverError
from pypts.hal.connection_driver import ConnectionDriver
from pypts.logger.log import log

#: How long one call may take when the section does not say (`call_timeout_s`).
DEFAULT_CALL_TIMEOUT_S = 60.0


def split_section(name: str, section: Mapping[str, Any]) -> tuple[str, float, dict[str, str]]:
    """
    One `[hardware.<name>]` section as (driver class path, call timeout, the
    driver's own keys). `driver` and `call_timeout_s` are read here; every
    other key goes to the driver's connect(), as text.
    """
    settings: dict[str, str] = {}
    for key, value in section.items():
        settings[key] = str(value)
    if "python" in settings:
        raise DriverError(
            f"Device '{name}': the 'python' key is not supported any more - every driver runs "
            f"on PyPTS's own Python. Remove it from [hardware.{name}]."
        )
    driver_path = settings.pop("driver", "").strip()
    if not driver_path:
        raise DriverError(
            f"Device '{name}': [hardware.{name}] has no 'driver' key naming its driver class."
        )
    timeout_text = settings.pop("call_timeout_s", "").strip()
    if timeout_text:
        try:
            call_timeout_s = float(timeout_text)
        except ValueError:
            call_timeout_s = 0.0
        if call_timeout_s <= 0:
            raise DriverError(
                f"Device '{name}': call_timeout_s must be a positive number of seconds, "
                f"not '{timeout_text}'."
            )
    else:
        call_timeout_s = DEFAULT_CALL_TIMEOUT_S
    return driver_path, call_timeout_s, settings


def hardware_sections(whole: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """The device sections of a whole configuration, by logical name, values as text."""
    from pypts.config_handler.configuration_schema import HARDWARE_PREFIX, is_hardware_section

    devices: dict[str, dict[str, str]] = {}
    for section, values in whole.items():
        if not is_hardware_section(section):
            continue
        text_values: dict[str, str] = {}
        for key, value in values.items():
            text_values[key] = str(value)
        devices[section[len(HARDWARE_PREFIX) :]] = text_values
    return devices


def ini_hardware_sections(path: str | os.PathLike[str]) -> dict[str, dict[str, str]]:
    """The device sections of an INI file of one's own - a setup outside PyPTS."""
    parser = configparser.ConfigParser(interpolation=None)
    with open(path, encoding="utf-8") as handle:
        parser.read_file(handle)
    whole: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        whole[section] = dict(parser[section])
    return hardware_sections(whole)


def hardware_sections_from_config() -> dict[str, dict[str, str]]:
    """The device sections of this process's config.ini - what the Sequencer reads."""
    from pypts.config_handler import ConfigHandler

    return hardware_sections(ConfigHandler().get_whole_config())


class LocalSetup:
    """The devices of one run. Thread-safe: test code may use it from threads of its own."""

    def __init__(self, read_sections: Callable[[], Mapping[str, Mapping[str, Any]]]) -> None:
        """
        Args:
            read_sections: returns the device sections by logical name. Called
                once, the first time a device is asked for - a run that uses
                no device never reads the configuration.
        """
        self._read_sections = read_sections
        self._sections: Mapping[str, Mapping[str, Any]] | None = None
        self._devices: dict[str, ConnectionDriver] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_ini(cls, path: str | os.PathLike[str]) -> "LocalSetup":
        """A local setup described by an INI file of `[hardware.<name>]` sections."""
        return cls(lambda: ini_hardware_sections(path))

    def device_names(self) -> list[str]:
        with self._lock:
            return sorted(self._loaded_sections())

    def get_device(self, name: str) -> ConnectionDriver:
        """The device called `name`, opened on first use. Raises DriverError."""
        with self._lock:
            device = self._devices.get(name)
            if device is not None:
                return device
            sections = self._loaded_sections()
            section = sections.get(name)
            if section is None:
                known = ", ".join(sorted(sections)) or "none"
                raise DriverError(
                    f"No device '{name}' is configured. Add a [hardware.{name}] section to "
                    f"config.ini. Configured devices: {known}."
                )
            driver_path, call_timeout_s, settings = split_section(name, section)
            device = ConnectionDriver(name, driver_path, settings, call_timeout_s=call_timeout_s)
            device.open()
            self._devices[name] = device
            return device

    def close(self) -> None:
        """Close every device this setup opened, newest first. Never raises."""
        with self._lock:
            names = list(self._devices)
            names.reverse()
            for name in names:
                try:
                    self._devices[name].close()
                except Exception as exc:  # noqa: BLE001 - one device must not keep the others open
                    log.warning("Device '%s' did not close: %s", name, exc)
            self._devices.clear()

    def _loaded_sections(self) -> Mapping[str, Mapping[str, Any]]:
        if self._sections is None:
            self._sections = self._read_sections()
            log.debug("Devices configured for this local setup: %s.", sorted(self._sections))
        return self._sections

    def __enter__(self) -> "LocalSetup":
        _activate(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        finally:
            _deactivate(self)


# --- the active local setup -------------------------------------------------------
#
# One per process. Not thread-local on purpose: test code may start threads of
# its own, and they belong to the same run. Two runs never overlap in one
# process - the Sequencer refuses a second Start - so one slot is enough.

_active_setup: LocalSetup | None = None
_active_lock = threading.Lock()


def _activate(setup: LocalSetup) -> None:
    global _active_setup
    with _active_lock:
        if _active_setup is not None and _active_setup is not setup:
            # Only an abandoned run (stop_running_sequence gave up on its
            # thread) leaves a local setup active behind it.
            log.debug("A new local setup replaces one that was never closed.")
        _active_setup = setup


def _deactivate(setup: LocalSetup) -> None:
    global _active_setup
    with _active_lock:
        if _active_setup is setup:
            _active_setup = None


def get_device(name: str) -> ConnectionDriver:
    """
    The device called `name` on the active local setup - what test code calls.

    Raises DriverError when no local setup is active, when no such device is
    configured, or when it cannot be opened.
    """
    with _active_lock:
        setup = _active_setup
    if setup is None:
        raise DriverError(
            "No local setup is active. get_device() works in test code PyPTS is running, or "
            "inside 'with LocalSetup.from_ini(path):' in a script of your own."
        )
    return setup.get_device(name)
