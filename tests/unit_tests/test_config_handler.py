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
    BootstrapOutcome,
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
    assert handler.bootstrap_outcome is BootstrapOutcome.CREATED


def test_an_existing_valid_file_is_loaded(config, config_path):
    ConfigHandler.reset_for_testing()

    reopened = ConfigHandler.bootstrap()

    assert reopened.bootstrap_outcome is BootstrapOutcome.LOADED
    assert reopened.bootstrap_problem is None


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


def test_a_value_of_the_wrong_type_discards_the_file_and_names_the_key(config, config_path):
    """
    There is no repair and no partial use: a file with one bad value is
    discarded whole, the defaults are in force in memory, and the reason names
    the key so the user knows what to fix.
    """
    broken = config_path.read_text(encoding="utf-8").replace(
        "window_width = 1280", "window_width = wide"
    )
    config_path.write_text(broken, encoding="utf-8")
    ConfigHandler.reset_for_testing()

    handler = ConfigHandler()

    assert handler.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert handler.bootstrap_problem is not None
    assert "gui.window_width" in handler.bootstrap_problem
    assert handler.get_parameter("gui.window_width") == 1280
    # Discarded, not rewritten: the broken file is exactly as the user left it.
    assert config_path.read_text(encoding="utf-8") == broken


def test_a_value_outside_the_allowed_set_discards_the_file(config, config_path):
    config_path.write_text(
        with_log_level(config_path.read_text(encoding="utf-8"), "CHATTY"),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    handler = ConfigHandler()

    assert handler.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert handler.bootstrap_problem is not None
    assert "logging.level" in handler.bootstrap_problem
    assert "DEBUG" in handler.bootstrap_problem


def test_a_file_saved_with_a_byte_order_mark_still_reads(config, config_path):
    """
    Notepad writes UTF-8 with a BOM by default, and this file exists to be
    edited by hand on a Windows bench. Read as plain utf-8 the BOM lands in
    front of the first section header and configparser refuses the whole file.
    """
    config_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8-sig")
    ConfigHandler.reset_for_testing()

    assert ConfigHandler().get_parameter("gui.window_width") == 1280


def test_a_file_that_is_not_ini_is_discarded_with_an_explanation(config, config_path):
    """
    The reason becomes the launcher's notice, so it has to say which file and
    what to do about it, not just what configparser thinks.
    """
    config_path.write_text("this is not an ini file\n", encoding="utf-8")
    ConfigHandler.reset_for_testing()

    handler = ConfigHandler.bootstrap()

    assert handler.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert handler.bootstrap_problem is not None
    assert str(config_path) in handler.bootstrap_problem
    assert "delete it" in handler.bootstrap_problem
    assert handler.get_parameter("gui.window_width") == 1280


def test_an_unopenable_file_is_reported_as_unopenable_not_version_zero(config_path):
    """
    A file that exists but cannot be opened - wrong ACL on a shared bench, or
    held by another tool - used to be swallowed by `ConfigParser.read()`, which
    skips an unreadable file silently. The empty result then read as
    `config_version = 0` and the operator was told to fix a version key that was
    perfectly fine. The reason has to name the real cause.

    A directory at the config path is the deterministic way to produce that: it
    exists, and opening it raises PermissionError on Windows and
    IsADirectoryError on Linux - both OSError.
    """
    config_path.mkdir()

    handler = ConfigHandler.bootstrap()

    assert handler.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert handler.bootstrap_problem is not None
    assert "cannot be opened" in handler.bootstrap_problem
    assert "structure version" not in handler.bootstrap_problem
    assert str(config_path) in handler.bootstrap_problem
    assert "delete it" in handler.bootstrap_problem
    assert handler.get_parameter("gui.window_width") == 1280


def test_the_file_pypts_writes_has_no_byte_order_mark(config, config_path):
    config.set_parameter("gui.theme", "dark")

    assert not config_path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_a_key_deleted_by_hand_discards_the_file(config, config_path):
    """
    There is no repair: the file is the user's, and pypts never modifies an
    existing one. A missing key discards the file for the run; the reason names
    the key so the user can add it back, or delete the file to start over.
    """
    broken = config_path.read_text(encoding="utf-8").replace("window_height = 720", "")
    config_path.write_text(broken, encoding="utf-8")
    ConfigHandler.reset_for_testing()

    handler = ConfigHandler.bootstrap()

    assert handler.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert handler.bootstrap_problem is not None
    assert "window_height" in handler.bootstrap_problem
    assert handler.get_parameter("gui.window_height") == 720
    # Discarded, not rewritten: the broken file is exactly as the user left it.
    assert config_path.read_text(encoding="utf-8") == broken


def test_a_reader_applies_the_same_discard_rule(config, config_path):
    """
    Every process reads the file for itself, so every process has to reach the
    same verdict about it - a run must agree with itself about the values in
    force.
    """
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("window_height = 720", ""),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    reader = ConfigHandler()

    assert reader.role is Role.READER
    assert reader.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert reader.get_parameter("gui.window_height") == 720


# --- sections the schema does not know ------------------------------------------------


def test_a_user_added_section_is_kept_as_text_and_reported(config, config_path, caplog):
    """
    The schema is a flat list of named sections; a hardware section is not one of
    them, and what a bench looks like is Phase 5's question. Until it is answered
    an added section is neither typed nor discarded: its values come back exactly
    as they were written, and it is reported once, because a section nothing
    reads may equally well be a typo.
    """
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[hardware.dmm1]\ndriver = nidmm\nresource = PXI1Slot2\ntimeout_s = 2.5\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with caplog.at_level(logging.WARNING):
        reopened = ConfigHandler.bootstrap()

    assert reopened.get_parameter("hardware.dmm1.driver") == "nidmm"
    assert reopened.get_parameter("hardware.dmm1.timeout_s") == "2.5"
    assert "[hardware.dmm1] is not part of the schema" in caplog.text


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


# --- the structure version -------------------------------------------------------------


def test_a_version_mismatch_discards_the_file_for_this_run(config, config_path, caplog):
    """
    A file with the wrong structure version is not trusted at all - even one
    whose values would validate. The defaults are in force in memory, the file
    is never touched, and the reason is an ERROR in the log.
    """
    mismatched = config_path.read_text(encoding="utf-8").replace(
        f"config_version = {CONFIG_VERSION}", f"config_version = {CONFIG_VERSION + 5}"
    )
    mismatched = mismatched.replace("window_width = 1280", "window_width = 999")
    config_path.write_text(mismatched, encoding="utf-8")
    ConfigHandler.reset_for_testing()

    handler = _bootstrap_before_logging()

    assert handler.bootstrap_outcome is BootstrapOutcome.DISCARDED
    assert handler.bootstrap_problem is not None
    assert str(CONFIG_VERSION + 5) in handler.bootstrap_problem
    assert f"expects {CONFIG_VERSION}" in handler.bootstrap_problem
    # The defaults are in force, not the file's values.
    assert handler.get_parameter("gui.window_width") == 1280
    # Never modified: the mismatch is the user's to resolve.
    assert config_path.read_text(encoding="utf-8") == mismatched

    with caplog.at_level(logging.ERROR):
        handler.replay_bootstrap_log()

    assert "discarded" in caplog.text
    assert f"expects {CONFIG_VERSION}" in caplog.text
    assert str(config_path) in caplog.text


def test_a_discarded_configuration_refuses_runtime_writes(config, config_path):
    """
    Writing one value while running on in-memory defaults would replace the
    user's file with the defaults - exactly the modification pypts promises
    never to make.
    """
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("window_height = 720", ""),
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()
    writer = ConfigHandler.bootstrap()

    assert writer.bootstrap_outcome is BootstrapOutcome.DISCARDED
    with pytest.raises(ConfigWriteError) as error:
        writer.set_parameter("gui.theme", "dark")

    assert "discarded" in str(error.value)


def test_restore_default_ends_the_discarded_state(config, config_path):
    """
    restore_default() rewrites the file with the defaults deliberately, so
    afterwards the file and the values in force agree again and writing works.
    """
    config_path.write_text("this is not an ini file\n", encoding="utf-8")
    ConfigHandler.reset_for_testing()
    writer = ConfigHandler.bootstrap()
    assert writer.bootstrap_outcome is BootstrapOutcome.DISCARDED

    writer.restore_default()

    assert writer.bootstrap_outcome is BootstrapOutcome.LOADED
    assert writer.bootstrap_problem is None
    writer.set_parameter("gui.theme", "dark")
    assert "theme = dark" in config_path.read_text(encoding="utf-8")


# --- the bootstrap log -------------------------------------------------------------------


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
    assert "declares the current structure version" in caplog.text
    assert "creating one from the template" not in caplog.text


def test_a_reader_narrates_its_role(config, config_path, caplog):
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


def test_every_value_in_force_is_logged_at_debug(config, caplog):
    """`config.dump()` for a console; this is the same thing for the run log."""
    ConfigHandler.reset_for_testing()
    handler = _bootstrap_before_logging()

    with caplog.at_level(logging.DEBUG):
        handler.replay_bootstrap_log()

    assert "Configuration value paths.logs_dir = " in caplog.text
    assert "Configuration value gui.window_width = 1280" in caplog.text
    assert "Configuration value report.type = html" in caplog.text


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
