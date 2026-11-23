"""
The local setup: the devices of one run, by logical name.

A LocalSetup reads its devices from bench.ini's sections - one per device,
bare name - opens a device the first time it is asked for it, and closes every
device it opened when it is closed. Entering it (`with setup:`) also makes it
the *active* setup, which is what get_device() asks - the Sequencer enters one
per run. A script outside PyPTS uses the HAL server instead
(`with pyhal.connect(path):`, `pyhal.client`).
"""

import logging
import threading
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any

from pyhal.base_driver import DriverError
from pyhal.bench import split_section
from pyhal.connection_driver import ConnectionDriver

log = logging.getLogger(__name__)


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
                    f"No device '{name}' is configured. Add a [{name}] section to "
                    f"bench.ini. Configured devices: {known}."
                )
            driver_path, settings = split_section(name, section)
            device = ConnectionDriver(name, driver_path, settings)
            # The private lifecycle: every public name on a device is the driver's.
            device._open()
            self._devices[name] = device
            return device

    def close(self) -> None:
        """Close every device this setup opened, newest first. Never raises."""
        with self._lock:
            names = list(self._devices)
            names.reverse()
            for name in names:
                try:
                    self._devices[name]._close()
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
            # A script that entered a setup and never left it.
            log.debug("A new local setup replaces one that was never closed.")
        _active_setup = setup


def _deactivate(setup: LocalSetup) -> None:
    global _active_setup
    with _active_lock:
        if _active_setup is setup:
            _active_setup = None


def _setup_is_active() -> bool:
    """Whether a local setup is active (what `pyhal.dispatch` asks first)."""
    with _active_lock:
        return _active_setup is not None


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
            "inside 'with pyhal.connect(path):' in a script of your own."
        )
    return setup.get_device(name)
