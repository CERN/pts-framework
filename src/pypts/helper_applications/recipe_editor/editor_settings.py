"""
The Recipe Editor v2's own settings: `[recipe_editor]` in config.ini, and its recent recipes.

The editor is set up like pypts - the same Settings dialog, the same theme cards,
window mode and size - but in a section of its own, so nothing done in the
editor changes pypts' window. It runs without CORE, so it writes config.ini
itself (`save_setting`): the one exception to "only CORE writes at runtime"
(config_handler.md). A write changes one line of the file in place, so pypts
and the editor each change only their own lines.

Recent recipes: the editor shows pypts' list beside its own (`merged_recents`),
but remembers and clears only its own file, `editor_recent_recipes_path()`.
"""

from __future__ import annotations

import logging

from pypts.config_handler import ConfigError, ConfigHandler
from pypts.config_handler.configuration_schema import SCHEMA
from pypts.hmi.gui.settings_dialog import SettingsProfile, setting_text
from pypts.messages.core_hmi_communication import ConfigParameterResult
from pypts.utilities.recent_recipes import MAX_ENTRIES, RecentEntry, RecentRecipes

log = logging.getLogger(__name__)

#: The config.ini section, and its keys.
SECTION = "recipe_editor"
THEME_KEY = f"{SECTION}.theme"
WINDOW_MODE_KEY = f"{SECTION}.window_mode"
WIDTH_KEY = f"{SECTION}.window_width"
HEIGHT_KEY = f"{SECTION}.window_height"

#: What the editor's Edit > Settings shows: Appearance, plus Advanced (Clear
#: recent recipes), which the dialog adds when given a clear callable.
EDITOR_SETTINGS = SettingsProfile(
    pages=(("Appearance", (THEME_KEY, WINDOW_MODE_KEY, WIDTH_KEY, HEIGHT_KEY)),),
    theme_key=THEME_KEY,
    window_keys=(WINDOW_MODE_KEY, WIDTH_KEY, HEIGHT_KEY),
    every_key=False,
    program="the Recipe Editor",
)


def open_config() -> None:
    """
    At start-up, before the window: create config.ini if this machine has none,
    and become this process's writer. An existing file is never modified; a
    broken one is discarded for the run, as pypts does (the Settings dialog
    then says why and offers no Save).
    """
    try:
        config = ConfigHandler.bootstrap()
    except ConfigError as error:
        log.warning("The settings file could not be opened; the defaults are in use.")
        log.debug("ConfigHandler.bootstrap() failed: %s", error)
        return
    config.replay_bootstrap_log()


def window_settings() -> tuple[str, str, int, int]:
    """
    The `[recipe_editor]` settings the window opens with: theme, window mode,
    width, height. With no configuration to read (a test, say): the template's.
    """
    try:
        config = ConfigHandler()
        return (
            config.get_parameter(THEME_KEY),
            config.get_parameter(WINDOW_MODE_KEY),
            config.get_parameter(WIDTH_KEY),
            config.get_parameter(HEIGHT_KEY),
        )
    except ConfigError as error:
        log.debug("No configuration to take the editor's window settings from (%s).", error)
        fields = SCHEMA[SECTION]
        return (
            fields["theme"].default,
            fields["window_mode"].default,
            int(fields["window_width"].default),
            int(fields["window_height"].default),
        )


def setting_values() -> tuple[dict[str, str], str | None]:
    """
    The values the Settings dialog opens with, as text, and why the file was
    discarded at start-up (None if it was not). With no configuration at all,
    the dialog shows the defaults and offers no Save.
    """
    try:
        config = ConfigHandler()
    except ConfigError as error:
        return {}, f"There is no settings file to save to: {error}"
    values = {}
    for section, options in config.get_whole_config().items():
        for key, value in options.items():
            values[f"{section}.{key}"] = setting_text(value)
    problem = None
    if config.bootstrap_problem is not None:
        problem = config.bootstrap_problem
    return values, problem


def save_setting(key: str, text: str) -> ConfigParameterResult:
    """Write one setting to config.ini, answered the way CORE answers pypts."""
    try:
        ConfigHandler().set_parameter(key, text)
    except ConfigError as error:
        log.warning("Setting '%s' was not saved: %s", key, error)
        return ConfigParameterResult(key=key, value=text, accepted=False, reason=str(error))
    return ConfigParameterResult(key=key, value=text, accepted=True, reason="")


def merged_recents(own: RecentRecipes, pypts: RecentRecipes) -> list[RecentEntry]:
    """
    The editor's Open Recent: its own list and pypts', newest first, each file
    once (the editor's entry wins), at most MAX_ENTRIES.
    """
    seen: set[str] = set()
    merged: list[RecentEntry] = []
    for entry in own.entries() + pypts.entries():
        if entry.path in seen:
            continue
        seen.add(entry.path)
        merged.append(entry)
    # Stable: on equal times the editor's own entry stays first.
    merged.sort(key=lambda entry: entry.opened_at, reverse=True)
    return merged[:MAX_ENTRIES]
