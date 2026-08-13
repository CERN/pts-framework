# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Config Handler module (src/pypts/config_handler/).

Every test runs against a config file in `tmp_path`: the `config` fixture
monkeypatches `file_locations.config_file_path`, which is the only place the handler
asks where the file is, and drops the singleton so the next call builds a fresh
one. Nothing here touches the real per-user configuration.

Two of these earn their place beyond ordinary coverage.
`test_schema_and_template_agree` is the config structure verification tool the
specification asks for - it fails if a key exists in `configuration_schema.py`
but not in
`config_template.ini` or the other way round, which is the mistake that
otherwise ships as a `ConfigSchemaError` on a user's machine.
`test_a_second_bootstrap_does_not_touch_the_file` guards the defect this module
was rewritten to fix: reading the configuration used to rewrite it, so every
process rewrote it once per run.
"""

import configparser
import logging
import re
import threading

import pytest

from pypts.config_handler import file_locations, template_writer
from pypts.config_handler.config_handler import (
    ConfigFileMissing,
    ConfigHandler,
    ConfigKeyError,
    ConfigSchemaError,
    ConfigWriteError,
    Role,
    _parse,
    _read_template,
)
from pypts.config_handler.configuration_schema import CONFIG_VERSION, SCHEMA, Field


def with_log_level(text: str, level: str) -> str:
    """
    Rewrite the `[logging] level` line, whatever it currently says.

    Matched on the key rather than on the shipped value, because that value is
    deliberately not stable: it is DEBUG while the framework is being refactored
    and goes back to INFO before v1.0. Tests that patched the literal
    `level = INFO` broke the day it changed, which told us nothing about the
    config handler and everything about the test.
    """
    return re.sub(r"^level = .*$", f"level = {level}", text, count=1, flags=re.MULTILINE)


#: A pre-versioned config.ini, as the previous implementation wrote it. The
#: logs_dir is deliberately not the default: migration has to keep it.
LEGACY_CONFIG = """\
[OperatingSystem]
name = Linux
version = 5.15.0
architecture = x86_64
kernel = generic

[Paths]
base_temp_dir = /tmp/pypts
logs_dir = /my/own/logs
config_dir = /tmp/pypts/config

[Application]
log_level = WARNING
app_version = 1.0.0

[Misc]
example_flag = True
"""


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Point the handler at tmp_path and give every test a cold singleton."""
    path = tmp_path / "config.ini"
    monkeypatch.setattr(file_locations, "config_file_path", lambda: path)
    ConfigHandler.reset_for_testing()
    yield path
    ConfigHandler.reset_for_testing()


@pytest.fixture
def config(config_path):
    """A bootstrapped writer, i.e. what the launcher holds."""
    return ConfigHandler.bootstrap()


# --- creation -------------------------------------------------------------------


def test_config_is_created_from_the_template_when_missing(config_path):
    assert not config_path.exists()

    handler = ConfigHandler.bootstrap()

    assert config_path.exists()
    assert handler.config_path == config_path
    assert handler.config_version == CONFIG_VERSION


def test_creation_fills_in_the_paths_for_this_platform(config):
    base = config.get_parameter("paths.base_dir")

    assert base.is_absolute()
    assert config.get_parameter("paths.logs_dir") == base / "logs"
    assert config.get_parameter("paths.reports_dir") == base / "reports"


def test_operating_system_section_is_filled_in_at_creation(config):
    """Detected, so it is whatever this machine is - but never left blank."""
    for key in ("name", "version", "architecture", "kernel"):
        assert config.get_parameter(f"operating_system.{key}")


def test_operating_system_is_not_rewritten_after_creation(config):
    """
    It records the machine the configuration was set up on. Rewriting it on
    every start would make it a detected value pretending to be a setting.
    """
    config.set_parameter("operating_system.name", "Recorded-Once")
    config.set_parameter("gui.theme", "dark")

    assert config.get_parameter("operating_system.name") == "Recorded-Once"


def test_no_path_in_the_template_is_platform_specific():
    """
    The template used to ship /tmp/pypts, which is wrong on Windows. Path values
    are blank in it now and filled in at creation, so there is nothing left to
    be wrong on either platform.
    """
    template = _read_raw_template()

    for key in SCHEMA["paths"]:
        assert template["paths"][key] == "", f"{key} should be derived, not shipped"


def test_a_reader_will_not_create_the_file(config_path):
    with pytest.raises(ConfigFileMissing):
        ConfigHandler()

    assert not config_path.exists()


# --- reading --------------------------------------------------------------------


def test_values_come_back_as_their_declared_type(config):
    assert config.get_parameter("gui.window_width") == 1280
    assert config.get_parameter("hardware.example_device.timeout_s") == 5.0
    # DEBUG while the refactor is on - see the note in config_template.ini.
    assert config.get_parameter("logging.level") == "DEBUG"
    assert config.get_parameter("paths.logs_dir").is_absolute()


def test_unknown_key_raises_and_says_what_the_section_holds(config):
    with pytest.raises(ConfigKeyError) as error:
        config.get_parameter("paths.logs_dr")

    assert "paths.logs_dr" in str(error.value)
    assert "logs_dir" in str(error.value)


def test_unknown_section_raises(config):
    with pytest.raises(ConfigKeyError):
        config.get_parameter("nowhere.at_all")


def test_a_default_is_returned_instead_of_raising(config):
    assert config.get_parameter("paths.nothing_here", default=None) is None
    assert config.get_parameter("nowhere.at_all", default=7) == 7


def test_get_whole_config_is_read_only(config):
    whole = config.get_whole_config()

    assert whole["gui"]["window_width"] == 1280
    with pytest.raises(TypeError):
        whole["gui"]["window_width"] = 5


def test_dump_names_the_file_it_read(config):
    dumped = config.dump()

    assert str(config.config_path) in dumped
    assert "[paths]" in dumped
    assert "window_width = 1280" in dumped


# --- the singleton ---------------------------------------------------------------


def test_one_instance_per_process(config):
    assert ConfigHandler() is config


def test_first_construction_is_thread_safe(config_path):
    """
    Sequencer and Report become threads of the engine process, so two threads
    can reach a cold singleton at the same moment. They must not get two
    handlers, each having parsed the file.
    """
    ConfigHandler.bootstrap()
    ConfigHandler.reset_for_testing()

    instances = []
    barrier = threading.Barrier(8)

    def build():
        barrier.wait()
        instances.append(ConfigHandler())

    threads = [threading.Thread(target=build) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(instances) == 8
    assert len({id(instance) for instance in instances}) == 1


# --- who may write ----------------------------------------------------------------


def test_a_reader_cannot_write(config_path):
    ConfigHandler.bootstrap()
    ConfigHandler.reset_for_testing()
    reader = ConfigHandler()

    assert reader.role is Role.READER
    with pytest.raises(ConfigWriteError):
        reader.set_parameter("gui.theme", "dark")
    with pytest.raises(ConfigWriteError):
        reader.restore_default()


def test_a_reader_cannot_be_promoted_to_writer(config_path):
    ConfigHandler.bootstrap()
    ConfigHandler.reset_for_testing()
    ConfigHandler()

    with pytest.raises(ConfigWriteError):
        ConfigHandler.open_for_writing()


def test_the_writer_writes_and_the_value_survives_a_restart(config, config_path):
    config.set_parameter("gui.theme", "dark")
    config.set_parameter("paths.reports_dir", str(config_path.parent / "elsewhere"))

    ConfigHandler.reset_for_testing()
    reopened = ConfigHandler()

    assert reopened.get_parameter("gui.theme") == "dark"
    assert reopened.get_parameter("paths.reports_dir").name == "elsewhere"


def test_user_edits_survive_a_restart(config, config_path):
    """The file is the user's. Editing it by hand is the supported way in."""
    config_path.write_text(
        with_log_level(config_path.read_text(encoding="utf-8"), "ERROR"),
        encoding="utf-8",
    )

    ConfigHandler.reset_for_testing()

    assert ConfigHandler.bootstrap().get_parameter("logging.level") == "ERROR"


def test_a_rejected_value_never_reaches_the_file(config, config_path):
    with pytest.raises(ConfigSchemaError):
        config.set_parameter("gui.theme", "chartreuse")

    assert "chartreuse" not in config_path.read_text(encoding="utf-8")
    assert config.get_parameter("gui.theme") == "default"


def test_restore_default_discards_user_values(config):
    config.set_parameter("gui.theme", "dark")

    config.restore_default()

    assert config.get_parameter("gui.theme") == "default"


def test_a_second_bootstrap_does_not_touch_the_file(config, config_path):
    """
    The defect this module was rewritten to fix: reading used to write, so every
    process rewrote config.ini once per run.
    """
    before = config_path.read_bytes(), config_path.stat().st_mtime_ns

    ConfigHandler.reset_for_testing()
    ConfigHandler.bootstrap()

    assert (config_path.read_bytes(), config_path.stat().st_mtime_ns) == before


# --- validation --------------------------------------------------------------------


def test_a_value_of_the_wrong_type_is_refused_by_name(config, config_path):
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "window_width = 1280", "window_width = wide"
        ),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with pytest.raises(ConfigSchemaError) as error:
        ConfigHandler()

    assert "gui.window_width" in str(error.value)


def test_a_value_outside_the_allowed_set_is_refused(config, config_path):
    config_path.write_text(
        with_log_level(config_path.read_text(encoding="utf-8"), "CHATTY"),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with pytest.raises(ConfigSchemaError) as error:
        ConfigHandler()

    assert "logging.level" in str(error.value)
    assert "DEBUG" in str(error.value)


def test_a_file_saved_with_a_byte_order_mark_still_reads(config, config_path):
    """
    Notepad writes UTF-8 with a BOM by default, and this file exists to be
    edited by hand on a Windows bench. Read as plain utf-8 the BOM lands in
    front of the first section header and configparser refuses the whole file.
    """
    config_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8-sig")
    ConfigHandler.reset_for_testing()

    assert ConfigHandler().get_parameter("gui.window_width") == 1280


def test_a_file_that_is_not_ini_is_refused_with_an_explanation(config, config_path):
    """
    Raised before logging exists, so the message is all the user gets - it has
    to say which file and what to do about it, not just what configparser thinks.
    """
    config_path.write_text("this is not an ini file\n", encoding="utf-8")
    ConfigHandler.reset_for_testing()

    with pytest.raises(ConfigSchemaError) as error:
        ConfigHandler.bootstrap()

    assert str(config_path) in str(error.value)
    assert "delete it" in str(error.value)


def test_the_file_pypts_writes_has_no_byte_order_mark(config, config_path):
    config.set_parameter("gui.theme", "dark")

    assert not config_path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_bootstrap_repairs_a_key_deleted_by_hand(config, config_path):
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("window_height = 720", ""),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    assert ConfigHandler.bootstrap().get_parameter("gui.window_height") == 720


def test_a_reader_refuses_a_file_the_launcher_has_not_repaired(config, config_path):
    """
    A reader cannot repair - it is not the writer - so it must say what is wrong
    rather than carry on with half a configuration.
    """
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("window_height = 720", ""),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with pytest.raises(ConfigSchemaError) as error:
        ConfigHandler()

    assert "window_height" in str(error.value)


def test_a_file_from_a_newer_pypts_is_refused(config, config_path):
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            f"config_version = {CONFIG_VERSION}", f"config_version = {CONFIG_VERSION + 5}"
        ),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with pytest.raises(ConfigSchemaError) as error:
        ConfigHandler.bootstrap()

    assert "newer" in str(error.value)


# --- structured data ----------------------------------------------------------------


def test_a_user_added_device_is_read_with_the_family_types(config, config_path):
    """
    Hardware is one section per device, `hardware.<logical name>`, validated
    against the fields of the example section. The names are the user's, so the
    schema cannot list them.
    """
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[hardware.dmm1]\ndriver = nidmm\nresource = PXI1Slot2\ntimeout_s = 2.5\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()
    reopened = ConfigHandler.bootstrap()

    assert reopened.get_parameter("hardware.dmm1.driver") == "nidmm"
    assert reopened.get_parameter("hardware.dmm1.timeout_s") == 2.5


def test_a_user_added_device_survives_a_rewrite(config, config_path):
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[hardware.dmm1]\ndriver = nidmm\nresource = PXI1Slot2\ntimeout_s = 2.5\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()
    reopened = ConfigHandler.bootstrap()

    reopened.set_parameter("gui.theme", "dark")

    assert "[hardware.dmm1]" in config_path.read_text(encoding="utf-8")
    assert reopened.get_parameter("hardware.dmm1.resource") == "PXI1Slot2"


# --- migration -------------------------------------------------------------------------


def test_migration_keeps_user_values_and_maps_renamed_keys(config_path):
    config_path.write_text(LEGACY_CONFIG, encoding="utf-8")

    migrated = ConfigHandler.bootstrap()

    assert migrated.config_version == CONFIG_VERSION
    # Compared as parts, because a POSIX path read on Windows keeps its
    # components but not its separators.
    assert migrated.get_parameter("paths.logs_dir").parts[-3:] == ("my", "own", "logs")
    assert migrated.get_parameter("logging.level") == "WARNING"
    assert migrated.get_parameter("operating_system.name") == "Linux"


def test_migration_adds_the_keys_the_new_version_introduced(config_path):
    config_path.write_text(LEGACY_CONFIG, encoding="utf-8")

    migrated = ConfigHandler.bootstrap()

    assert migrated.get_parameter("report.type") == "html"
    assert migrated.get_parameter("gui.window_width") == 1280
    assert migrated.get_parameter("paths.reports_dir").is_absolute()


def test_migration_keeps_the_previous_file(config_path):
    config_path.write_text(LEGACY_CONFIG, encoding="utf-8")

    ConfigHandler.bootstrap()

    backup = config_path.with_suffix(".ini.v0.bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == LEGACY_CONFIG


def test_migration_drops_keys_that_no_longer_mean_anything(config_path):
    config_path.write_text(LEGACY_CONFIG, encoding="utf-8")

    ConfigHandler.bootstrap()

    text = config_path.read_text(encoding="utf-8")
    assert "example_flag" not in text
    assert "config_dir" not in text
    assert "app_version" not in text


def test_migration_is_reported_once_logging_exists(config_path, caplog):
    """
    Bootstrap runs before the Logger process, so it buffers. Nothing about a
    migration may be lost just because it happened too early to log.
    """
    config_path.write_text(LEGACY_CONFIG, encoding="utf-8")
    migrated = _bootstrap_before_logging()

    with caplog.at_level(logging.INFO):
        migrated.replay_bootstrap_log()

    replayed = caplog.text
    assert "migrated" in replayed
    assert "logging.level" in replayed
    assert str(config_path) in replayed


def test_the_bootstrap_log_is_emptied_by_replaying_it(config_path, caplog):
    handler = _bootstrap_before_logging()
    handler.replay_bootstrap_log()

    with caplog.at_level(logging.INFO):
        handler.replay_bootstrap_log()

    assert caplog.text == ""


def test_creating_the_file_is_narrated(config_path, caplog):
    """
    The launcher's first run is where "why is my log over there" is answered, so
    the log has to name the directory, say the file was absent, and say it was
    created.
    """
    handler = _bootstrap_before_logging()

    with caplog.at_level(logging.DEBUG):
        handler.replay_bootstrap_log()

    assert "No configuration file at" in caplog.text
    assert "creating one from the template" in caplog.text
    assert "Configuration created at" in caplog.text
    assert str(config_path) in caplog.text


def test_finding_an_existing_file_is_narrated(config, config_path, caplog):
    ConfigHandler.reset_for_testing()
    handler = _bootstrap_before_logging()

    with caplog.at_level(logging.DEBUG):
        handler.replay_bootstrap_log()

    assert "Found an existing configuration file" in caplog.text
    assert "nothing to migrate" in caplog.text
    assert "creating one from the template" not in caplog.text


def test_a_reader_says_it_will_not_repair(config, config_path, caplog):
    ConfigHandler.reset_for_testing()
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    try:
        reader = ConfigHandler()
    finally:
        root.handlers.extend(saved)

    with caplog.at_level(logging.DEBUG):
        reader.replay_bootstrap_log()

    assert "opened as reader" in caplog.text
    assert "neither creates nor repairs" in caplog.text


def test_every_value_in_force_is_logged_at_debug(config, caplog):
    """`config.dump()` for a console; this is the same thing for the run log."""
    ConfigHandler.reset_for_testing()
    handler = _bootstrap_before_logging()

    with caplog.at_level(logging.DEBUG):
        handler.replay_bootstrap_log()

    assert "Configuration value paths.logs_dir = " in caplog.text
    assert "Configuration value gui.window_width = 1280" in caplog.text
    assert "Configuration value hardware.example_device.timeout_s = 5.0" in caplog.text


def test_the_value_dump_is_debug_only(config, caplog):
    """One line per key is right for a trace and wrong for a normal run."""
    ConfigHandler.reset_for_testing()
    handler = _bootstrap_before_logging()

    with caplog.at_level(logging.INFO):
        handler.replay_bootstrap_log()

    assert "Configuration value" not in caplog.text
    assert "Configuration loaded from" in caplog.text


def test_nothing_is_buffered_once_logging_is_up(config_path, caplog):
    """
    The buffer is for the launcher's head start, not a second log. With handlers
    installed the handler logs straight out, and replaying finds nothing left.
    """
    with caplog.at_level(logging.INFO):
        handler = ConfigHandler.bootstrap()

    assert str(config_path) in caplog.text
    caplog.clear()

    with caplog.at_level(logging.INFO):
        handler.replay_bootstrap_log()

    assert caplog.text == ""


# --- comments -----------------------------------------------------------------------------


def test_comments_survive_a_write(config, config_path):
    """
    configparser.write() would drop every one of them. The file is edited by
    hand on a bench, and the comments are what say what a key means.
    """
    before = _comment_lines(config_path.read_text(encoding="utf-8"))

    config.set_parameter("gui.theme", "dark")

    assert _comment_lines(config_path.read_text(encoding="utf-8")) == before
    assert before


def test_writing_changes_only_the_line_it_was_asked_to_change(config, config_path):
    before = config_path.read_text(encoding="utf-8").splitlines()

    config.set_parameter("gui.theme", "dark")

    after = config_path.read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    differences = [
        (old, new) for old, new in zip(before, after, strict=True) if old != new
    ]
    assert differences == [("theme = default", "theme = dark")]


def test_the_writer_keeps_a_section_the_template_does_not_have():
    rendered = template_writer.render(
        "[gui]\n# a comment\ntheme = default\n",
        {"gui": {"theme": "dark"}, "hardware.dmm1": {"driver": "nidmm"}},
    )

    assert "theme = dark" in rendered
    assert "# a comment" in rendered
    assert "[hardware.dmm1]" in rendered
    assert "driver = nidmm" in rendered


# --- the structure verification tool ---------------------------------------------------------


def test_schema_and_template_agree():
    """
    configuration_schema.py declares the types, config_template.ini carries the values and the
    comments, and they describe one structure. This is the check that keeps them
    from drifting - without it, a key added to one and forgotten in the other
    reaches a user as a ConfigSchemaError on startup.
    """
    template = _read_raw_template()

    assert set(template) == set(SCHEMA), "sections differ between template and schema"

    for section, fields in SCHEMA.items():
        assert set(template[section]) == set(fields), f"keys differ in [{section}]"


def test_every_template_default_is_valid_for_its_type():
    template = _read_raw_template()

    for section, fields in SCHEMA.items():
        for key, field in fields.items():
            shipped = template[section][key]
            if field.derived:
                assert shipped == "", f"derived key '{section}.{key}' should ship blank"
            else:
                assert shipped == field.default, f"default differs for '{section}.{key}'"
                _parse_or_fail(section, key, shipped, field)


def test_the_template_declares_the_current_structure_version():
    assert _read_raw_template()["meta"]["config_version"] == str(CONFIG_VERSION)


# --- helpers ---------------------------------------------------------------------------------


def _bootstrap_before_logging() -> ConfigHandler:
    """
    Bootstrap with no logging handlers installed, which is the state the
    launcher is really in: it configures the configuration before it configures
    logging, because the configuration is what says where the log file goes.

    pytest installs a root handler of its own, so without this the handler would
    log immediately and the buffer - the thing under test - would stay empty.
    """
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    try:
        return ConfigHandler.bootstrap()
    finally:
        root.handlers.extend(saved)


def _read_raw_template():
    """The shipped template, parsed the same way a real config file is."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(_read_template())
    return {section: dict(parser[section]) for section in parser.sections()}


def _parse_or_fail(section: str, key: str, text: str, field: Field):
    try:
        return _parse(section, key, text, field)
    except ConfigSchemaError as error:  # pragma: no cover - only on a broken template
        pytest.fail(f"template default for '{section}.{key}' is not a valid {field.type}: {error}")


def _comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("#")]
