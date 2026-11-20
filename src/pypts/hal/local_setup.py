"""
The local setup: the devices of one run, by logical name.

A LocalSetup reads its devices from bench.ini's sections - one per device,
bare name - opens a device the first time it is asked for it, and closes every
device it opened when it is closed. Entering it (`with setup:`) also makes it
the *active* setup, which is what get_device() asks - the Sequencer enters one
per run, and a script outside PyPTS does the same with
`with LocalSetup.from_ini("bench.ini"):`.

pypts.config_handler is imported inside the one function that needs it: a
driver process imports this module too (through pypts.hal), and has no use
for the configuration.
"""

import configparser
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

from pypts.hal.base_driver import DriverError
from pypts.hal.connection_driver import ConnectionDriver, split_driver_file
from pypts.logger.log import log


def split_section(name: str, section: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    """
    One device section as (driver class path, the driver's own keys). Only
    `driver` is read here; every other key goes to the driver's connect(), as
    text.
    """
    settings: dict[str, str] = {}
    for key, value in section.items():
        settings[key] = str(value)
    if "python" in settings:
        raise DriverError(
            f"Device '{name}': the 'python' key is not supported any more - every driver runs "
            f"on PyPTS's own Python. Remove it from the [{name}] section."
        )
    driver_path = settings.pop("driver", "").strip()
    if not driver_path:
        raise DriverError(
            f"Device '{name}': the [{name}] section has no 'driver' key naming its driver class."
        )
    return driver_path, settings


def anchor_driver_files(
    sections: Mapping[str, Mapping[str, str]], ini_folder: Path
) -> dict[str, dict[str, str]]:
    """
    The sections, each a copy, with every driver file
    (`driver = drivers/acme_psu.py:AcmePsuDriver`) made absolute: `~` expanded,
    and a relative file taken as relative to `ini_folder`, the folder of the
    INI file that declares it. A dotted driver path is left as it is.
    """
    anchored: dict[str, dict[str, str]] = {}
    for name, section in sections.items():
        copy = dict(section)
        driver_file = split_driver_file(copy.get("driver", "").strip())
        if driver_file is not None:
            file_name, class_name = driver_file
            path = Path(file_name).expanduser()
            if not path.is_absolute():
                path = ini_folder / path
            copy["driver"] = f"{path}:{class_name}"
        anchored[name] = copy
    return anchored


def ini_device_sections(path: str | os.PathLike[str]) -> dict[str, dict[str, str]]:
    """
    The devices of an INI file of one's own - a setup outside PyPTS.

    The file has bench.ini's format: every section is one device, bare name.
    Read as utf-8-sig so a file saved by Notepad, BOM and all, still opens.
    A relative driver file is relative to this file's folder.
    """
    parser = configparser.ConfigParser(interpolation=None)
    with open(path, encoding="utf-8-sig") as handle:
        parser.read_file(handle)
    sections = {section: dict(parser[section]) for section in parser.sections()}
    return anchor_driver_files(sections, Path(path).resolve().parent)


def bench_sections() -> dict[str, dict[str, str]]:
    """
    The devices of this machine's bench.ini - what the Sequencer reads. A
    relative driver file is relative to bench.ini's folder.

    Raises:
        DriverError: the bench file was discarded at startup; the message
            carries the real reason, so the step's error names the file to
            fix rather than a section to add.
    """
    from pypts.config_handler.bench_config import BenchOutcome, bench_config

    bench = bench_config()
    if bench.outcome is BenchOutcome.DISCARDED:
        raise DriverError(
            f"bench.ini was discarded at startup, so this start has no devices: {bench.problem}"
        )
    return anchor_driver_files(bench.devices, bench.path.parent)


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
        """A local setup described by an INI file in bench.ini's format: one section per device."""
        return cls(lambda: ini_device_sections(path))

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
