# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Config Handler: one place that answers "how is this installation set up".

Three rules shape everything below.

**One instance per process.** `ConfigHandler()` returns the same object however
often it is called, so any module can reach the configuration without it being
passed down through constructors. The instance is per *process*, not per
application - a spawned child shares no memory with its parent, so it builds its
own instance and reads the same file. That is why reading is pure: it parses,
it never writes. The previous implementation created and rewrote the file on
every read, which meant five processes rewriting one file per run.

**One writer.** The launcher calls `bootstrap()` before anything else exists: it
creates the file from the template if the machine has none, migrates it if it
was written by an older pypts, and validates it. From then on the file is
read-only to everyone except CORE, which opens it with `open_for_writing()`.
Any other process calling `set_parameter()` gets a `ConfigWriteError` rather
than a race.

**It has to work before logging does.** `bootstrap()` runs before the Logger
process exists - it is what decides where the log file goes - so it cannot log.
It buffers its messages instead, and the launcher calls
`replay_bootstrap_log()` once logging is up. Nothing about the config's own
startup is lost; it simply arrives in the run log a few milliseconds late.

Typical use:

    ConfigHandler.bootstrap()                        # launcher, once
    ConfigHandler().get_parameter("paths.logs_dir")  # anywhere, any process
"""

import configparser
import copy
import logging
import platform
import threading
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

from pypts.config_handler import file_locations, template_writer
from pypts.config_handler.configuration_schema import (
    CONFIG_VERSION,
    DEPRECATED,
    FALSE_VALUES,
    SCHEMA,
    TRUE_VALUES,
    Field,
    schema_for_section,
)
from pypts.logger.log import log

#: Name of the template shipped inside this package.
TEMPLATE_FILE_NAME = "config_template.ini"

#: Distinguishes "no default given" from "the default is None", so that
#: get_parameter(key, default=None) can legitimately return None.
_UNSET = object()


class ConfigError(Exception):
    """Base of everything this module raises, so a caller can catch one type."""


class ConfigFileMissing(ConfigError):
    """The config file does not exist and this handler is not allowed to create it."""


class ConfigKeyError(ConfigError):
    """A key was asked for that the configuration does not have."""


class ConfigWriteError(ConfigError):
    """A write was attempted through a handler that is not the writer."""


class ConfigSchemaError(ConfigError):
    """The file's contents do not match the schema: a key is missing, or a value
    cannot be read as the type its key declares."""


class Role(Enum):
    """
    What an instance is allowed to do.

    READER is the default and what every module gets. WRITER is held by the
    launcher during bootstrap and by CORE, which owns configuration changes at
    runtime.
    """

    READER = "reader"
    WRITER = "writer"


class ConfigHandler:
    """
    The per-process singleton. Build it with `ConfigHandler()`, or with
    `bootstrap()` / `open_for_writing()` if you are allowed to write.
    """

    _instance: "ConfigHandler | None" = None

    #: Guards first construction. Sequencer and Report become threads of the
    #: engine process in the target architecture, so two threads can reach a
    #: cold singleton at the same moment.
    _lock = threading.RLock()

    def __new__(cls) -> Self:
        """Read-only access to the configuration of this process."""
        return cls._obtain(Role.READER, create_if_missing=False)

    def __init__(self) -> None:
        """
        Deliberately empty.

        `__new__` may return an instance that is already set up, and Python
        calls `__init__` on it regardless; doing the work here would redo it on
        every `ConfigHandler()` call.
        """

    # --- construction ---------------------------------------------------------

    @classmethod
    def bootstrap(cls) -> "ConfigHandler":
        """
        Prepare the configuration for this run. The launcher's job, and only the
        launcher's.

        Creates the file from the template if it does not exist, migrates it if
        it predates this version of pypts, repairs missing keys, and validates
        the result. Writes only when something actually changed, so a second run
        leaves the file untouched.

        Returns:
            The writer instance for this process.

        Raises:
            ConfigWriteError: a read-only instance already exists here.
            ConfigSchemaError: the file cannot be made to fit the schema.
        """
        return cls._obtain(Role.WRITER, create_if_missing=True)

    @classmethod
    def open_for_writing(cls) -> "ConfigHandler":
        """
        Writer access for CORE, which owns configuration changes while the
        application runs. The file must already exist - creating it is the
        launcher's job and has happened long before CORE starts.
        """
        return cls._obtain(Role.WRITER, create_if_missing=False)

    @classmethod
    def reset_for_testing(cls) -> None:
        """
        Forget the singleton, so the next call builds a fresh one.

        Only tests should call this: a process that dropped its configuration
        half way through a run would be reading a different file from its own
        threads. Tests need it because the singleton would otherwise outlive the
        `tmp_path` it was pointed at.
        """
        with cls._lock:
            cls._instance = None

    @classmethod
    def _obtain(cls, role: Role, create_if_missing: bool) -> "ConfigHandler":
        with cls._lock:
            if cls._instance is not None:
                if role is Role.WRITER and cls._instance.role is not Role.WRITER:
                    raise ConfigWriteError(
                        "This process already holds a read-only configuration; it "
                        "cannot be promoted to writer. Only the launcher's bootstrap "
                        "and CORE open the configuration for writing."
                    )
                return cls._instance

            instance = object.__new__(cls)
            instance._setup(role, create_if_missing)
            cls._instance = instance
            return instance

    def _setup(self, role: Role, create_if_missing: bool) -> None:
        """
        Find, create or repair the file, then read it.

        Narrated deliberately thoroughly. This runs once per process, before
        anything else in that process, and it is what decides where the run log
        and the reports go - so when the answer is surprising, the log has to
        say where the handler looked, what it found there and what it did about
        it. At DEBUG it also prints every resulting value.
        """
        self.role = role
        self._path = file_locations.config_file_path()
        self._template_text = _read_template()
        self._bootstrap_log: list[tuple[int, str]] = []

        self._note(
            logging.DEBUG,
            f"Resolving configuration: directory {file_locations.config_dir()}, "
            f"file {file_locations.CONFIG_FILE_NAME}, opened as {self.role.value}.",
        )

        if not self._path.exists():
            if not create_if_missing:
                self._note(logging.DEBUG, f"No configuration file at {self._path}.")
                raise ConfigFileMissing(
                    f"No configuration at {self._path}. It is created by the launcher "
                    f"at startup; a module that reaches this has been started on its own."
                )
            self._note(
                logging.INFO,
                f"No configuration file at {self._path}; creating one from the template.",
            )
            raw = self._build_from_defaults()
            self._write(raw)
            self._note(
                logging.INFO,
                f"Configuration created at {self._path} (structure version {CONFIG_VERSION}).",
            )
        else:
            self._note(
                logging.DEBUG,
                f"Found an existing configuration file at {self._path} "
                f"({self._path.stat().st_size} bytes).",
            )
            raw = _read_raw(self._path)
            if create_if_missing:
                raw = self._repair(raw)
            else:
                self._note(
                    logging.DEBUG,
                    "Opened read-only; this process neither creates nor repairs the file.",
                )

        self._raw = raw
        self._values = self._validate(raw)
        self._note(
            logging.INFO,
            f"Configuration loaded from {self._path} (structure version "
            f"{self.config_version}, {len(self._values)} sections).",
        )
        self._note_active_configuration()

    def _note_active_configuration(self) -> None:
        """
        Every value in force, one record each, at DEBUG.

        One line per key rather than one block, so that the run log stays one
        record per line and a value can be grepped for on its own.
        """
        for section, values in self._values.items():
            for key, value in values.items():
                self._note(logging.DEBUG, f"Configuration value {section}.{key} = {value}")

    # --- reading --------------------------------------------------------------

    def get_parameter(self, key: str, default: Any = _UNSET) -> Any:
        """
        One value, converted to the type its schema field declares.

        Args:
            key: dotted, `section.option` - "paths.logs_dir",
                "hardware.dmm1.timeout_s". Everything before the last dot is the
                section name.
            default: returned instead of raising when the key is absent. Pass it
                only where an absent key is genuinely acceptable.

        Returns:
            `Path`, `int`, `float`, `bool` or `str`, per the schema. Values in
            sections the schema does not know about are returned as strings.

        Raises:
            ConfigKeyError: no such key, and no default was given.
        """
        section, _, option = key.rpartition(".")
        if not section:
            raise ConfigKeyError(
                f"Configuration keys are dotted, as in 'paths.logs_dir'; got {key!r}."
            )

        if section in self._values and option in self._values[section]:
            return self._values[section][option]

        if default is not _UNSET:
            return default

        if section not in self._values:
            known = ", ".join(sorted(self._values)) or "none"
            raise ConfigKeyError(
                f"Unknown configuration section {section!r}. Known sections: {known}."
            )

        known = ", ".join(sorted(self._values[section])) or "none"
        raise ConfigKeyError(
            f"Unknown configuration key {key!r}. Section {section!r} has: {known}."
        )

    def get_whole_config(self) -> Mapping[str, Mapping[str, Any]]:
        """
        Every section and value, converted, as a read-only mapping.

        Read-only because handing out the live dictionaries would let any caller
        change the configuration of the whole process without going through
        `set_parameter()` and without anything being written to disk.
        """
        return MappingProxyType(
            {section: MappingProxyType(dict(values)) for section, values in self._values.items()}
        )

    def dump(self) -> str:
        """
        The full active configuration as text, for a log or a console.

        Names the file it came from, because "which config.ini is this process
        actually using" is the first question worth answering when a setting
        does not seem to apply.
        """
        lines = [
            f"Configuration: {self._path}",
            f"Structure version: {self.config_version}",
        ]
        # Schema order first, so the dump reads like the file rather than like
        # whatever order a migrated file happened to leave the sections in.
        ordered = [section for section in SCHEMA if section in self._values]
        ordered += [section for section in self._values if section not in SCHEMA]
        for section in ordered:
            lines.append(f"[{section}]")
            lines.extend(f"    {key} = {value}" for key, value in self._values[section].items())
        return "\n".join(lines)

    @property
    def config_path(self) -> Path:
        """The file this process is using. Absolute, and it exists."""
        return self._path

    @property
    def config_version(self) -> int:
        """Structure version of the file on disk."""
        return int(self._raw.get("meta", {}).get("config_version", 0))

    # --- writing --------------------------------------------------------------

    def set_parameter(self, key: str, value: Any) -> None:
        """
        Change one value and write the file.

        Args:
            key: dotted, as for `get_parameter`.
            value: anything that reads as the key's declared type. `Path`, `int`
                and `bool` are all accepted for their respective fields, as are
                the strings that spell them.

        Raises:
            ConfigWriteError: this handler is a reader.
            ConfigKeyError: no such key.
            ConfigSchemaError: the value does not fit the key's type.

        Note that other processes already running hold their own copy and will
        not see this until they are restarted. Propagating a change to a live
        run is not implemented; it is a roadmap item.
        """
        self._require_writer("set_parameter")

        section, _, option = key.rpartition(".")
        if section not in self._raw or option not in self._raw[section]:
            raise ConfigKeyError(f"Unknown configuration key {key!r}.")

        field = _field_for(section, option)
        text = _to_text(value)
        if field is not None:
            # Parsed and thrown away, purely so a bad value is refused here
            # rather than at the next start, when the file is all there is.
            _parse(section, option, text, field)

        self._raw[section][option] = text
        self._values = self._validate(self._raw)
        self._write(self._raw)
        log.info("Configuration key %s set to %r in %s", key, text, self._path)

    def restore_default(self) -> None:
        """
        Rewrite the file as a fresh installation would: template defaults, paths
        and operating system detected again. Every user change is discarded.

        Raises:
            ConfigWriteError: this handler is a reader.
        """
        self._require_writer("restore_default")

        self._raw = self._build_from_defaults()
        self._values = self._validate(self._raw)
        self._write(self._raw)
        log.warning("Configuration restored to defaults in %s", self._path)

    def _require_writer(self, action: str) -> None:
        if self.role is not Role.WRITER:
            raise ConfigWriteError(
                f"{action}() needs write access, and this process holds the "
                f"configuration read-only. Configuration changes are made by CORE; "
                f"send it a SetConfigParameter message instead of writing the file."
            )

    def _write(self, raw: dict[str, dict[str, str]]) -> None:
        template_writer.write(self._path, self._template_text, raw)
        # Worth a record of its own: this is the only thing in the framework
        # that modifies the user's file, so "was it written, and when" should
        # never have to be inferred from mtime.
        self._note(logging.DEBUG, f"Configuration file written: {self._path}")

    # --- creation, migration, validation ---------------------------------------

    def _build_from_defaults(self) -> dict[str, dict[str, str]]:
        """
        A complete set of values for a machine that has no config file: the
        template's defaults, with the derived ones filled in.
        """
        raw = {
            section: {key: field.default for key, field in fields.items()}
            for section, fields in SCHEMA.items()
        }
        raw["meta"]["config_version"] = str(CONFIG_VERSION)
        raw["operating_system"] = _detect_operating_system()
        raw["paths"] = _default_paths()
        return raw

    def _repair(self, raw: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        """
        Bring an existing file up to the current structure, keeping every value
        the user set.

        Renames deprecated keys, drops the ones that no longer mean anything,
        adds keys this version introduced, and fills in any derived value that
        is missing. Writes only if that changed something, and keeps the
        previous file as config.ini.v<n>.bak when it did.

        Raises:
            ConfigSchemaError: the file was written by a newer pypts, whose
                structure this code cannot know.
        """
        found_version = raw.get("meta", {}).get("config_version", "0")
        try:
            file_version = int(found_version)
        except ValueError:
            file_version = 0

        self._note(
            logging.DEBUG,
            f"Configuration declares structure version {file_version}; this pypts "
            f"expects {CONFIG_VERSION}.",
        )

        if file_version > CONFIG_VERSION:
            raise ConfigSchemaError(
                f"{self._path} declares structure version {file_version}, but this pypts "
                f"understands version {CONFIG_VERSION}. It was written by a newer "
                f"version; upgrade pypts or remove the file to start again."
            )

        repaired = copy.deepcopy(raw)
        changes: list[str] = []

        _apply_deprecations(repaired, changes)
        _add_missing_keys(repaired, changes)

        if file_version != CONFIG_VERSION:
            repaired.setdefault("meta", {})["config_version"] = str(CONFIG_VERSION)
            changes.append(f"structure version {file_version} -> {CONFIG_VERSION}")

        if not changes:
            self._note(
                logging.DEBUG,
                "Configuration is complete and current; nothing to migrate, "
                "and the file is left untouched.",
            )
            return repaired

        self._note(
            logging.INFO,
            f"Configuration needs {len(changes)} change(s); migrating {self._path}.",
        )
        for change in changes:
            self._note(logging.INFO, f"  {change}")

        backup = self._path.with_suffix(f".ini.v{file_version}.bak")
        backup.write_text(self._path.read_text(encoding="utf-8"), encoding="utf-8")
        self._write(repaired)

        self._note(logging.INFO, f"Configuration migrated; previous file kept as {backup}")
        return repaired

    def _validate(self, raw: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
        """
        Convert every value to its declared type, and refuse the file if one of
        them does not fit.

        A section the schema does not know about is kept as strings and reported
        once - it may be a typo, and a typo that silently does nothing is worse
        than one that is mentioned.
        """
        values: dict[str, dict[str, Any]] = {}

        for section, options in raw.items():
            fields = schema_for_section(section)
            if fields is None:
                self._note(
                    logging.WARNING,
                    f"Configuration section [{section}] is not part of the schema; "
                    f"its values are available as text and nothing else reads them.",
                )
                values[section] = dict(options)
                continue

            converted: dict[str, Any] = {}
            for key, text in options.items():
                field = fields.get(key)
                if field is None:
                    self._note(
                        logging.WARNING,
                        f"Configuration key '{section}.{key}' is not part of the schema; "
                        f"it is available as text and nothing else reads it.",
                    )
                    converted[key] = text
                    continue
                converted[key] = _parse(section, key, text, field)

            missing = [key for key in fields if key not in converted]
            if missing:
                raise ConfigSchemaError(
                    f"Configuration section [{section}] in {self._path} is missing: "
                    f"{', '.join(sorted(missing))}. Start pypts through its launcher, "
                    f"which repairs the file, or delete it to have it recreated."
                )
            values[section] = converted

        for section in SCHEMA:
            if section not in values:
                raise ConfigSchemaError(
                    f"Configuration in {self._path} has no [{section}] section. Start "
                    f"pypts through its launcher, which repairs the file, or delete it "
                    f"to have it recreated."
                )

        return values

    # --- the bootstrap log ------------------------------------------------------

    def _note(self, level: int, message: str) -> None:
        """
        Record something that happened before there was anywhere to log it.

        Buffered rather than logged, because `bootstrap()` runs before the
        Logger process exists - it is what decides where the log file goes.
        Once a handler is already initialised the buffer is pointless, so the
        message goes straight out instead.
        """
        if logging.getLogger().handlers:
            log.log(level, message)
            return
        self._bootstrap_log.append((level, message))

    def replay_bootstrap_log(self) -> None:
        """
        Emit everything buffered during bootstrap, now that logging works.
        Called by the launcher immediately after `init_logging()`.
        """
        for level, message in self._bootstrap_log:
            log.log(level, message)
        self._bootstrap_log.clear()


# --- module-level helpers -------------------------------------------------------


def _read_template() -> str:
    """The shipped template, which is both the defaults and the comment layout."""
    return (Path(__file__).parent / TEMPLATE_FILE_NAME).read_text(encoding="utf-8")


def _read_raw(path: Path) -> dict[str, dict[str, str]]:
    """
    Parse the file into plain strings.

    Interpolation is off: a Windows path or a password may legitimately contain
    a `%`, and configparser's default would read it as a reference and raise.

    Read as utf-8-sig, not utf-8, so a byte order mark is skipped. This file is
    meant to be edited by hand, and Notepad writes a BOM by default - without
    this, saving the file in the most obvious editor on Windows makes the first
    section header unreadable and the application will not start. Writing stays
    plain utf-8, so a file pypts wrote has no BOM to begin with.

    Raises:
        ConfigSchemaError: the file is not readable as INI at all. Wrapped
            because this runs before logging exists, where a bare configparser
            traceback is the only thing the user would get.
    """
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8-sig")
    except configparser.Error as error:
        raise ConfigSchemaError(
            f"{path} cannot be read as a configuration file: {error}. Correct it, or "
            f"delete it and pypts will create it again from the template."
        ) from error
    return {section: dict(parser[section]) for section in parser.sections()}


def _detect_operating_system() -> dict[str, str]:
    """The machine this config was set up on. Recorded once, at creation."""
    return {
        "name": platform.system(),
        "version": platform.version(),
        "architecture": platform.machine(),
        "kernel": platform.release(),
    }


def _default_paths() -> dict[str, str]:
    """Where output goes on a fresh installation, for this platform."""
    base = file_locations.default_data_dir()
    return {
        "base_dir": str(base),
        "logs_dir": str(base / "logs"),
        "reports_dir": str(base / "reports"),
    }


def _field_for(section: str, key: str) -> Field | None:
    fields = schema_for_section(section)
    return None if fields is None else fields.get(key)


def _to_text(value: Any) -> str:
    """
    How a value is spelled in the file. `True` becomes "true" rather than
    "True", so a file written by the code and one written by hand look alike.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse(section: str, key: str, text: str, field: Field) -> Any:
    """
    One string from the file, as the type its field declares.

    Raises:
        ConfigSchemaError: naming the key and what was wrong with it. The
            message is read by whoever has to fix the file, so it says what is
            allowed rather than only what failed.
    """
    where = f"'{section}.{key}'"

    if field.type == "str":
        if field.choices and text not in field.choices:
            raise ConfigSchemaError(
                f"Configuration key {where} is {text!r}; allowed values are "
                f"{', '.join(field.choices)}."
            )
        return text

    if field.type == "path":
        if not text:
            raise ConfigSchemaError(f"Configuration key {where} is empty; a path is required.")
        return Path(text).expanduser()

    if field.type == "int":
        try:
            return int(text)
        except ValueError:
            raise ConfigSchemaError(
                f"Configuration key {where} is {text!r}; a whole number is required."
            ) from None

    if field.type == "float":
        try:
            return float(text)
        except ValueError:
            raise ConfigSchemaError(
                f"Configuration key {where} is {text!r}; a number is required."
            ) from None

    if field.type == "bool":
        lowered = text.strip().lower()
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
        raise ConfigSchemaError(
            f"Configuration key {where} is {text!r}; use one of "
            f"{', '.join(sorted(TRUE_VALUES))} or {', '.join(sorted(FALSE_VALUES))}."
        )

    raise ConfigSchemaError(f"Configuration key {where} declares unknown type {field.type!r}.")


def _apply_deprecations(raw: dict[str, dict[str, str]], changes: list[str]) -> None:
    """Rename what moved, drop what no longer means anything."""
    for old_key, replacement in DEPRECATED.items():
        old_section, _, old_option = old_key.rpartition(".")
        if old_section not in raw or old_option not in raw[old_section]:
            continue

        value = raw[old_section].pop(old_option)
        if replacement is None:
            changes.append(f"removed '{old_key}' (no longer used)")
        else:
            new_section, _, new_option = replacement.rpartition(".")
            target = raw.setdefault(new_section, {})
            # An already-present target wins: the user set it in the new place,
            # and the old key is a leftover.
            if new_option not in target or not target[new_option]:
                target[new_option] = value
                changes.append(f"moved '{old_key}' to '{replacement}'")
            else:
                changes.append(f"removed '{old_key}' (superseded by '{replacement}')")

        if not raw[old_section]:
            del raw[old_section]


def _add_missing_keys(raw: dict[str, dict[str, str]], changes: list[str]) -> None:
    """
    Add whatever this version introduced, and fill any derived value that has
    ended up blank.

    Derived values are only filled when they are absent or empty. A path the
    user pointed at their own drive is a value like any other once written, and
    nothing here recomputes it.
    """
    derived_defaults = {
        "operating_system": _detect_operating_system(),
        "paths": _default_paths(),
    }

    for section, fields in SCHEMA.items():
        target = raw.setdefault(section, {})
        for key, field in fields.items():
            if target.get(key):
                continue
            if field.derived:
                value = derived_defaults.get(section, {}).get(key, field.default)
            else:
                value = field.default
            if key not in target:
                changes.append(f"added '{section}.{key}' = {value!r}")
            else:
                changes.append(f"filled in empty '{section}.{key}' = {value!r}")
            target[key] = value
