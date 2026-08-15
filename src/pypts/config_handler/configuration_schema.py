# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the configuration *is*: every section, every key, its type and its default.

This module and `config_template.ini` are two views of one structure. The
template owns the comments and is what the user reads; this module owns the
types and is what the code reads. They are kept honest by
`test_schema_and_template_agree` in tests/unit_tests/test_config_handler.py,
which fails if a key exists in one and not the other, or if a template default
cannot be parsed as its declared type. That test is the "config structure
verification tool" the specification asks for, and CI already runs it - see the
`dev_test` job in .gitlab-ci.yml.

One kind of value needs explaining.

*Derived* values ship blank in the template and are filled in the first time the
config is created: the paths (from the platform's data directory) and the
operating system section (from `platform`). This is how the template stays free
of `/tmp/pypts`, which was wrong on Windows, without hardcoding a Windows path
that would be wrong on Linux. Once written they are ordinary values the user may
edit, and nothing recomputes them.

The schema is a flat list of named sections and nothing else. A section the user
adds that is not in it - `[hardware.dmm1]`, most likely - is not an error: it is
kept as it was written, reported once at WARNING, and its values come back as
text. How hardware is configured is Phase 5's question, and this module does not
pre-empt the answer.
"""

from dataclasses import dataclass

#: Bumped whenever a section or key is added, removed or renamed. An existing
#: config.ini declaring a lower version is migrated on the next launch; one
#: declaring a higher version is refused, because this code cannot know what a
#: future pypts meant by it.
CONFIG_VERSION = 1

#: Values a boolean key accepts, borrowed from configparser's own vocabulary so
#: that a file written by hand behaves the way an INI file is expected to.
TRUE_VALUES = frozenset({"1", "yes", "true", "on"})
FALSE_VALUES = frozenset({"0", "no", "false", "off"})


@dataclass(frozen=True, slots=True)
class Field:
    """
    One key. `default` is the literal that appears in the template, so the two
    can be compared directly by the agreement test.

    Args:
        type: one of "str", "int", "float", "bool", "path".
        default: the value as it is written in the file. Empty for derived keys.
        choices: allowed values for a "str" key. Empty means anything goes.
        derived: True if the value is computed when the config is created
            rather than shipped. Such keys are blank in the template, and the
            agreement test expects them to be.
    """

    type: str
    default: str = ""
    choices: tuple[str, ...] = ()
    derived: bool = False


#: The log levels `[logging] level` accepts. Same set as the launcher's
#: --log-level argument, which overrides this value for one run.
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: section -> key -> Field. Section names are lower case with dots for
#: hierarchy; configparser treats them as opaque strings, so the dots cost
#: nothing and read as structure.
SCHEMA: dict[str, dict[str, Field]] = {
    "meta": {
        "config_version": Field("int", str(CONFIG_VERSION)),
    },
    "operating_system": {
        "name": Field("str", derived=True),
        "version": Field("str", derived=True),
        "architecture": Field("str", derived=True),
        "kernel": Field("str", derived=True),
    },
    "paths": {
        "base_dir": Field("path", derived=True),
        "logs_dir": Field("path", derived=True),
        "reports_dir": Field("path", derived=True),
    },
    "logging": {
        # DEBUG for the duration of the refactor, so every run carries the
        # message trace and the Debug Monitor always has something to read.
        # This reverts to INFO before v1.0 - see the TODO in the roadmap.
        "level": Field("str", "DEBUG", choices=LOG_LEVELS),
    },
    "report": {
        "type": Field("str", "html", choices=("html", "csv")),
        "theme": Field("str", "default"),
    },
    "gui": {
        "theme": Field("str", "default", choices=("default", "light", "dark")),
        "window_width": Field("int", "1280"),
        "window_height": Field("int", "720"),
    },
}

#: Old dotted key -> its replacement, or None if the key was simply dropped.
#: Consulted only during migration. Everything here comes from the pre-versioned
#: layout that shipped before this module existed, which had no [meta] section
#: at all and is therefore treated as version 0.
DEPRECATED: dict[str, str | None] = {
    "OperatingSystem.name": "operating_system.name",
    "OperatingSystem.version": "operating_system.version",
    "OperatingSystem.architecture": "operating_system.architecture",
    "OperatingSystem.kernel": "operating_system.kernel",
    "Paths.base_temp_dir": "paths.base_dir",
    "Paths.logs_dir": "paths.logs_dir",
    # The config no longer lives where the config says it lives; the location is
    # computed (see file_locations.py), so a stored copy could only ever be a lie.
    "Paths.config_dir": None,
    "Application.log_level": "logging.level",
    # Was a hand-maintained duplicate of the package version, which setuptools-scm
    # already owns. Read pypts.__version__ instead.
    "Application.app_version": None,
    "Misc.example_flag": None,
}


def schema_for_section(section: str) -> dict[str, Field] | None:
    """
    The fields a section is validated against, or None if it is not part of the
    schema at all.

    A plain lookup today. It stays a function rather than a dict access because
    it is the one place that decides what a section name means, and Phase 5 will
    have to answer that question again for hardware.
    """
    return SCHEMA.get(section)
