"""
The bench file: bench.ini's device sections, read and prepared for the devices.

One section per device, bare name. read_bench() returns the sections with
their driver files anchored, and the SHA-256 of the file's bytes, which tells a
later reader whether the bench changed.
"""

import configparser
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pyhal.base_driver import DriverError
from pyhal.connection_driver import split_driver_file


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


def read_bench(path: Path) -> tuple[dict[str, dict[str, str]], str]:
    """
    The bench file's device sections - driver files anchored to its folder -
    and the SHA-256 hex digest of the file's bytes. Read as utf-8-sig, so a file
    saved by Notepad, BOM and all, still opens.
    """
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(raw.decode("utf-8-sig"))
    sections = {section: dict(parser[section]) for section in parser.sections()}
    return anchor_driver_files(sections, Path(path).resolve().parent), digest
