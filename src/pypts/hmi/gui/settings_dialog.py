# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Settings dialog: Edit -> Settings.

A list of pages on the left - Appearance, Folders, Logging, Report, Advanced -
and the page's settings on the right, one card each. Controls are chosen for
the value, not for the file: the theme is three picture cards, a short list of
choices a row of buttons, a yes/no setting an On/Off switch, the window size two
number fields with presets, a folder a path with Browse and Open. A card whose
value differs from the one the dialog opened with is outlined, gets a Reset, and
marks its page in the list. Save sends the changed values; the same window then
says what was saved and what was not.

**It does not write the file.** CORE is the single runtime writer of config.ini
(config_handler.md), so Save hands each changed value to a `send` callable - the
GUI passes `set_config_parameter()`, which puts a SetConfigParameter on the link
- and waits for CORE's ConfigParameterResult for each one, which the GUI passes
to `apply_result()`. The answers get here through the GUI's poll timer, which
keeps firing inside `exec()`'s nested event loop. If they do not all arrive
within ANSWER_TIMEOUT_MS the dialog stops waiting and says so.

**The theme is previewed, everything else waits for the next start.** Picking a
theme card calls `preview_theme`, so the operator sees it at once; every way out
of the dialog goes through `done()`, which puts the theme in force back unless
CORE confirmed saving the new one. No other setting can be applied to a running
pypts - every process read its configuration once, at startup.

**No setting is left out.** PAGES places the keys it knows; any other key of the
schema (outside `READ_ONLY_SECTIONS`) gets a page named after its section and a
control chosen from its type, so a key added to `configuration_schema.py` shows
up with no change here.

Pure presentation, like `remove_cache_dialog.py`: handed the values in force, the
`send` callable and the preview callable, so a test drives the whole dialog with
no CORE and no file. Styling lives in `styles.py` (object names `settings*` and
`themeSwatch*`).
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pypts.config_handler.configuration_schema import (
    READ_ONLY_SECTIONS,
    SCHEMA,
    TRUE_VALUES,
    Field,
)
from pypts.hmi.gui.remove_cache_dialog import count_of
from pypts.messages.core_hmi_communication import ConfigParameterResult

#: How long the dialog waits for CORE's answers before it gives up on them.
#: CORE answers within one turn of its event loop; five seconds is the heartbeat
#: timeout, the point at which the rest of the framework presumes a module lost.
ANSWER_TIMEOUT_MS = 5000

#: Upper bound of every whole-number field. Only there so a slipped finger
#: cannot type a window no screen could show.
_SPIN_MAXIMUM = 100_000

#: Height of every input, so a crowded card cannot squeeze one to a sliver.
_INPUT_HEIGHT = 30

THEME_KEY = "gui.theme"
WIDTH_KEY = "gui.window_width"
HEIGHT_KEY = "gui.window_height"

#: Page title -> the keys on it, in order. A key the schema does not have is
#: skipped; a key the schema has and this does not name gets a page of its own.
PAGES = (
    ("Appearance", (THEME_KEY, WIDTH_KEY, HEIGHT_KEY)),
    ("Folders", ("paths.logs_dir", "paths.reports_dir", "paths.base_dir")),
    ("Logging", ("logging.level",)),
    ("Report", ("report.type", "report.theme")),
    ("Advanced", ("watchdog.enabled",)),
)

#: Page title for a section PAGES does not place.
SECTION_TITLES = {
    "paths": "Paths",
    "logging": "Logging",
    "report": "Report",
    "gui": "Window",
    "watchdog": "Watchdog",
}

#: Card title for each key. A key missing here shows its own name.
LABELS = {
    "paths.base_dir": "Base folder",
    "paths.logs_dir": "Run logs folder",
    "paths.reports_dir": "Reports folder",
    "logging.level": "Log level",
    "report.type": "Report type",
    "report.theme": "Report theme",
    "gui.theme": "Theme",
    "gui.window_width": "Window width",
    "gui.window_height": "Window height",
    "watchdog.enabled": "End the run when a module stops responding",
}

#: The line under a card's title, where a key needs explaining.
HINTS = {
    "paths.base_dir": "The folder pypts keeps its own data in.",
    "paths.logs_dir": "Every run writes its log here.",
    "paths.reports_dir": "Every run gets a report folder here.",
    "logging.level": "How much goes into the run log. DEBUG adds the full message trace.",
    "report.type": "Not used yet.",
    "report.theme": "Not used yet.",
    "gui.theme": "Used by pypts and the Recipe Creator. Previewed as you pick it.",
    "watchdog.enabled": "Turn off only while debugging the engine.",
}

#: Name and one line for each theme card.
THEME_CARDS = {
    "light": ("Light", "Bright and clear."),
    "dark": ("Dark", "Easier on the eyes in a dim lab."),
    "system": ("System", "Follows the operating system."),
}

#: Window size presets: name, width, height.
WINDOW_PRESETS = (
    ("HD", 1280, 720),
    ("HD+", 1600, 900),
    ("Full HD", 1920, 1080),
)

#: Appended to a page's name in the list while something on it is changed.
MODIFIED_MARK = "  •"

NEXT_START_NOTE = "Changes take effect the next time pypts starts."
FOOTER_NOTE = f"{NEXT_START_NOTE} The theme is previewed straight away."

#: Said for every change still unanswered when ANSWER_TIMEOUT_MS runs out.
NO_ANSWER_REASON = "The engine did not answer, so this change may not have been saved."


def setting_text(value: Any) -> str:
    """
    A configuration value as it is spelled in config.ini.

    The Config Handler hands out typed values - `Path`, `int`, `bool` - and the
    dialog edits and sends text. `True` becomes "true", like the handler itself
    writes it, so a value nobody touched never reads as changed.
    """
    if isinstance(value, bool):
        if value:
            return "true"
        return "false"
    return str(value)


def editable_keys() -> list[str]:
    """Every dotted key the dialog offers, in schema order."""
    keys = []
    for section, fields in SCHEMA.items():
        if section in READ_ONLY_SECTIONS:
            continue
        for key in fields:
            keys.append(f"{section}.{key}")
    return keys


def pages_for_schema() -> list[tuple[str, tuple[str, ...]]]:
    """
    The pages to show: PAGES, holding only keys the schema has, followed by one
    page per section for any editable key PAGES does not place.
    """
    known = editable_keys()
    placed: set[str] = set()
    pages = []
    for title, keys in PAGES:
        present = tuple(key for key in keys if key in known)
        if present:
            pages.append((title, present))
            placed.update(present)

    leftovers: dict[str, list[str]] = {}
    for key in known:
        if key not in placed:
            section = key.rpartition(".")[0]
            leftovers.setdefault(section, []).append(key)
    for section, keys in leftovers.items():
        pages.append((SECTION_TITLES.get(section, section), tuple(keys)))
    return pages


def label_for(key: str) -> str:
    return LABELS.get(key, key)


def field_for(key: str) -> Field:
    section, _, name = key.rpartition(".")
    return SCHEMA[section][name]


# --- The controls ---------------------------------------------------------------


class SettingEditor(QWidget):
    """
    One setting's control. Every kind reads and writes the value as config.ini
    spells it, and emits `changed` when the operator changes it.
    """

    changed = Signal()

    def value(self) -> str:
        raise NotImplementedError

    def set_value(self, text: str) -> None:
        raise NotImplementedError


class _ExclusiveButtons(SettingEditor):
    """Checkable buttons of which exactly one is on - the base of both choice controls."""

    def __init__(self) -> None:
        super().__init__()
        #: allowed value -> its button, in the schema's order.
        self.buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

    def _add(self, choice: str, button: QPushButton) -> QPushButton:
        button.setCheckable(True)
        button.setAutoDefault(False)
        self._group.addButton(button)
        self.buttons[choice] = button
        return button

    def _finish(self, text: str) -> None:
        # Set before connecting: the value the dialog opens with is not a change.
        self.set_value(text)
        self._group.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, _button: QPushButton, checked: bool) -> None:
        # One click toggles two buttons - one off, one on. Only the second counts.
        if checked:
            self.changed.emit()

    def value(self) -> str:
        for choice, button in self.buttons.items():
            if button.isChecked():
                return choice
        return ""

    def set_value(self, text: str) -> None:
        button = self.buttons.get(text)
        if button is not None:
            button.setChecked(True)


class ChoiceButtons(_ExclusiveButtons):
    """A row of buttons, one per allowed value."""

    def __init__(self, choices: Sequence[str], text: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for choice in choices:
            button = QPushButton(choice)
            button.setObjectName("settingsSegment")
            button.setMinimumHeight(_INPUT_HEIGHT)
            row.addWidget(self._add(choice, button))
        row.addStretch()
        self._finish(text)


class ThemeCards(_ExclusiveButtons):
    """The theme as picture cards: a thumbnail of the window, a name and a line."""

    def __init__(self, choices: Sequence[str], text: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for choice in choices:
            title, description = THEME_CARDS.get(choice, (choice.capitalize(), ""))
            row.addWidget(self._add(choice, _theme_card(choice, title, description)))
        row.addStretch()
        self._finish(text)


def _theme_card(choice: str, title: str, description: str) -> QPushButton:
    card = QPushButton()
    card.setObjectName("settingsThemeCard")
    card.setFixedSize(172, 138)
    card.setToolTip(f"{title}: {description}")

    column = QVBoxLayout(card)
    column.setContentsMargins(10, 10, 10, 8)
    column.setSpacing(4)
    column.addWidget(_theme_swatch(choice))

    name = QLabel(title)
    name.setObjectName("settingsThemeName")
    column.addWidget(name)
    hint = QLabel(description)
    hint.setObjectName("settingsThemeHint")
    hint.setWordWrap(True)
    column.addWidget(hint)

    # The button takes the click wherever it lands, including on its pictures.
    for child in card.findChildren(QWidget):
        child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return card


def _theme_swatch(choice: str) -> QWidget:
    """A thumbnail of the window in one theme: a toolbar strip over a page.
    System shows light and dark side by side."""
    swatch = QWidget()
    swatch.setFixedHeight(56)
    row = QHBoxLayout(swatch)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)

    if choice == "system":
        parts = ("Light", "Dark")
    elif choice == "dark":
        parts = ("Dark",)
    else:
        parts = ("Light",)

    for part in parts:
        page = QFrame()
        page.setObjectName(f"themeSwatch{part}")
        inner = QVBoxLayout(page)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        bar = QFrame()
        bar.setObjectName(f"themeSwatch{part}Bar")
        bar.setFixedHeight(12)
        inner.addWidget(bar)
        inner.addStretch()
        row.addWidget(page)
    return swatch


class OnOffSwitch(SettingEditor):
    """A yes/no setting as one button that reads On or Off."""

    def __init__(self, text: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.setObjectName("settingsSwitch")
        self.button.setCheckable(True)
        self.button.setAutoDefault(False)
        self.button.setFixedSize(76, _INPUT_HEIGHT)
        row.addWidget(self.button)
        row.addStretch()
        self.set_value(text)
        self.button.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._show(checked)
        self.changed.emit()

    def _show(self, checked: bool) -> None:
        if checked:
            self.button.setText("On")
        else:
            self.button.setText("Off")

    def value(self) -> str:
        if self.button.isChecked():
            return "true"
        return "false"

    def set_value(self, text: str) -> None:
        checked = text.strip().lower() in TRUE_VALUES
        self.button.setChecked(checked)
        self._show(checked)


class NumberField(SettingEditor):
    """A whole number, typed. No arrows: nobody sets a window one pixel at a time."""

    def __init__(self, text: str, fallback: str) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.spin = QSpinBox()
        self.spin.setRange(0, _SPIN_MAXIMUM)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin.setFixedSize(110, _INPUT_HEIGHT)
        try:
            self.spin.setValue(int(text))
        except ValueError:
            self.spin.setValue(int(fallback))
        row.addWidget(self.spin)
        self.spin.valueChanged.connect(self._on_value_changed)

    def _on_value_changed(self, _value: int) -> None:
        self.changed.emit()

    def value(self) -> str:
        return str(self.spin.value())

    def set_value(self, text: str) -> None:
        self.spin.setValue(int(text))


class TextField(SettingEditor):
    """Free text."""

    def __init__(self, text: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.line = QLineEdit(text)
        self.line.setMinimumHeight(_INPUT_HEIGHT)
        row.addWidget(self.line)
        self.line.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, _text: str) -> None:
        self.changed.emit()

    def value(self) -> str:
        return self.line.text().strip()

    def set_value(self, text: str) -> None:
        self.line.setText(text)


class FolderField(SettingEditor):
    """
    A folder: the path, Browse to pick one, Open to look inside it.

    The path must be absolute - a relative one would be resolved against
    whatever directory pypts happened to be started from, a different folder on
    every bench. The Config Handler itself only insists on non-empty.
    """

    def __init__(self, text: str, title: str) -> None:
        super().__init__()
        self._title = title
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.line = QLineEdit(text)
        self.line.setMinimumHeight(_INPUT_HEIGHT)
        row.addWidget(self.line, stretch=1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setObjectName("settingsBrowse")
        self.browse_button.setAutoDefault(False)
        self.browse_button.setMinimumHeight(_INPUT_HEIGHT)
        row.addWidget(self.browse_button)
        self.open_button = QPushButton("Open")
        self.open_button.setObjectName("settingsBrowse")
        self.open_button.setAutoDefault(False)
        self.open_button.setMinimumHeight(_INPUT_HEIGHT)
        self.open_button.setToolTip("Show this folder in the file manager.")
        row.addWidget(self.open_button)
        column.addLayout(row)

        self.error = QLabel("An absolute path is required.")
        self.error.setObjectName("settingsError")
        self.error.setHidden(True)
        column.addWidget(self.error)

        self.line.textChanged.connect(self._on_text_changed)
        # Checked when the operator has finished typing, not per keystroke: a
        # stat() against a dead network share can hang for seconds.
        self.line.editingFinished.connect(self._update_open_button)
        self.browse_button.clicked.connect(self._browse)
        self.open_button.clicked.connect(self._open)
        self._update_open_button()

    def _on_text_changed(self, _text: str) -> None:
        self.changed.emit()

    def value(self) -> str:
        return self.line.text().strip()

    def set_value(self, text: str) -> None:
        self.line.setText(text)
        self._update_open_button()

    def is_usable(self) -> bool:
        """True if the path is absolute; shows or hides the error line to match."""
        text = self.value()
        usable = text != "" and Path(text).is_absolute()
        self.error.setHidden(usable)
        return usable

    def _update_open_button(self) -> None:
        text = self.value()
        exists = text != "" and Path(text).is_absolute() and Path(text).is_dir()
        self.open_button.setEnabled(exists)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose the {self._title.lower()}", self.value()
        )
        if chosen:
            # Path() puts the platform's own separators back: Qt hands out "/".
            self.set_value(str(Path(chosen)))

    def _open(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.value()))


class SettingCard(QFrame):
    """
    One setting - or a few that belong together, like width and height - on a
    card: a title, a line of explanation, the control, and a Reset that appears
    once the value differs from the one the dialog opened with.
    """

    def __init__(self, title: str, hint: str, body: QWidget) -> None:
        super().__init__()
        self.setObjectName("settingsCard")
        self.setProperty("modified", False)
        #: The dotted keys this card edits. Filled in by the dialog.
        self.keys: list[str] = []
        self.body = body

        column = QVBoxLayout(self)
        column.setContentsMargins(16, 12, 16, 14)
        column.setSpacing(4)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(title)
        title_label.setObjectName("settingsCardTitle")
        heading.addWidget(title_label)
        heading.addStretch()
        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("settingsReset")
        self.reset_button.setAutoDefault(False)
        self.reset_button.setToolTip("Put back the value this dialog opened with.")
        self.reset_button.setHidden(True)
        heading.addWidget(self.reset_button)
        column.addLayout(heading)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("settingsCardHint")
            hint_label.setWordWrap(True)
            column.addWidget(hint_label)

        column.addSpacing(6)
        column.addWidget(body)

    def set_modified(self, modified: bool) -> None:
        self.reset_button.setHidden(not modified)
        if self.property("modified") == modified:
            return
        self.setProperty("modified", modified)
        # A dynamic property restyles only once the style is told to look again.
        self.style().unpolish(self)
        self.style().polish(self)


# --- The dialog -------------------------------------------------------------------


class SettingsDialog(QDialog):
    """Pages of setting cards; save through CORE; say what was saved - in one window."""

    def __init__(
        self,
        values: Mapping[str, str],
        send: Callable[[str, str], None],
        problem: str | None = None,
        parent: QWidget | None = None,
        answer_timeout_ms: int = ANSWER_TIMEOUT_MS,
        preview_theme: Callable[[str], None] | None = None,
    ) -> None:
        """
        Args:
            values: dotted key -> the value in force, as text (`setting_text`).
                A key missing here starts at its schema default.
            send: called once per changed key with (key, text) when the
                operator saves.
            problem: why the settings file was discarded at startup, or None.
                A discarded file cannot be written to - the Config Handler
                refuses, so the file is never replaced with defaults - so the
                dialog says why and offers no Save.
            preview_theme: called with a theme value as the operator picks it,
                and again with the theme in force if they leave without saving
                it. None: no preview.
        """
        super().__init__(parent)
        self._send = send
        self.problem = problem
        self._answer_timeout_ms = answer_timeout_ms
        self._preview_theme = preview_theme

        #: One control per dotted key. The dialog's whole editable state.
        self.editors: dict[str, SettingEditor] = {}
        #: The card holding each key. Width and height share one.
        self.cards: dict[str, SettingCard] = {}
        #: Window size preset name -> its button.
        self.presets: dict[str, QPushButton] = {}
        #: Each control's value as the dialog opened, to tell what changed.
        self._original: dict[str, str] = {}
        self._page_titles: list[str] = []
        self._page_keys: list[tuple[str, ...]] = []

        #: Changes sent to CORE and not answered yet, key -> text.
        self.pending: dict[str, str] = {}
        #: CORE's answers, in the order they arrived.
        self.results: list[ConfigParameterResult] = []
        #: True once CORE confirmed saving the theme, so leaving keeps it.
        self._theme_saved = False

        self._answer_timer = QTimer(self)
        self._answer_timer.setSingleShot(True)
        self._answer_timer.timeout.connect(self._answer_timed_out)

        self.setWindowTitle("Settings")
        self.setObjectName("settingsDialog")
        self.setModal(True)

        #: "edit", then "saving" once Save is pressed, then "result".
        self.showing = "edit"
        self.edit_page = self._build_edit_page(values)
        self.result_page: QWidget | None = None

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.edit_page)

    # --- Page 1: the settings -------------------------------------------------

    def _build_edit_page(self, values: Mapping[str, str]) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if self.problem is not None:
            banner = QLabel(
                "The settings file could not be used at startup, so the standard "
                "settings are in force and nothing can be saved from here. Correct "
                "the file, or delete it to have it recreated, then restart pypts.\n\n"
                f"{self.problem}"
            )
            banner.setObjectName("settingsProblem")
            banner.setWordWrap(True)
            banner.setContentsMargins(20, 14, 20, 14)
            outer.addWidget(banner)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(190)
        self.pages = QStackedWidget()
        # On the pages rather than the whole dialog, so the problem banner adds
        # height instead of taking it from them. Wide enough for the three
        # theme cards side by side.
        self.pages.setMinimumSize(680, 500)
        for title, keys in pages_for_schema():
            self._page_titles.append(title)
            self._page_keys.append(keys)
            self.nav.addItem(title)
            self.pages.addWidget(self._build_page(title, keys, values))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        middle.addWidget(self.nav)
        middle.addWidget(self.pages, stretch=1)
        outer.addLayout(middle, stretch=1)
        outer.addWidget(self._footer())

        # Only now: every control exists, and so does the Save button the
        # handler touches. Connecting earlier would fire it half-built.
        for key, editor in self.editors.items():
            self._original[key] = editor.value()
        if self.problem is not None:
            for card in self._all_cards():
                card.body.setEnabled(False)
        self._connect_editors()
        self._refresh()
        return page

    def _build_page(
        self, title: str, keys: tuple[str, ...], values: Mapping[str, str]
    ) -> QWidget:
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 20, 24, 20)
        column.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("settingsPageTitle")
        column.addWidget(heading)

        has_window_size = WIDTH_KEY in keys and HEIGHT_KEY in keys
        for key in keys:
            if key in self.cards:
                continue
            if has_window_size and key in (WIDTH_KEY, HEIGHT_KEY):
                column.addWidget(self._window_size_card(values))
            else:
                column.addWidget(self._single_card(key, values))
        column.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _single_card(self, key: str, values: Mapping[str, str]) -> SettingCard:
        field = field_for(key)
        editor = self._editor_for(key, field, values.get(key, field.default))
        card = SettingCard(label_for(key), HINTS.get(key, ""), editor)
        self._register(key, editor, card)
        return card

    @staticmethod
    def _editor_for(key: str, field: Field, text: str) -> SettingEditor:
        if key == THEME_KEY and field.choices:
            return ThemeCards(field.choices, text)
        if field.type == "bool":
            return OnOffSwitch(text)
        if field.type == "int":
            return NumberField(text, field.default)
        if field.type == "path":
            return FolderField(text, label_for(key))
        if field.choices:
            return ChoiceButtons(field.choices, text)
        return TextField(text)

    def _window_size_card(self, values: Mapping[str, str]) -> SettingCard:
        width_field = field_for(WIDTH_KEY)
        height_field = field_for(HEIGHT_KEY)
        width = NumberField(values.get(WIDTH_KEY, width_field.default), width_field.default)
        height = NumberField(values.get(HEIGHT_KEY, height_field.default), height_field.default)

        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        size_row.addWidget(width)
        times = QLabel("×")  # noqa: RUF001 - a multiplication sign, meant for the reader
        times.setObjectName("settingsCardTitle")
        size_row.addWidget(times)
        size_row.addWidget(height)
        unit = QLabel("pixels")
        unit.setObjectName("settingsCardHint")
        size_row.addWidget(unit)
        size_row.addStretch()
        column.addLayout(size_row)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(6)
        for name, preset_width, preset_height in WINDOW_PRESETS:
            button = QPushButton(f"{name}  {preset_width} × {preset_height}")  # noqa: RUF001 - sign
            button.setObjectName("settingsPreset")
            button.setAutoDefault(False)
            button.clicked.connect(
                lambda _checked=False, w=preset_width, h=preset_height: self._use_window_size(
                    w, h
                )
            )
            self.presets[name] = button
            preset_row.addWidget(button)
        preset_row.addStretch()
        column.addLayout(preset_row)

        card = SettingCard(
            "Window size",
            "The window is never smaller than 1000 × 700.",  # noqa: RUF001 - a multiplication sign
            body,
        )
        self._register(WIDTH_KEY, width, card)
        self._register(HEIGHT_KEY, height, card)
        return card

    def _register(self, key: str, editor: SettingEditor, card: SettingCard) -> None:
        self.editors[key] = editor
        if not card.keys:
            card.reset_button.clicked.connect(
                lambda _checked=False, c=card: self._reset_card(c)
            )
        self.cards[key] = card
        card.keys.append(key)

    def _footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("settingsFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(8)

        note = QLabel(FOOTER_NOTE)
        note.setObjectName("settingsFooterNote")
        row.addWidget(note)
        row.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.cancel_button)

        # Text and enabled state are settled by _refresh().
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primaryBtn")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self._save)
        row.addWidget(self.save_button)
        return footer

    def _all_cards(self) -> list[SettingCard]:
        """Every card once, in page order."""
        return list(dict.fromkeys(self.cards.values()))

    # --- Editing ------------------------------------------------------------------

    def _connect_editors(self) -> None:
        for key, editor in self.editors.items():
            editor.changed.connect(lambda k=key: self._on_edited(k))

    def text_of(self, key: str) -> str:
        """One control's value, spelled the way config.ini spells it."""
        return self.editors[key].value()

    def set_value(self, key: str, text: str) -> None:
        """Change one control, exactly as the operator would."""
        self.editors[key].set_value(text)

    def changes(self) -> dict[str, str]:
        """Every key whose control no longer holds what it opened with, key -> text."""
        changed = {}
        for key, editor in self.editors.items():
            text = editor.value()
            if text != self._original[key]:
                changed[key] = text
        return changed

    def _on_edited(self, key: str) -> None:
        if key == THEME_KEY and self._preview_theme is not None:
            self._preview_theme(self.text_of(THEME_KEY))
        self._refresh()

    def _use_window_size(self, width: int, height: int) -> None:
        self.set_value(WIDTH_KEY, str(width))
        self.set_value(HEIGHT_KEY, str(height))

    def _reset_card(self, card: SettingCard) -> None:
        for key in card.keys:
            self.set_value(key, self._original[key])

    def _refresh(self) -> None:
        """Keep the marks, the error lines and the Save button honest as the operator edits."""
        folders_usable = True
        for editor in self.editors.values():
            # Every folder is checked, not just up to the first bad one, so
            # each shows its own error line.
            if isinstance(editor, FolderField) and not editor.is_usable():
                folders_usable = False

        changed = self.changes()
        if self.showing == "edit":
            for card in self._all_cards():
                card.set_modified(any(key in changed for key in card.keys))

        for row, keys in enumerate(self._page_keys):
            title = self._page_titles[row]
            if any(key in changed for key in keys):
                title = title + MODIFIED_MARK
            self.nav.item(row).setText(title)

        if changed:
            self.save_button.setText(f"Save {count_of(len(changed), 'change')}")
        else:
            self.save_button.setText("Save")
        self.save_button.setEnabled(self.problem is None and bool(changed) and folders_usable)

    # --- Saving ---------------------------------------------------------------------

    def _save(self) -> None:
        changed = self.changes()
        if not changed or self.problem is not None:
            return

        # Before sending, so every answer finds its key waiting.
        self.pending = dict(changed)
        self.showing = "saving"
        for card in self._all_cards():
            card.body.setEnabled(False)
            card.reset_button.setHidden(True)
        self.save_button.setEnabled(False)
        self.save_button.setText("Saving...")
        self.cancel_button.setText("Close")

        for key, text in changed.items():
            self._send(key, text)
        self._answer_timer.start(self._answer_timeout_ms)

    def apply_result(self, result: ConfigParameterResult) -> bool:
        """
        Take one of CORE's answers. True if this dialog was waiting for it.

        The result page is shown once the last answer is in.
        """
        if result.key not in self.pending:
            return False
        del self.pending[result.key]
        self.results.append(result)
        if result.key == THEME_KEY and result.accepted:
            self._theme_saved = True
        if not self.pending:
            self._answer_timer.stop()
            self._show_result_page()
        return True

    def _answer_timed_out(self) -> None:
        if self.showing != "saving":
            return
        for key, text in self.pending.items():
            self.results.append(
                ConfigParameterResult(key=key, value=text, accepted=False, reason=NO_ANSWER_REASON)
            )
        self.pending = {}
        self._show_result_page()

    def done(self, result: int) -> None:
        """
        Every way out - Close, Cancel, Escape, the title bar's X - comes through
        here, so this is where a previewed theme is put back, unless CORE
        confirmed saving it.
        """
        self._answer_timer.stop()
        if self._preview_theme is not None and not self._theme_saved:
            original = self._original.get(THEME_KEY)
            if original is not None and self.text_of(THEME_KEY) != original:
                self._preview_theme(original)
        super().done(result)

    # --- Page 2: what was saved -------------------------------------------------------

    def _show_result_page(self) -> None:
        # Hidden and taken out of the layout, not deleted: the caller may still
        # hold a reference to a control on it.
        self.body.removeWidget(self.edit_page)
        self.edit_page.hide()

        self.result_page = self._build_result_page()
        self.body.addWidget(self.result_page)
        self.showing = "result"
        self.adjustSize()

    def _build_result_page(self) -> QWidget:
        saved = [result for result in self.results if result.accepted]
        refused = [result for result in self.results if not result.accepted]

        page = QWidget()
        page.setMinimumWidth(520)
        column = QVBoxLayout(page)
        column.setContentsMargins(28, 24, 28, 20)
        column.setSpacing(0)

        if not refused:
            heading = "Saved"
        elif not saved:
            heading = "Not saved"
        else:
            heading = "Partly saved"
        title = QLabel(heading)
        title.setObjectName("settingsResultTitle")
        column.addWidget(title)

        if saved:
            summary = f"{count_of(len(saved), 'setting')} saved. {NEXT_START_NOTE}"
        else:
            summary = "Nothing was saved."
        summary_label = QLabel(summary)
        summary_label.setObjectName("settingsSubtitle")
        column.addWidget(summary_label)

        if saved:
            column.addSpacing(14)
            for result in saved:
                line = QLabel(f"✓  {label_for(result.key)}: {result.value}")
                line.setObjectName("settingsSaved")
                line.setToolTip(result.key)
                column.addSpacing(4)
                column.addWidget(line)

        if refused:
            column.addSpacing(14)
            for result in refused:
                line = QLabel(f"✗  {label_for(result.key)}: {result.reason}")
                line.setObjectName("settingsRefused")
                line.setToolTip(result.key)
                # A reason from the Config Handler can be a long sentence.
                line.setWordWrap(True)
                column.addSpacing(4)
                column.addWidget(line)

        column.addStretch()
        column.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("primaryBtn")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        column.addLayout(buttons)
        return page
