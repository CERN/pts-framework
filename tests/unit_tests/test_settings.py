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
        "paths.reports_dir": str(tmp_path / "reports"),
        "logging.level": "INFO",
        "report.type": "html",
        "report.theme": "default",
        "gui.theme": "light",
        "gui.window_mode": "windowed",
        "gui.window_width": "1280",
        "gui.window_height": "720",
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
    assert titles == ["Folders", "Appearance", "Logging", "Report"]
    assert dialog.nav.currentItem().text() == "Folders"

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
    assert ("Paths", ("paths.base_dir", "paths.reports_dir")) in pages


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

    # A clean save closes the dialog by itself - no result page to dismiss.
    dialog.apply_result(ConfigParameterResult(key="gui.theme", value="dark", accepted=True))

    assert dialog.saved is True
    assert dialog.result() == dialog.DialogCode.Accepted.value
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

    assert list(buttons) == ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    buttons["DEBUG"].click()

    assert dialog.text_of("logging.level") == "DEBUG"
    dialog.close()


def test_a_yes_no_setting_is_an_on_off_switch(qapp):
    """No yes/no key is in the schema today; the control stays for the next one."""
    from pypts.hmi.gui.settings_dialog import OnOffSwitch

    switch = OnOffSwitch("true")

    assert switch.button.text() == "On"
    switch.button.click()

    assert switch.value() == "false"
    assert switch.button.text() == "Off"


def test_the_watchdog_is_not_a_setting(qapp, tmp_path):
    """Ending the run when a module stops responding is fixed behaviour."""
    dialog = a_settings_dialog(tmp_path, clear_recent_recipes=lambda: None, offer_restore=True)

    assert not [key for key in dialog.editors if key.startswith("watchdog.")]
    assert "watchdog" not in " ".join(all_text(dialog)).lower()
    dialog.close()


def test_advanced_is_offered_only_with_its_actions(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path, offer_restore=True, offer_storage=True)

    titles = [dialog.nav.item(row).text() for row in range(dialog.nav.count())]
    assert titles[-2:] == ["Advanced", "Storage"]
    dialog.close()


def test_a_changed_setting_is_marked_and_can_be_reset(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)
    card = dialog.cards["gui.window_width"]

    dialog.set_value("gui.window_width", "1600")

    assert card.property("modified") is True
    assert card.reset_button.isHidden() is False
    assert dialog.nav.item(1).text() != "Appearance"

    card.reset_button.click()

    assert dialog.text_of("gui.window_width") == "1280"
    assert card.property("modified") is False
    assert card.reset_button.isHidden() is True
    assert dialog.nav.item(1).text() == "Appearance"
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
    dialog.set_value("logging.level", "DEBUG")

    assert dialog.save_button.text() == "Save 2 changes"
    dialog.save_button.click()

    assert sent == [("gui.window_width", "1600"), ("logging.level", "DEBUG")]
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
    dialog = a_settings_dialog(tmp_path)  # the reports folder is not made yet

    assert dialog.editors["paths.base_dir"].open_button.isEnabled() is True
    assert dialog.editors["paths.reports_dir"].open_button.isEnabled() is False
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
# Trying a window on screen
# --------------------------------------------------------------------------


def a_window_dialog(tmp_path, keep=True):
    """
    A dialog whose window previews are recorded, and whose "keep it?" question
    is answered with `keep` - the countdown dialog itself is tested on its own.
    """
    previews = []
    asked = []
    sent = []

    def confirm(description):
        asked.append(description)
        return keep

    dialog = a_settings_dialog(
        tmp_path,
        sent,
        preview_window=lambda mode, width, height: previews.append((mode, width, height)),
        confirm_window=confirm,
    )
    return dialog, previews, asked, sent


def test_the_window_card_offers_three_modes(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)
    buttons = dialog.editors["gui.window_mode"].buttons

    assert list(buttons) == ["windowed", "fullscreen"]
    assert [button.text() for button in buttons.values()] == ["Windowed", "Full screen"]
    assert dialog.cards["gui.window_mode"] is dialog.cards["gui.window_width"]
    dialog.close()


def test_a_kept_preset_resizes_the_window_and_saves_it(qapp, tmp_path):
    """Keep is a save: nothing is left for the Save button to do."""
    dialog, previews, asked, sent = a_window_dialog(tmp_path, keep=True)

    dialog.presets["Full HD"].click()

    assert previews == [("windowed", 1920, 1080)]
    assert len(asked) == 1
    assert "1920" in asked[0]
    assert dialog.window_on_screen == ("windowed", 1920, 1080)
    assert sent == [("gui.window_width", "1920"), ("gui.window_height", "1080")]
    assert dialog.changes() == {}
    assert dialog.save_button.isEnabled() is False
    dialog.close()


def test_a_size_not_kept_goes_back_on_screen_and_in_the_fields(qapp, tmp_path):
    """No answer within the countdown counts as not kept."""
    dialog, previews, _asked, sent = a_window_dialog(tmp_path, keep=False)

    dialog.presets["Full HD"].click()

    assert previews == [("windowed", 1920, 1080), ("windowed", 1280, 720)]
    assert dialog.text_of("gui.window_width") == "1280"
    assert dialog.text_of("gui.window_height") == "720"
    assert dialog.changes() == {}
    assert sent == []
    dialog.close()


def test_a_typed_size_waits_for_apply(qapp, tmp_path):
    """The window must not jump on every keystroke."""
    dialog, previews, _asked, sent = a_window_dialog(tmp_path)

    dialog.set_value("gui.window_width", "1500")

    assert previews == []
    assert sent == []
    assert dialog.apply_window_button.isEnabled() is True

    dialog.apply_window_button.click()

    assert previews == [("windowed", 1500, 720)]
    assert sent == [("gui.window_width", "1500")]
    assert dialog.apply_window_button.isEnabled() is False
    dialog.close()


def test_picking_full_screen_tries_it_at_once(qapp, tmp_path):
    dialog, previews, asked, sent = a_window_dialog(tmp_path)

    dialog.editors["gui.window_mode"].buttons["fullscreen"].click()

    assert previews == [("fullscreen", 1280, 720)]
    assert asked == ["Full screen"]
    assert sent == [("gui.window_mode", "fullscreen")]
    dialog.close()


def test_a_kept_window_stays_when_the_dialog_is_cancelled(qapp, tmp_path):
    """Keep already saved it; Cancel only drops what was not saved."""
    dialog, previews, _asked, _sent = a_window_dialog(tmp_path)
    dialog.presets["HD+"].click()

    dialog.cancel_button.click()

    assert previews == [("windowed", 1600, 900)]


def test_the_answers_to_a_kept_window_go_to_the_gui_not_the_dialog(qapp, tmp_path):
    """The dialog is not waiting on Keep's answers; the GUI's status line shows them."""
    dialog, _previews, _asked, _sent = a_window_dialog(tmp_path)
    dialog.presets["HD+"].click()

    taken = dialog.apply_result(
        ConfigParameterResult(key="gui.window_width", value="1600", accepted=True)
    )

    assert taken is False
    assert dialog.showing == "edit"
    dialog.close()


def test_reset_puts_a_typed_window_size_back(qapp, tmp_path):
    dialog, previews, _asked, sent = a_window_dialog(tmp_path)
    dialog.set_value("gui.window_width", "1500")

    dialog.cards["gui.window_width"].reset_button.click()

    assert dialog.text_of("gui.window_width") == "1280"
    assert dialog.changes() == {}
    assert previews == []
    assert sent == []
    dialog.close()


def test_the_confirmation_reverts_by_itself_when_the_countdown_runs_out(qapp, qtbot):
    """A window too big or too small may leave nothing to click - so waiting reverts."""
    from pypts.hmi.gui.settings_dialog import WindowConfirmDialog

    dialog = WindowConfirmDialog("1920 × 1080", seconds=1)  # noqa: RUF001 - as shown on screen
    dialog.open()

    qtbot.waitUntil(lambda: dialog.timed_out, timeout=3000)

    assert dialog.isVisible() is False
    assert dialog.result() != dialog.DialogCode.Accepted.value


def test_the_confirmation_counts_down_and_keep_accepts(qapp):
    from pypts.hmi.gui.settings_dialog import WindowConfirmDialog

    dialog = WindowConfirmDialog("Full screen", seconds=15)

    assert "15 seconds" in dialog.countdown_label.text()
    assert dialog.revert_button.isDefault() is True

    dialog.open()
    dialog.keep_button.click()

    assert dialog.result() == dialog.DialogCode.Accepted.value
    assert dialog.timed_out is False


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

    The change is the log level, not a window size: the window keys are saved
    by Keep in the "keep these window settings?" question, never by Save
    (SettingsDialog._changes_to_save), and have tests of their own below.
    """
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, outbox, inbox = gui_factory()
    seen = {}

    def operator_changes_the_log_level(dialog):
        dialog.set_value("logging.level", "INFO")
        dialog.save_button.click()
        seen["asked"] = [m for m in drain(outbox) if isinstance(m, SetConfigParameter)]
        inbox.send(ConfigParameterResult(key="logging.level", value="INFO", accepted=True))
        instance.poll_core()
        seen["saved"] = dialog.saved
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", operator_changes_the_log_level)
    instance.window.settings_action.trigger()

    assert seen["asked"] == [SetConfigParameter(key="logging.level", value="INFO")]
    # All accepted: the dialog closed itself, and the status line says so.
    assert seen["saved"] is True
    assert "Settings saved" in instance.status_label.text()
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

    a_config_file({"meta.config_version": "2.0.0"})
    instance, _outbox, _inbox = gui_factory()
    seen = {}

    def look_at_the_dialog(dialog):
        seen["problem"] = dialog.problem
        seen["can_save"] = dialog.save_button.isEnabled()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", look_at_the_dialog)
    instance.window.settings_action.trigger()

    assert "structure version 2.0.0" in seen["problem"]
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


def test_view_offers_full_screen_on_f11(gui_factory):
    instance, _outbox, _inbox = gui_factory()
    action = instance.window.full_screen_action

    assert action.text() == "Full Screen"
    assert action.isCheckable() is True
    assert action.shortcut().toString() == "F11"


def test_full_screen_toggles_for_the_session(gui_factory):
    """Full screen is maximised, not a true full screen - GUI._use_window() says why."""
    instance, _outbox, _inbox = gui_factory()
    instance.show()

    instance.window.full_screen_action.trigger()
    assert instance.window.isMaximized() is True
    assert instance.window.isFullScreen() is False

    instance.window.full_screen_action.trigger()
    assert instance.window.isMaximized() is False


def test_the_window_opens_in_the_configured_mode(gui_factory):
    a_config_file({"gui.window_mode": "fullscreen"})
    instance, _outbox, _inbox = gui_factory()

    instance.show()

    assert instance.window.isMaximized() is True
    assert instance.window.full_screen_action.isChecked() is True


def test_a_window_kept_in_settings_is_saved_and_stays_after_cancel(gui_factory, monkeypatch):
    """
    Keep in the "keep these window settings?" question is a save: the size goes
    to CORE at once and counts as what the dialog opened with, so leaving the
    dialog by Cancel does not put the old window back.
    """
    from pypts.hmi.gui import settings_dialog
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, outbox, _inbox = gui_factory()
    instance.show()
    monkeypatch.setattr(settings_dialog, "confirm_window_settings", lambda text, parent: True)
    seen = {}

    def try_hd_plus_keep_it_then_cancel(dialog):
        dialog.presets["HD+"].click()
        seen["size_while_open"] = (instance.window.width(), instance.window.height())
        seen["asked"] = [m for m in drain(outbox) if isinstance(m, SetConfigParameter)]
        dialog.reject()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", try_hd_plus_keep_it_then_cancel)
    instance.window.settings_action.trigger()

    assert seen["size_while_open"] == (1600, 900)
    assert seen["asked"] == [
        SetConfigParameter(key="gui.window_width", value="1600"),
        SetConfigParameter(key="gui.window_height", value="900"),
    ]
    assert (instance.window.width(), instance.window.height()) == (1600, 900)


def test_a_window_not_kept_in_settings_is_put_back_at_once(gui_factory, monkeypatch):
    """Not keeping a tried window restores the previous one there and then, and saves nothing."""
    from pypts.hmi.gui import settings_dialog
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, outbox, _inbox = gui_factory()
    instance.show()
    monkeypatch.setattr(settings_dialog, "confirm_window_settings", lambda text, parent: False)
    seen = {}

    def try_hd_plus_and_refuse_it(dialog):
        dialog.presets["HD+"].click()
        seen["size_after_refusing"] = (instance.window.width(), instance.window.height())
        seen["asked"] = [m for m in drain(outbox) if isinstance(m, SetConfigParameter)]
        dialog.reject()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", try_hd_plus_and_refuse_it)
    instance.window.settings_action.trigger()

    assert seen["size_after_refusing"] == (1280, 720)
    assert seen["asked"] == []
    assert (instance.window.width(), instance.window.height()) == (1280, 720)


def test_without_a_configuration_the_window_uses_the_template_defaults(gui_factory):
    """A GUI built by a test, or started by hand, still opens - light, 1280 x 720."""
    instance, _outbox, _inbox = gui_factory()

    assert (instance.window.width(), instance.window.height()) == (1280, 720)
    assert instance._dark is False


# --------------------------------------------------------------------------
# Storage, Clear recent recipes, and Restore default settings
# --------------------------------------------------------------------------


def page_named(dialog, title):
    """The page widget whose entry in the list reads `title`."""
    for row in range(dialog.nav.count()):
        if dialog.nav.item(row).text() == title:
            return dialog.pages.widget(row)
    raise AssertionError(f"no page named {title!r}")


def test_storage_is_the_last_page_and_shows_the_base_folder(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path, offer_storage=True)
    last = dialog.nav.count() - 1

    assert dialog.nav.item(last).text() == "Storage"
    assert str(tmp_path) in all_text(dialog.pages.widget(last))
    dialog.close()


def test_storage_is_not_offered_unless_asked_for(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    assert dialog.open_base_folder_button is None
    assert "Storage" not in [dialog.nav.item(row).text() for row in range(dialog.nav.count())]
    dialog.close()


def test_storage_opens_the_base_folder_in_the_file_manager(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    dialog = a_settings_dialog(tmp_path, offer_storage=True)

    dialog.open_base_folder_button.click()

    assert [Path(url.toLocalFile()) for url in opened] == [tmp_path]
    dialog.close()


def test_storage_cannot_open_a_base_folder_that_is_not_there(qapp, tmp_path):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    values = settings_in_force(tmp_path)
    values["paths.base_dir"] = str(tmp_path / "gone")
    dialog = SettingsDialog(values, lambda key, value: None, offer_storage=True)

    assert dialog.open_base_folder_button.isEnabled() is False
    dialog.close()


def test_storage_deletes_nothing(qapp, tmp_path):
    """Reports and run logs are test records: the operator removes them, not pypts."""
    from PySide6.QtWidgets import QPushButton

    dialog = a_settings_dialog(tmp_path, offer_storage=True)
    buttons = page_named(dialog, "Storage").findChildren(QPushButton)

    assert [button.text() for button in buttons if not button.isHidden()] == ["Open"]
    dialog.close()


def test_settings_can_open_on_a_named_page(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path, offer_storage=True, open_page="Storage")

    assert dialog.nav.currentItem().text() == "Storage"
    assert dialog.pages.currentWidget() is page_named(dialog, "Storage")
    dialog.close()


def test_clear_recent_recipes_is_offered_on_the_advanced_page(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path, clear_recent_recipes=lambda: None)

    assert dialog.clear_recents_button is not None
    advanced = page_named(dialog, "Advanced")
    assert dialog.clear_recents_button in advanced.findChildren(type(dialog.clear_recents_button))
    dialog.close()


def test_clear_recent_recipes_is_not_offered_unless_asked_for(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    assert dialog.clear_recents_button is None
    dialog.close()


def test_clear_recent_recipes_clears_at_once_without_asking(qapp, tmp_path):
    cleared = []
    dialog = a_settings_dialog(tmp_path, clear_recent_recipes=lambda: cleared.append(True))

    dialog.clear_recents_button.click()

    assert cleared == [True]
    assert dialog.recents_cleared is True
    assert dialog.clear_recents_button.isEnabled() is False
    dialog.close()


def test_clear_recent_recipes_is_allowed_during_a_run(qapp, tmp_path):
    dialog = a_settings_dialog(
        tmp_path,
        clear_recent_recipes=lambda: None,
        blocked_reason="Not while a recipe is running - stop the run first.",
    )

    assert dialog.clear_recents_button.isEnabled() is True
    dialog.close()


def test_restore_default_settings_is_offered_on_the_advanced_page(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path, offer_restore=True, confirm_restore=lambda: False)

    assert dialog.restore_button is not None
    advanced = dialog.pages.widget(dialog.nav.count() - 1)
    assert dialog.restore_button in advanced.findChildren(type(dialog.restore_button))
    dialog.close()


def test_restore_is_not_offered_unless_asked_for(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path)

    assert dialog.restore_button is None
    dialog.close()


def test_restore_asks_first_and_cancel_does_nothing(qapp, tmp_path):
    asked = []

    def say_cancel():
        asked.append(True)
        return False

    dialog = a_settings_dialog(tmp_path, offer_restore=True, confirm_restore=say_cancel)

    dialog.restore_button.click()

    assert asked == [True]
    assert dialog.restore_requested is False
    dialog.close()


def test_a_confirmed_restore_closes_settings_asking_for_it(qapp, tmp_path):
    dialog = a_settings_dialog(tmp_path, offer_restore=True, confirm_restore=lambda: True)

    dialog.restore_button.click()

    assert dialog.restore_requested is True
    assert dialog.result() == dialog.DialogCode.Accepted.value


def test_restore_is_refused_during_a_run_and_says_why(qapp, tmp_path):
    dialog = a_settings_dialog(
        tmp_path,
        offer_restore=True,
        confirm_restore=lambda: True,
        blocked_reason="Not while a recipe is running - stop the run first.",
    )

    assert dialog.restore_button.isEnabled() is False
    assert any("running" in text for text in all_text(dialog))
    dialog.close()


def test_edit_offers_only_edit_recipe_and_settings(gui_factory):
    from PySide6.QtWidgets import QMenu

    instance, _outbox, _inbox = gui_factory()
    # Found by title among the menu bar's children: QAction.menu() hands back a
    # wrapper PySide6 may already have let go of.
    menus = instance.window.menuBar().findChildren(QMenu)
    edit_menu = next(menu for menu in menus if menu.title() == "Edit")

    assert [action.text() for action in edit_menu.actions() if action.text()] == [
        "Edit Recipe",
        "Settings",
    ]


def test_view_appearance_opens_settings_on_the_appearance_page(gui_factory, monkeypatch):
    from pypts.hmi.gui.settings_dialog import SettingsDialog

    a_config_file()
    instance, _outbox, _inbox = gui_factory()
    seen = {}

    def look_at_the_page(dialog):
        seen["page"] = dialog.nav.currentItem().text()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", look_at_the_page)
    instance.window.appearance_action.trigger()

    assert seen["page"] == "Appearance"


def test_restore_is_refused_during_a_run_and_clearing_the_recents_is_not(
    gui_factory, monkeypatch
):
    from pypts.hmi.gui.settings_dialog import SettingsDialog
    from pypts.messages.run_events import RunStarted

    a_config_file()
    instance, _outbox, inbox = gui_factory()
    inbox.send(RunStarted(recipe_name="demo", recipe_description="d"))
    instance.poll_core()
    seen = {}

    def look_at_the_advanced_page(dialog):
        seen["can_clear"] = dialog.clear_recents_button.isEnabled()
        seen["can_restore"] = dialog.restore_button.isEnabled()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", look_at_the_advanced_page)
    instance.window.settings_action.trigger()

    assert seen["can_clear"] is True
    assert seen["can_restore"] is False


def test_restoring_the_defaults_deletes_the_config_and_restarts_pypts(gui_factory, monkeypatch):
    """Every process read config.ini at startup; a fresh start recreates it from the template."""
    from pypts.hmi.gui import settings_dialog
    from pypts.hmi.gui.settings_dialog import SettingsDialog
    from pypts.messages.core_hmi_communication import ShutdownRequested
    from pypts.utilities.common import RESTART_EXIT_CODE

    config_file = a_config_file()
    instance, outbox, _inbox = gui_factory()
    monkeypatch.setattr(settings_dialog, "confirm_restore_defaults", lambda parent: True)

    def press_restore(dialog):
        dialog.restore_button.click()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", press_restore)
    instance.window.settings_action.trigger()

    assert not config_file.exists()
    assert instance.exit_code == RESTART_EXIT_CODE
    assert any(isinstance(message, ShutdownRequested) for message in drain(outbox))


def test_clearing_the_recents_in_settings_empties_the_list_without_a_restart(
    gui_factory, monkeypatch, tmp_path
):
    from pypts.hmi.gui.settings_dialog import SettingsDialog
    from pypts.messages.core_hmi_communication import ShutdownRequested
    from pypts.utilities.recent_recipes import RecentRecipes

    config_file = a_config_file()
    instance, outbox, _inbox = gui_factory()
    recipe = tmp_path / "bench.yml"
    recipe.write_text("name: bench\n", encoding="utf-8")
    instance.recent_recipes.remember(str(recipe), "Bench")
    assert instance.recent_recipes.entries() != []

    def clear_the_recents(dialog):
        dialog.clear_recents_button.click()
        dialog.accept()
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", clear_the_recents)
    instance.window.settings_action.trigger()

    assert instance.recent_recipes.entries() == []
    assert RecentRecipes().entries() == []
    assert config_file.exists()
    assert instance.exit_code == 0
    assert not any(isinstance(message, ShutdownRequested) for message in drain(outbox))


def test_the_version_is_shown_faintly_in_the_status_bar(gui_factory):
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    from pypts._version import __version__

    instance, _outbox, _inbox = gui_factory()
    label = instance.version_label

    assert label.text() == f"pypts {__version__}"
    assert isinstance(label.graphicsEffect(), QGraphicsOpacityEffect)
    assert label.graphicsEffect().opacity() == pytest.approx(0.5)


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
