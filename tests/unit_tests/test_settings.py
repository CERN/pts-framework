# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for Edit > Settings (src/pypts/hmi/gui/settings_dialog.py) and for
the [gui] theme both windows open with.

Three layers, top to bottom of this file: the dialog on its own, driven with a
`send` and a `preview_theme` callable and no CORE; the dialog inside the GUI,
with CORE's answers arriving on the inbox; and `configured_theme()`, the one
reading of `[gui] theme` that pypts and the Recipe Creator share.

Like test_hmi_gui.py, nothing here may read the operator's real config.ini or
follow the real operating system's theme - see `isolated_configuration`.
"""

import queue
import re

import pytest

from pypts.config_handler import file_locations
from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import ConfigParameterResult, SetConfigParameter

pytest.importorskip("PySide6", reason="the GUI is an optional extra")


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    """
    No test may read the operator's real config.ini or recent-recipes list, nor
    follow the real OS theme. The config points at a file that does not exist
    until a test writes one with `a_config_file()`.
    """
    from pypts.config_handler import ConfigHandler
    from pypts.hmi.gui import gui as gui_module

    monkeypatch.setattr(
        file_locations, "config_file_path", lambda: tmp_path / "config" / "config.ini"
    )
    monkeypatch.setattr(
        file_locations, "recent_recipes_path", lambda: tmp_path / "state" / "recent.json"
    )
    monkeypatch.setattr(gui_module, "detect_system_dark_mode", lambda app=None: False)
    ConfigHandler.reset_for_testing()
    yield
    ConfigHandler.reset_for_testing()


def a_config_file(settings=None):
    """
    Write a real config.ini where `isolated_configuration` points, with some
    values replaced, then drop the singleton - so what is built next reads the
    file the way a fresh process would.

    Args:
        settings: dotted key -> value as it should appear in the file, e.g.
            {"gui.theme": "dark"}. Replaced inside its own section, because
            `theme` is a key of both [report] and [gui].
    """
    from pypts.config_handler import ConfigHandler

    path = file_locations.config_file_path()
    ConfigHandler.bootstrap()
    text = path.read_text(encoding="utf-8")
    for dotted, value in (settings or {}).items():
        section, _, key = dotted.rpartition(".")
        head, header, rest = text.partition(f"[{section}]")
        rest = re.sub(rf"^{key} = .*$", f"{key} = {value}", rest, count=1, flags=re.MULTILINE)
        text = head + header + rest
    path.write_text(text, encoding="utf-8")
    ConfigHandler.reset_for_testing()
    return path


@pytest.fixture
def gui_factory(qapp):
    """Builds a GUI when the test asks, so config.ini can be written first."""
    from pypts.hmi.gui.gui import GUI

    built = []

    def build():
        outbox: queue.Queue = queue.Queue()
        inbox: queue.Queue = queue.Queue()
        instance = GUI(QueueWrapper(outbox), QueueWrapper(inbox))
        built.append(instance)
        return instance, outbox, QueueWrapper(inbox)

    yield build
    for instance in built:
        instance.timer.stop()
        instance.window.allow_close = True
        instance.window.close()


def drain(a_queue):
    messages = []
    while True:
        try:
            messages.append(a_queue.get_nowait())
        except queue.Empty:
            return messages


def all_text(widget):
    from PySide6.QtWidgets import QLabel, QPushButton

    return [
        child.text() for child in widget.findChildren(QLabel) + widget.findChildren(QPushButton)
    ]


def settings_in_force(tmp_path):
    """What a dialog is opened with: every editable key, as text."""
    return {
        "paths.base_dir": str(tmp_path),
        "paths.logs_dir": str(tmp_path / "logs"),
        "paths.reports_dir": str(tmp_path / "reports"),
        "logging.level": "INFO",
        "report.type": "html",
        "report.theme": "default",
        "gui.theme": "light",
        "gui.window_width": "1280",
        "gui.window_height": "720",
        "watchdog.enabled": "true",
    }


def a_settings_dialog(tmp_path, sent=None, **options):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    if sent is None:
        sent = []
    return SettingsDialog(
        settings_in_force(tmp_path), lambda key, value: sent.append((key, value)), **options
    )


# --------------------------------------------------------------------------
# The dialog on its own
# --------------------------------------------------------------------------


def test_the_dialog_offers_every_setting_but_the_managed_ones(qapp, tmp_path):
    """`meta` and `operating_system` are not settings; everything else is."""
    from pypts.hmi.gui.settings_dialog import editable_keys

    dialog = a_settings_dialog(tmp_path)

    assert sorted(dialog.editors) == sorted(editable_keys())
    assert not [key for key in dialog.editors if key.startswith(("meta.", "operating_system."))]
    dialog.close()


def test_the_settings_are_grouped_into_pages(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    titles = [dialog.nav.item(row).text() for row in range(dialog.nav.count())]
    assert titles == ["Appearance", "Folders", "Logging", "Report", "Advanced"]

    dialog.nav.setCurrentRow(1)

    assert dialog.pages.currentIndex() == 1
    dialog.close()


def test_a_key_no_page_names_still_gets_a_page(monkeypatch):
    """A key added to the schema must never be left out of the dialog."""
    from pypts.hmi.gui import settings_dialog

    monkeypatch.setattr(settings_dialog, "PAGES", (("Appearance", ("gui.theme",)),))

    pages = settings_dialog.pages_for_schema()

    placed = [key for _title, keys in pages for key in keys]
    assert sorted(placed) == sorted(settings_dialog.editable_keys())
    assert ("Paths", ("paths.base_dir", "paths.logs_dir", "paths.reports_dir")) in pages


def test_the_theme_is_picked_from_three_cards(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)
    cards = dialog.editors["gui.theme"].buttons

    assert list(cards) == ["light", "dark", "system"]
    assert cards["light"].isChecked() is True

    cards["dark"].click()

    assert dialog.text_of("gui.theme") == "dark"
    assert cards["light"].isChecked() is False
    dialog.close()


def test_picking_a_theme_previews_it_and_cancel_puts_it_back(qapp, tmp_path):
    previews = []
    dialog = a_settings_dialog(tmp_path, preview_theme=previews.append)

    dialog.editors["gui.theme"].buttons["system"].click()
    assert previews == ["system"]

    dialog.cancel_button.click()

    assert previews == ["system", "light"]


def test_a_saved_theme_is_kept_when_the_dialog_closes(qapp, tmp_path):
    previews = []
    dialog = a_settings_dialog(tmp_path, preview_theme=previews.append)
    dialog.editors["gui.theme"].buttons["dark"].click()
    dialog.save_button.click()
    dialog.apply_result(ConfigParameterResult(key="gui.theme", value="dark", accepted=True))

    dialog.close_button.click()

    assert previews == ["dark"]


def test_a_refused_theme_is_put_back_when_the_dialog_closes(qapp, tmp_path):
    """The window must not stay in a theme the next start will not use."""
    previews = []
    dialog = a_settings_dialog(tmp_path, preview_theme=previews.append)
    dialog.editors["gui.theme"].buttons["dark"].click()
    dialog.save_button.click()
    dialog.apply_result(
        ConfigParameterResult(key="gui.theme", value="dark", accepted=False, reason="No.")
    )

    dialog.close_button.click()

    assert previews == ["dark", "light"]


def test_a_window_size_preset_fills_in_both_fields(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    dialog.presets["Full HD"].click()

    assert dialog.text_of("gui.window_width") == "1920"
    assert dialog.text_of("gui.window_height") == "1080"
    assert dialog.save_button.text() == "Save 2 changes"
    dialog.close()


def test_the_log_level_is_a_row_of_buttons(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)
    buttons = dialog.editors["logging.level"].buttons

    assert list(buttons) == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    buttons["DEBUG"].click()

    assert dialog.text_of("logging.level") == "DEBUG"
    dialog.close()


def test_the_watchdog_is_an_on_off_switch(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)
    switch = dialog.editors["watchdog.enabled"].button

    assert switch.text() == "On"
    switch.click()

    assert dialog.text_of("watchdog.enabled") == "false"
    assert switch.text() == "Off"
    dialog.close()


def test_a_changed_setting_is_marked_and_can_be_reset(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)
    card = dialog.cards["gui.window_width"]

    dialog.set_value("gui.window_width", "1600")

    assert card.property("modified") is True
    assert card.reset_button.isHidden() is False
    assert dialog.nav.item(0).text() != "Appearance"

    card.reset_button.click()

    assert dialog.text_of("gui.window_width") == "1280"
    assert card.property("modified") is False
    assert card.reset_button.isHidden() is True
    assert dialog.nav.item(0).text() == "Appearance"
    dialog.close()


def test_nothing_changed_means_nothing_to_save(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    assert dialog.changes() == {}
    assert dialog.save_button.isEnabled() is False
    dialog.close()


def test_save_sends_only_what_changed(qapp, tmp_path):
    sent = []
    dialog = a_settings_dialog(tmp_path, sent)
    dialog.set_value("gui.window_width", "1600")
    dialog.editors["watchdog.enabled"].button.click()

    assert dialog.save_button.text() == "Save 2 changes"
    dialog.save_button.click()

    assert sent == [("gui.window_width", "1600"), ("watchdog.enabled", "false")]
    assert dialog.showing == "saving"
    assert dialog.cards["gui.window_width"].body.isEnabled() is False
    dialog.close()


def test_a_relative_folder_cannot_be_saved_and_says_why(qapp, tmp_path):
    """A relative path would land wherever pypts happened to be started from."""
    dialog = a_settings_dialog(tmp_path)
    folder = dialog.editors["paths.reports_dir"]

    folder.set_value("reports")

    assert dialog.save_button.isEnabled() is False
    assert folder.error.isHidden() is False

    folder.set_value(str(tmp_path / "elsewhere"))

    assert dialog.save_button.isEnabled() is True
    assert folder.error.isHidden() is True
    dialog.close()


def test_open_is_offered_only_for_a_folder_that_exists(qapp, tmp_path):
    (tmp_path / "reports").mkdir()

    dialog = a_settings_dialog(tmp_path)

    assert dialog.editors["paths.reports_dir"].open_button.isEnabled() is True
    assert dialog.editors["paths.logs_dir"].open_button.isEnabled() is False
    dialog.close()


def test_the_answers_are_shown_once_every_change_is_answered(qapp, tmp_path):
    from pypts.hmi.gui.settings_dialog import NEXT_START_NOTE

    dialog = a_settings_dialog(tmp_path)
    dialog.set_value("gui.window_width", "1600")
    dialog.editors["logging.level"].buttons["DEBUG"].click()
    dialog.save_button.click()

    dialog.apply_result(ConfigParameterResult(key="logging.level", value="DEBUG", accepted=True))
    assert dialog.showing == "saving"

    dialog.apply_result(
        ConfigParameterResult(
            key="gui.window_width", value="1600", accepted=False, reason="The file was discarded."
        )
    )

    assert dialog.showing == "result"
    shown = " ".join(all_text(dialog.result_page))
    assert "Partly saved" in shown
    assert "Log level: DEBUG" in shown
    assert "Window width: The file was discarded." in shown
    assert NEXT_START_NOTE in shown
    dialog.close()


def test_an_answer_nobody_asked_for_is_not_taken(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    taken = dialog.apply_result(ConfigParameterResult(key="gui.theme", value="dark", accepted=True))

    assert taken is False
    assert dialog.showing == "edit"
    dialog.close()


def test_changes_nobody_answered_are_reported_when_the_wait_runs_out(qapp, qtbot, tmp_path):
    """A CORE that never answers must not leave the dialog saying Saving... forever."""
    from pypts.hmi.gui.settings_dialog import NO_ANSWER_REASON

    dialog = a_settings_dialog(tmp_path, answer_timeout_ms=10)
    dialog.set_value("gui.window_width", "1600")
    dialog.save_button.click()

    qtbot.waitUntil(lambda: dialog.showing == "result", timeout=2000)

    shown = " ".join(all_text(dialog.result_page))
    assert "Not saved" in shown
    assert NO_ANSWER_REASON in shown
    dialog.close()


def test_a_discarded_settings_file_offers_no_save(qapp, tmp_path):
    """Writing one value would replace the user's broken file with the defaults."""
    dialog = a_settings_dialog(tmp_path, problem="It declares structure version 1.")

    assert dialog.save_button.isEnabled() is False
    assert dialog.cards["gui.window_width"].body.isEnabled() is False
    assert any("structure version 1" in text for text in all_text(dialog))
    dialog.close()


def test_cancel_sends_nothing(qapp, tmp_path):
    sent = []
    dialog = a_settings_dialog(tmp_path, sent)
    dialog.set_value("gui.window_width", "1600")

    dialog.cancel_button.click()

    assert sent == []


# --------------------------------------------------------------------------
# The dialog inside the GUI
# --------------------------------------------------------------------------


def test_edit_offers_settings(gui_factory):
    instance, _outbox, _inbox = gui_factory()

    assert instance.window.settings_action.text() == "Settings"
    assert instance.window.settings_action.isEnabled() is True


def test_the_dialog_saves_through_core_and_shows_its_answer(gui_factory, monkeypatch):
    """
    Save puts SetConfigParameter on the link, and CORE's answer - arriving
    through the poll timer, which keeps running under exec()'s nested event
    loop - reaches the open dialog.
    """
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, outbox, inbox = gui_factory()
    seen = {}

    def operator_changes_the_width(dialog):
        dialog.set_value("gui.window_width", "1500")
        dialog.save_button.click()
        seen["asked"] = [m for m in drain(outbox) if isinstance(m, SetConfigParameter)]
        inbox.send(ConfigParameterResult(key="gui.window_width", value="1500", accepted=True))
        instance.poll_core()
        seen["showing"] = dialog.showing
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", operator_changes_the_width)
    instance.window.settings_action.trigger()

    assert seen["asked"] == [SetConfigParameter(key="gui.window_width", value="1500")]
    assert seen["showing"] == "result"
    assert instance.settings_dialog is None


def test_a_saved_setting_is_shown_when_the_dialog_reopens(gui_factory, monkeypatch):
    """This process never re-reads config.ini, so it remembers what CORE confirmed."""
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, _outbox, inbox = gui_factory()
    inbox.send(ConfigParameterResult(key="gui.window_width", value="1500", accepted=True))
    instance.poll_core()
    shown = {}

    def look_at_the_width(dialog):
        shown["width"] = dialog.text_of("gui.window_width")
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", look_at_the_width)
    instance.window.settings_action.trigger()

    assert shown["width"] == "1500"


def test_an_answer_with_no_dialog_open_goes_to_the_status_line(gui_factory):
    instance, _outbox, inbox = gui_factory()

    inbox.send(
        ConfigParameterResult(
            key="gui.theme", value="dark", accepted=False, reason="The file was discarded."
        )
    )
    instance.poll_core()

    assert "gui.theme not saved: The file was discarded." in instance.status_label.text()


def test_a_discarded_settings_file_is_explained_in_the_dialog(gui_factory, monkeypatch):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file({"meta.config_version": "1"})
    instance, _outbox, _inbox = gui_factory()
    seen = {}

    def look_at_the_dialog(dialog):
        seen["problem"] = dialog.problem
        seen["can_save"] = dialog.save_button.isEnabled()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", look_at_the_dialog)
    instance.window.settings_action.trigger()

    assert "structure version 1" in seen["problem"]
    assert seen["can_save"] is False


def test_picking_a_theme_repaints_the_window_and_cancel_restores_it(gui_factory, monkeypatch):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, _outbox, _inbox = gui_factory()
    seen = {}

    def pick_dark_then_cancel(dialog):
        dialog.editors["gui.theme"].buttons["dark"].click()
        seen["dark_while_open"] = instance._dark
        dialog.reject()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", pick_dark_then_cancel)
    instance.window.settings_action.trigger()

    assert seen["dark_while_open"] is True
    assert instance._dark is False


def test_the_window_opens_with_the_configured_size_and_theme(gui_factory):
    a_config_file({"gui.theme": "dark", "gui.window_width": "1100", "gui.window_height": "750"})

    instance, _outbox, _inbox = gui_factory()

    assert (instance.window.width(), instance.window.height()) == (1100, 750)
    assert instance._dark is True


def test_light_is_the_shipped_theme_and_ignores_a_dark_os(gui_factory, monkeypatch):
    from pypts.hmi.gui import gui as gui_module

    installed = []
    monkeypatch.setattr(gui_module, "detect_system_dark_mode", lambda app=None: True)
    monkeypatch.setattr(
        gui_module,
        "install_system_theme_sync",
        lambda app, callback: installed.append(callback) or (lambda: None),
    )
    a_config_file()

    instance, _outbox, _inbox = gui_factory()

    assert instance._dark is False
    assert installed == []


def test_the_system_theme_follows_the_operating_system(gui_factory, monkeypatch):
    from pypts.hmi.gui import gui as gui_module

    installed = []
    monkeypatch.setattr(gui_module, "detect_system_dark_mode", lambda app=None: True)
    monkeypatch.setattr(
        gui_module,
        "install_system_theme_sync",
        lambda app, callback: installed.append(callback) or (lambda: None),
    )
    a_config_file({"gui.theme": "system"})

    instance, _outbox, _inbox = gui_factory()

    assert instance._dark is True
    assert len(installed) == 1


def test_without_a_configuration_the_window_uses_the_template_defaults(gui_factory):
    """A GUI built by a test, or started by hand, still opens - light, 1280 x 720."""
    instance, _outbox, _inbox = gui_factory()

    assert (instance.window.width(), instance.window.height()) == (1280, 720)
    assert instance._dark is False


# --------------------------------------------------------------------------
# One theme setting for pypts and the Recipe Creator
# --------------------------------------------------------------------------


def test_the_theme_is_light_without_a_configuration():
    from pypts.hmi.gui.gui_theme import configured_theme

    assert configured_theme() == "light"


def test_the_theme_is_read_from_the_file_pypts_uses():
    from pypts.hmi.gui.gui_theme import configured_theme

    a_config_file({"gui.theme": "dark"})

    assert configured_theme() == "dark"


def test_the_recipe_creator_opens_in_the_configured_theme(qapp):
    from pypts.helper_applications.recipe_creator.recipe_creator_new import (
        RecipeCreatorNewWindow,
    )

    a_config_file({"gui.theme": "dark"})

    window = RecipeCreatorNewWindow()

    assert window._dark is True
    assert window._act_dark.isChecked() is True
    window.close()


def test_the_recipe_creator_opens_light_by_default(qapp):
    from pypts.helper_applications.recipe_creator.recipe_creator_new import (
        RecipeCreatorNewWindow,
    )

    window = RecipeCreatorNewWindow()

    assert window._dark is False
    window.close()
