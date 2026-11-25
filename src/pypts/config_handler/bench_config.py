# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The bench file: which devices are on this bench.

`bench.ini` lives beside `config.ini` and holds one section per device, bare
name: `[ssh1]`. Nothing in it is typed or mandatory - every value is kept as
text for the hardware layer (`pyhal/pyhal.md` -> Configuration) - so it needs none
of ConfigHandler's machinery: no schema, no structure version, no roles and no
writer. Nothing in pypts ever writes a device section; the file is the user's.

One entry point: `bench_config()`, which reads the file on every call and keeps
nothing. The launcher calls it first, after logging is up - so unlike
`ConfigHandler.bootstrap()` it never buffers its log lines - and shows the
operator a notice if the file was discarded. CORE's `HalLink.start()` calls it
again for the path it hands the HAL server, which reads the devices itself, once,
when it starts (`pyhal/pyhal.md` -> Configuration).
"""

import configparser
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pypts.config_handler import file_locations, template_writer

#: The root logger, the way `config_handler.py` logs. Not `pypts.logger.log`:
#: that module imports the message layer, which this package must not depend on.
log = logging.getLogger()

#: Name of the template shipped inside this package: what a new bench.ini starts
#: with - its comments and one demo device, the weather station `meteo_Meyrin`.
BENCH_TEMPLATE_FILE_NAME = "bench_template.ini"


class BenchOutcome(Enum):
    """What bench_config() found."""

    #: No file existed; one was written from the template, and its devices read back.
    CREATED = "created"
    #: The file was read; its sections are the devices, verbatim.
    LOADED = "loaded"
    #: The file exists but cannot be used, or could not be created: there are
    #: no devices this start, and `problem` says why.
    DISCARDED = "discarded"


@dataclass(frozen=True)
class BenchConfig:
    """The devices of this bench, as bench.ini declares them."""

    #: Logical name -> the section's keys, every value as text.
    devices: dict[str, dict[str, str]]
    outcome: BenchOutcome
    #: Why the file was discarded; None unless `outcome` is DISCARDED.
    problem: str | None
    path: Path


def bench_config() -> BenchConfig:
    """
    The bench file, read - or created from the template - now. Stateless, like
    ConfigHandler: nothing is kept between calls.

    Never raises: a file that cannot be used is DISCARDED, with the reason in
    `problem`, and the start simply has no devices.
    """
    return _read_or_create()


def _read_or_create() -> BenchConfig:
    path = file_locations.bench_file_path()
    if not path.exists():
        return _create(path)

    parser = configparser.ConfigParser(interpolation=None)
    try:
        # Not parser.read(path): that swallows OSError per-file and returns an
        # empty parser, which would misread as a bench with no devices. Opening
        # explicitly makes "exists but cannot be opened" its own reason.
        # utf-8-sig, because this file is meant to be edited by hand and
        # Notepad writes a BOM by default. Interpolation is off: a Windows
        # path or a password may legitimately contain a `%`.
        with open(path, encoding="utf-8-sig") as bench_file:
            parser.read_file(bench_file)
    except OSError as error:
        return _discarded(path, f"{path} exists but cannot be opened: {error}.")
    except configparser.Error as error:
        return _discarded(path, f"{path} cannot be read as an INI file: {error}.")

    devices = {section: dict(parser[section]) for section in parser.sections()}
    log.debug("Bench file %s declares %d device(s).", path, len(devices))
    return BenchConfig(devices=devices, outcome=BenchOutcome.LOADED, problem=None, path=path)


def _create(path: Path) -> BenchConfig:
    template_path = Path(__file__).parent / BENCH_TEMPLATE_FILE_NAME
    try:
        template_writer.write(path, template_path.read_text(encoding="utf-8"))
    except OSError as error:
        return _discarded(path, f"No bench file at {path}, and one could not be created: {error}.")
    log.info("No bench file was found; one was created from the template at %s.", path)
    # Read back what was written, so the devices the template declares are this
    # start's devices too - the same reader as for a file that already existed.
    written = _read_or_create()
    if written.outcome is BenchOutcome.DISCARDED:
        return written
    return BenchConfig(
        devices=written.devices, outcome=BenchOutcome.CREATED, problem=None, path=path
    )


def _discarded(path: Path, problem: str) -> BenchConfig:
    log.error(
        "The bench file is not usable, so this start has no devices. %s "
        "Correct it, or delete it to have it recreated.",
        problem,
    )
    return BenchConfig(devices={}, outcome=BenchOutcome.DISCARDED, problem=problem, path=path)
