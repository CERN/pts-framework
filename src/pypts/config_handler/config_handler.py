# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Config Handler: one place that answers "how is this installation set up".

**Stateless.** Nothing is kept between calls: every `ConfigHandler()` reads and
validates config.ini afresh, is used, and is thrown away. There is no singleton
and no lock. A value saved a moment ago is seen by the next read, in any
process; a value read once at startup (the log level, the window size) is in
force only from the next start.

**One writer, by rule.** The file is the shared thing, not the object:
- The launcher's `bootstrap()` creates the file if it does not exist, before
  CORE starts. An existing file is never repaired: if it is broken or
  version-mismatched it is discarded - the template defaults are used in
  memory (see `BootstrapOutcome`) - and every later read discards it the same
  way until it is corrected or deleted.
- At runtime only CORE writes (`set_parameter()`, `restore_default()`), for the
  frontends' SetConfigParameter and RestoreDefaultConfig.
- The Recipe Editor v2, which runs without CORE, writes its own
  `[recipe_editor]` lines.
Nothing in the code enforces this; it is a convention, and the frontends have
only the messages. A write is atomic (`template_writer.write()`), so a reader
sees the old file or the new one, never half of one.

**It has to work before logging does.** `bootstrap()` runs before the Logger
process exists - it is what decides where the log file goes - so it cannot log.
It buffers its messages instead, and the launcher calls
`replay_bootstrap_log()` once logging is up. Only `bootstrap()` narrates; an
ordinary read logs one DEBUG line.

Typical use:

    ConfigHandler.bootstrap()                        # launcher, once
    ConfigHandler().get_parameter("paths.reports_dir")  # anywhere, any process
"""

import configparser
import logging
import platform
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pypts.config_handler import file_locations, template_writer
from pypts.config_handler.configuration_schema import (
    CONFIG_VERSION,
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
    """A write was refused: the file is discarded, so writing one value would
    replace the user's file with the defaults."""


class ConfigSchemaError(ConfigError):
    """The file's contents do not match the schema: a key is missing, or a value
    cannot be read as the type its key declares."""


class BootstrapOutcome(Enum):
    """
    How one read of the configuration went.

    LOADED: the file was read, validated and is in force. CREATED: no file
    existed, `bootstrap()` wrote one from the template and it is in force. DISCARDED: a
    file exists but is broken or declares the wrong structure version, so the
    template defaults are in force **in memory** - the file itself is left
    exactly as the user wrote it. The launcher reads this to decide whether
    the operator needs a notice before the run starts.
    """

    LOADED = "loaded"
    CREATED = "created"
    DISCARDED = "discarded"


class ConfigHandler:
    """
    One read of config.ini, used and thrown away. `ConfigHandler()` reads an
    existing file; `bootstrap()` - the launcher's - also creates a missing one.
    """

    def __init__(self) -> None:
        """
        Read and validate the file, now. Logs one DEBUG line.

        Raises:
            ConfigFileMissing: there is no config.ini; the launcher creates it.
        """
        self._setup(create_if_missing=False, narrate=False)

    # --- construction ---------------------------------------------------------

    @classmethod
    def bootstrap(cls) -> "ConfigHandler":
        """
        Prepare the configuration for this start. The launcher's job, and the
        Recipe Editor v2's, which runs without a launcher.

        Creates the file from the template if it does not exist. An existing
        file is never modified: it is validated, and if it is broken or declares
        the wrong structure version it is **discarded** - the template defaults
        are used in memory instead, and `bootstrap_outcome` /
        `bootstrap_problem` tell the launcher what to show the operator. Keeping
        the file correct is the user's job: edit it, or delete it to have it
        recreated.

        The one read that narrates: where it looked, what it found, every value
        in force, buffered until `replay_bootstrap_log()`.
        """
        handler = object.__new__(cls)
        handler._setup(create_if_missing=True, narrate=True)
        return handler

    def _setup(self, create_if_missing: bool, narrate: bool) -> None:
        """
        Find or create the file, then read it.

        With `narrate` - bootstrap only - deliberately thorough: this decides
        where the run log and the reports go, so when the answer is surprising
        the log has to say where the handler looked, what it found there and
        what it did about it, and at DEBUG every resulting value. Without it,
        one DEBUG line per read: reads happen on every use, and the full story
        on each would bury the log.
        """
        self._narrate = narrate
        self._path = file_locations.config_file_path()
        self._template_text = _read_template()
        self._bootstrap_log: list[tuple[int, str]] = []
        self.bootstrap_problem: str | None = None

        self._note(
            logging.DEBUG,
            f"Resolving configuration: directory {file_locations.config_dir()}, "
            f"file {file_locations.CONFIG_FILE_NAME}.",
        )

        if not self._path.exists():
            if not create_if_missing:
                log.debug("No configuration file at %s.", self._path)
                raise ConfigFileMissing(
                    f"No configuration at {self._path}. It is created by the launcher "
                    f"at startup; a module that reaches this has been started on its own."
                )
            self._note(
                logging.INFO,
                f"No configuration file at {self._path}; creating one from the template.",
            )
            raw = _build_from_defaults()
            self._write(raw)
            self._note(
                logging.INFO,
                f"A new settings file was created at {self._path}.",
            )
            self._note(
                logging.DEBUG,
                f"It declares structure version {CONFIG_VERSION}.",
            )
            self.bootstrap_outcome = BootstrapOutcome.CREATED
            values = self._validate(raw)
        else:
            self._note(
                logging.DEBUG,
                f"Found an existing configuration file at {self._path} "
                f"({self._path.stat().st_size} bytes).",
            )
            raw, values = self._load_or_discard()

        self._raw = raw
        self._values = values

        if not narrate:
            if self.bootstrap_outcome is BootstrapOutcome.DISCARDED:
                log.debug(
                    "Configuration read from %s: discarded, the defaults are in force. %s",
                    self._path,
                    self.bootstrap_problem,
                )
            else:
                log.debug("Configuration read from %s.", self._path)
            return

        if self.bootstrap_outcome is BootstrapOutcome.DISCARDED:
            self._note(
                logging.INFO,
                f"The settings file at {self._path} could not be used, so the standard "
                f"settings are in force for this run. The file was left untouched.",
            )
        else:
            self._note(
                logging.DEBUG,
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
            key: dotted, `section.option` - "paths.reports_dir",
                "gui.window_width". Everything before the last dot is the
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
                f"Configuration keys are dotted, as in 'paths.reports_dir'; got {key!r}."
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
        # whatever order the file on disk happens to have.
        ordered = [section for section in SCHEMA if section in self._values]
        ordered += [section for section in self._values if section not in SCHEMA]
        for section in ordered:
            lines.append(f"[{section}]")
            values = self._values[section]
            lines.extend(f"    {key} = {value}" for key, value in values.items())
        return "\n".join(lines)

    @property
    def config_path(self) -> Path:
        """The file this process is using. Absolute, and it exists."""
        return self._path

    @property
    def config_version(self) -> str:
        """Structure version of the file on disk, as written (MAJOR.MINOR.PATCH)."""
        return self._raw.get("meta", {}).get("config_version", "")

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
            ConfigWriteError: the file is discarded (broken, or the wrong
                structure version).
            ConfigKeyError: no such key.
            ConfigSchemaError: the value does not fit the key's type.

        At runtime only CORE calls this - a rule, not a check. The next read in
        any process sees the new value; whoever read it once at startup keeps
        the old one until the next start.
        """
        if self.bootstrap_outcome is BootstrapOutcome.DISCARDED:
            raise ConfigWriteError(
                f"The configuration file {self._path} cannot be used, so pypts runs on "
                f"the defaults; writing one value now would replace the user's file with "
                f"the defaults. Correct or delete the file, or restore the default "
                f"settings to rewrite it deliberately."
            )

        section, _, option = key.rpartition(".")
        if section not in self._raw or option not in self._raw[section]:
            raise ConfigKeyError(f"Unknown configuration key {key!r}.")

        field = _field_for(section, option)
        text = _to_text(value)
        if field is not None:
            # Parsed and thrown away, purely so a bad value is refused here
            # rather than at the next start, when the file is all there is.
            _parse(section, option, text, field)

        # The file is edited in place - one line, in its own section - rather
        # than rebuilt from the template: from the moment it exists it is the
        # user's, keys they added by hand included.
        current = self._path.read_text(encoding="utf-8-sig")
        try:
            changed = template_writer.replace_value(current, section, option, text)
        except KeyError as error:
            raise ConfigKeyError(
                f"Configuration key {key!r} is not in {self._path} any more, so it "
                f"was not changed."
            ) from error
        template_writer.write(self._path, changed)

        self._raw[section][option] = text
        self._values = self._validate(self._raw)
        if field is not None and field.quiet:
            log.debug("Setting '%s' changed to '%s'.", key, text)
        else:
            log.info("Setting '%s' changed to '%s'.", key, text)
        log.debug("Written to %s.", self._path)

    @classmethod
    def restore_default(cls) -> None:
        """
        Rewrite the file as a fresh installation would: template defaults, paths
        and operating system detected again. Every user change is discarded.

        A class method: it needs no read of the old file, so it works on a file
        that is broken or missing too - rewriting it is what fixes it. At
        runtime only CORE calls this, for RestoreDefaultConfig.

        Raises:
            OSError: the file could not be written.
        """
        path = file_locations.config_file_path()
        text = template_writer.render(_read_template(), _build_from_defaults())
        template_writer.write(path, text)
        log.warning("All settings were restored to their defaults.")
        log.debug("Rewrote %s from the template.", path)

    def _write(self, raw: dict[str, dict[str, str]]) -> None:
        """
        Write a whole new file from the template. Only for creating the file and
        for restore_default(); a change to one value goes through set_parameter(),
        which edits the existing file instead.
        """
        template_writer.write(self._path, template_writer.render(self._template_text, raw))
        # Worth a record of its own: this is the only thing in the framework
        # that modifies the user's file, so "was it written, and when" should
        # never have to be inferred from mtime.
        self._note(logging.DEBUG, f"Configuration file written: {self._path}")

    # --- creation, validation ---------------------------------------------------

    def _load_or_discard(
        self,
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
        """
        Read and validate the existing file - or discard it for this run.

        There is no migration and no repair: the file is the user's, and pypts
        never modifies an existing one. If the file cannot be used - it is not
        INI, its structure version is not this pypts', or a value does not fit
        the schema - the whole file is discarded and the template defaults are
        used **in memory** instead. The reason lands in `bootstrap_problem` and
        as an ERROR in the log; the launcher turns it into a notice for the
        operator. Every read applies the same rule to the same file, so a
        discarded file stays discarded, everywhere, until it is corrected.
        """
        raw: dict[str, dict[str, str]] | None = None
        values: dict[str, dict[str, Any]] | None = None
        problem: str | None = None

        try:
            raw = _read_raw(self._path)
        except ConfigSchemaError as error:
            problem = str(error)

        if raw is not None:
            problem = self._structure_version_problem(raw)

        if raw is not None and problem is None:
            try:
                values = self._validate(raw)
            except ConfigSchemaError as error:
                problem = str(error)

        if raw is not None and values is not None and problem is None:
            self.bootstrap_outcome = BootstrapOutcome.LOADED
            return raw, values

        self.bootstrap_outcome = BootstrapOutcome.DISCARDED
        self.bootstrap_problem = problem
        self._note(
            logging.ERROR,
            f"Configuration file {self._path} is discarded for this run: {problem} "
            f"Running on the default template in memory; no parameter was taken from "
            f"the file, and the file was not modified. Correct it, or delete it to "
            f"have it recreated.",
        )
        raw = _build_from_defaults()
        values = self._validate(raw)
        return raw, values

    def _structure_version_problem(self, raw: dict[str, dict[str, str]]) -> str | None:
        """
        One sentence naming the version mismatch, or None when there is none.

        A mismatched version - older or newer - means the file's structure is
        not the one this pypts was written against, so the file is not trusted
        at all; the caller discards it. The version key itself is not repaired
        or rewritten, like everything else in the file.
        """
        found_version = raw.get("meta", {}).get("config_version", "")
        file_major = _major_version(found_version)
        if file_major is None:
            return (
                f"It declares structure version {found_version!r}, which is not a "
                f"MAJOR.MINOR.PATCH version; this pypts expects {CONFIG_VERSION}."
            )

        if file_major == _major_version(CONFIG_VERSION):
            self._note(
                logging.DEBUG,
                f"Configuration declares structure version {found_version}, compatible "
                f"with this pypts' {CONFIG_VERSION}.",
            )
            return None

        return (
            f"It declares structure version {found_version}, but this pypts expects "
            f"{CONFIG_VERSION} (the major number must match)."
        )

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
                    f"{', '.join(sorted(missing))}. Add the missing keys by hand, or "
                    f"delete the file to have it recreated from the template."
                )
            values[section] = converted

        for section in SCHEMA:
            if section not in values:
                raise ConfigSchemaError(
                    f"Configuration in {self._path} has no [{section}] section. Add it "
                    f"by hand, or delete the file to have it recreated from the template."
                )

        return values

    # --- the bootstrap log ------------------------------------------------------

    def _note(self, level: int, message: str) -> None:
        """
        Record something that happened before there was anywhere to log it.

        Only `bootstrap()` narrates; an ordinary read drops these, having
        logged its own one line. Buffered rather than logged, because
        `bootstrap()` runs before the Logger process exists - it is what decides
        where the log file goes. Once a handler is already initialised the
        buffer is pointless, so the message goes straight out instead.
        """
        if not self._narrate:
            return
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


def _build_from_defaults() -> dict[str, dict[str, str]]:
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
        ConfigSchemaError: the file cannot be opened at all, or is not readable
            as INI. Wrapped because this runs before logging exists, where a
            bare configparser traceback is the only thing the user would get.
    """
    parser = configparser.ConfigParser(interpolation=None)
    try:
        # Not parser.read(path): that swallows OSError per-file and returns
        # an empty parser, which downstream then misdiagnoses as a structure-
        # version mismatch. Opening explicitly makes "exists but unreadable"
        # its own, correctly-worded refusal.
        with open(path, encoding="utf-8-sig") as config_file:
            parser.read_file(config_file)
    except OSError as error:
        raise ConfigSchemaError(
            f"{path} exists but cannot be opened: {error}. Correct it, or "
            f"delete it and pypts will create it again from the template."
        ) from error
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
        "reports_dir": str(base / "reports"),
    }


def _major_version(text: str) -> int | None:
    """
    The MAJOR number of a MAJOR.MINOR.PATCH version, or None if `text` is not
    one - including the bare integers the refactor branch used to write.
    """
    parts = text.strip().split(".")
    if len(parts) != 3:
        return None
    for part in parts:
        if not part.isdigit():
            return None
    return int(parts[0])


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
