"""
Devices - the open devices of the HAL server, by logical name.

The server's one request thread owns an instance and is the only thread that
touches it, so there is no lock here. A device is opened the first time it is
named and stays open until it is closed. A device whose driver process is gone
- crashed, or stopped because a call timed out - is torn down at once, on a
fresh process (the rescue), and dropped from the open set; the request that
meets it still gets the DriverError, and the next request for that device opens
it again.
"""

import logging
from collections.abc import Mapping
from typing import Any

from pyhal.base_driver import LIFECYCLE_METHODS, DriverError
from pyhal.bench import split_section
from pyhal.connection_driver import CALL_TIMEOUT_S, ConnectionDriver

log = logging.getLogger(__name__)


class Devices:
    """The bench's devices: the open ones, and what the bench file says about the rest."""

    def __init__(
        self,
        sections: Mapping[str, Mapping[str, str]],
        *,
        call_timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        """
        Args:
            sections: the device sections by logical name, as read_bench() returns them.
            call_timeout_s: the longest one call to a driver may take.
        """
        self._sections = sections
        self._call_timeout_s = call_timeout_s
        #: The open devices, in the order they were opened.
        self._devices: dict[str, ConnectionDriver] = {}
        #: The device type of every device opened so far, kept after it closes.
        self._device_types: dict[str, str] = {}
        #: Why the last attempt with a device failed; absent when it did not.
        self._last_errors: dict[str, str] = {}

    # --- what the request handlers call ------------------------------------------

    def open(self, name: str) -> tuple[str, list[str]]:
        """
        The device's type and operations; opens the device on first use, or
        reuses it. Raises DriverError.
        """
        device = self._open_device(name)
        return device._device_type, list(device._operations)

    def call(self, name: str, operation: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        """
        One operation of the device, opened first when it is not open.

        A DriverError that finds the device's process gone is torn down on the
        spot, and the original error is raised after that.
        """
        if operation in LIFECYCLE_METHODS:
            raise DriverError(
                f"Device '{name}': '{operation}' is not an operation; "
                "the HAL server runs it itself."
            )
        device = self._open_device(name)
        try:
            return device._call(operation, args, kwargs)
        except DriverError as exc:
            if not device._is_open():
                self._rescue(name, device, exc)
            raise

    def recover(self, name: str) -> None:
        """Bring the device back: its driver's recover(), or a fresh process. Raises DriverError."""
        device = self._open_device(name)
        try:
            device._recover()
        except DriverError as exc:
            self._last_errors[name] = str(exc)
            if not device._is_open():
                # _recover() tore it down and the fresh process could not connect.
                self._devices.pop(name, None)
            raise
        self._last_errors.pop(name, None)

    def info(self, name: str) -> tuple[str, list[str], bool]:
        """(device type, operations, is open) of a device of the bench. Raises DriverError."""
        device = self._devices.get(name)
        if device is not None:
            return device._device_type, list(device._operations), device._is_open()
        self._section_of(name)
        return self._device_types.get(name, ""), [], False

    def close(self, name: str) -> bool:
        """
        Close the device if it is open. Never raises.

        Returns:
            True when it was torn down or was not open; False when the
            teardown ladder ended on the ERROR line.
        """
        device = self._devices.pop(name, None)
        if device is None:
            return True
        return self._close_device(name, device)

    def close_all(self) -> list[str]:
        """
        Close every open device, the newest first. Never raises.

        Returns:
            The names of the devices that were not torn down, in closing order.
        """
        failed: list[str] = []
        for name in reversed(list(self._devices)):
            if not self.close(name):
                failed.append(name)
        return failed

    def open_names(self) -> list[str]:
        """The names of the open devices, in the order they were opened."""
        return list(self._devices)

    def snapshot(self) -> list[dict[str, Any]]:
        """One dict per bench device: name, device_type, state, last_error."""
        rows: list[dict[str, Any]] = []
        for name in self._sections:
            last_error = self._last_errors.get(name)
            if name in self._devices:
                state = "open"
            elif last_error is not None:
                state = "failed"
            else:
                state = "configured"
            rows.append(
                {
                    "name": name,
                    "device_type": self._device_types.get(name, ""),
                    "state": state,
                    "last_error": last_error,
                }
            )
        return rows

    # --- inside ------------------------------------------------------------------

    def _section_of(self, name: str) -> Mapping[str, str]:
        section = self._sections.get(name)
        if section is None:
            known = ", ".join(sorted(self._sections)) or "none"
            raise DriverError(
                f"No device '{name}' is configured. Add a [{name}] section to "
                f"bench.ini. Configured devices: {known}."
            )
        return section

    def _open_device(self, name: str) -> ConnectionDriver:
        device = self._devices.get(name)
        if device is not None:
            return device
        section = self._section_of(name)
        try:
            driver_path, settings = split_section(name, section)
            device = ConnectionDriver(
                name, driver_path, settings, call_timeout_s=self._call_timeout_s
            )
            device._open()
        except DriverError as exc:
            self._last_errors[name] = str(exc)
            raise
        self._devices[name] = device
        self._device_types[name] = device._device_type
        self._last_errors.pop(name, None)
        return device

    def _rescue(self, name: str, device: ConnectionDriver, error: DriverError) -> None:
        """The device's process is gone: tear it down on a fresh process and drop it."""
        log.warning("Device '%s' lost its driver process: %s", name, error)
        self._devices.pop(name, None)
        self._last_errors[name] = str(error)
        self._close_device(name, device)

    def _close_device(self, name: str, device: ConnectionDriver) -> bool:
        try:
            torn_down = device._close()
        except Exception as exc:  # noqa: BLE001 - one device must not keep the others open
            log.warning("Device '%s' did not close: %s", name, exc)
            torn_down = False
        if not torn_down:
            text = "Its teardown did not run; it may still be energised."
            earlier = self._last_errors.get(name)
            if earlier:
                text = earlier + " " + text
            self._last_errors[name] = text
        return torn_down
