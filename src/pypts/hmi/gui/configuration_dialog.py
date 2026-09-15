# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Configuration dialog: Edit -> Configuration.

Every setting in config.ini an operator may change, one editor per key, grouped
by section. Save sends the changed ones; the same window then says what was
saved and what was not.

**It does not write the file.** CORE is the single runtime writer of config.ini
(config_handler.md), so Save hands each changed value to a `send` callable - the
GUI passes `set_config_parameter()`, which puts a SetConfigParameter on the link
- and waits for CORE's ConfigParameterResult for each one, which the GUI passes
to `apply_result()`. The answers get here through the GUI's poll timer, which
keeps firing inside `exec()`'s nested event loop. If they do not all arrive
within ANSWER_TIMEOUT_MS the dialog stops waiting and says so.

**The editors come from the schema.** A key with choices is a combo box, an int
a number field, a bool a check box, a path a line edit with a Browse button, any
other string a line edit. A key added to `configuration_schema.py` shows up here
with no change to this file; LABELS and HINTS only make it read well.
`READ_ONLY_SECTIONS` are left out, and CORE refuses them anyway.

**Nothing changes until the next start.** Every process read its configuration
once, at startup, and nothing tells a running one that a value changed. Both
pages say so rather than letting the operator expect the window to move.

Pure presentation, like `remove_cache_dialog.py`: handed the values in force and
the `send` callable, so a test drives the whole dialog with no CORE and no file.
The two pages are swapped in the layout rather than stacked, for the reason
given there. Styling lives in `styles.py` (object names `configDialog*`).
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
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

#: Upper bound of every whole-number editor. Only there so a slipped finger
#: cannot type a window no screen could show.
_SPIN_MAXIMUM = 100_000

#: Height of every editor, and of the label beside it so the two line up. Set
#: explicitly because the stylesheet's padding otherwise lets a crowded layout
#: squeeze a line edit down to a sliver.
_EDITOR_HEIGHT = 28

#: What each section is called on screen. A section missing here shows its own name.
SECTION_TITLES = {
    "paths": "Paths",
    "logging": "Logging",
    "report": "Report",
    "gui": "Window",
    "watchdog": "Watchdog",
}

#: What each key is called on screen. A key missing here shows its own name.
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

#: One short line under an editor, where a key needs explaining.
HINTS = {
    "paths.logs_dir": "Every run writes its log here.",
    "paths.reports_dir": "Every run gets a report folder here.",
    "logging.level": "DEBUG adds the full message trace.",
    "report.type": "Not used yet.",
    "report.theme": "Not used yet.",
    "gui.theme": "default follows the operating system.",
    "gui.window_width": "In pixels. Never narrower than 1000.",
    "gui.window_height": "In pixels. Never shorter than 700.",
    "watchdog.enabled": "Turn off only while debugging the engine.",
}

#: The sentence that closes both pages.
NEXT_START_NOTE = "Changes take effect the next time pypts starts."

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


def label_for(key: str) -> str:
    return LABELS.get(key, key)


class ConfigurationDialog(QDialog):
    """Edit, save through CORE, report - in one window."""

    def __init__(
        self,
        values: Mapping[str, str],
        send: Callable[[str, str], None],
        problem: str | None = None,
        parent: QWidget | None = None,
        answer_timeout_ms: int = ANSWER_TIMEOUT_MS,
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
        """
        super().__init__(parent)
        self._send = send
        self.problem = problem
        self._answer_timeout_ms = answer_timeout_ms

        #: One editor per dotted key. The dialog's whole editable state.
        self.editors: dict[str, QWidget] = {}
        #: The "An absolute path is required." label under each path editor.
        self.path_errors: dict[str, QLabel] = {}
        #: Each editor's text as it opened, to tell what the operator changed.
        self._original: dict[str, str] = {}

        #: Changes sent to CORE and not answered yet, key -> text.
        self.pending: dict[str, str] = {}
        #: CORE's answers, in the order they arrived.
        self.results: list[ConfigParameterResult] = []

        self._answer_timer = QTimer(self)
        self._answer_timer.setSingleShot(True)
        self._answer_timer.timeout.connect(self._answer_timed_out)

        self.setWindowTitle("Configuration")
        self.setObjectName("configDialog")
        self.setModal(True)
        self.setMinimumWidth(560)

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
        column = QVBoxLayout(page)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(0)

        title = QLabel("Configuration")
        title.setObjectName("configDialogTitle")
        column.addWidget(title)

        subtitle = QLabel(f"Saved to config.ini. {NEXT_START_NOTE}")
        subtitle.setObjectName("configDialogSubtitle")
        column.addWidget(subtitle)

        if self.problem is not None:
            column.addSpacing(12)
            banner = QLabel(
                "The settings file could not be used at startup, so the standard "
                "settings are in force and nothing can be saved from here. Correct "
                "the file, or delete it to have it recreated, then restart pypts.\n\n"
                f"{self.problem}"
            )
            banner.setObjectName("configDialogProblem")
            banner.setWordWrap(True)
            column.addWidget(banner)

        column.addSpacing(6)
        column.addLayout(self._settings_grid(values))
        column.addStretch()
        column.addSpacing(18)
        column.addLayout(self._edit_buttons())

        # Only now: every editor exists, and so does the Save button the
        # handler touches. Connecting earlier would fire it half-built.
        for key in self.editors:
            self._original[key] = self.text_of(key)
        self._connect_editors()
        self._refresh()
        return page

    def _settings_grid(self, values: Mapping[str, str]) -> QGridLayout:
        """
        Every section's heading and rows, in one grid.

        One grid rather than a form per section, so the editors of every
        section start at the same x and the page reads as one column.
        """
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        row = 0
        for section, fields in SCHEMA.items():
            if section in READ_ONLY_SECTIONS:
                continue

            heading = QLabel(SECTION_TITLES.get(section, section))
            heading.setObjectName("configDialogSection")
            heading.setContentsMargins(0, 14, 0, 2)
            grid.addWidget(heading, row, 0, 1, 2)
            row += 1

            for name, field in fields.items():
                key = f"{section}.{name}"
                text = values.get(key, field.default)
                field_widget = self._field_widget(key, field, text)
                if field.type == "bool":
                    # The check box carries its own caption; a label beside
                    # it would say the same thing twice.
                    grid.addWidget(field_widget, row, 0, 1, 2)
                else:
                    label = QLabel(label_for(key))
                    label.setObjectName("configDialogKey")
                    label.setToolTip(key)
                    label.setMinimumHeight(_EDITOR_HEIGHT)
                    grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
                    grid.addWidget(field_widget, row, 1)
                row += 1
        return grid

    def _field_widget(self, key: str, field: Field, text: str) -> QWidget:
        """The editor for one key, with its hint and its error line under it."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        editor = self._editor_for(key, field, text)
        editor.setToolTip(key)
        editor.setEnabled(self.problem is None)
        self.editors[key] = editor

        if field.type == "path":
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(editor, stretch=1)
            browse = QPushButton("Browse...")
            browse.setObjectName("configDialogBrowse")
            browse.setMinimumHeight(_EDITOR_HEIGHT)
            # Not a default button: Return in a path field must not open a
            # file dialog.
            browse.setAutoDefault(False)
            browse.setEnabled(self.problem is None)
            browse.clicked.connect(lambda _checked=False, k=key: self._browse(k))
            row.addWidget(browse)
            column.addLayout(row)
        else:
            column.addWidget(editor)

        hint_text = HINTS.get(key)
        if hint_text:
            hint = QLabel(hint_text)
            hint.setObjectName("configDialogHint")
            column.addWidget(hint)

        if field.type == "path":
            error = QLabel("An absolute path is required.")
            error.setObjectName("configDialogError")
            error.setHidden(True)
            self.path_errors[key] = error
            column.addWidget(error)
        return holder

    @staticmethod
    def _editor_for(key: str, field: Field, text: str) -> QWidget:
        if field.type == "bool":
            box = QCheckBox(label_for(key))
            box.setObjectName("configDialogCheck")
            box.setChecked(text.strip().lower() in TRUE_VALUES)
            return box

        editor: QWidget
        if field.type == "int":
            spin = QSpinBox()
            spin.setRange(0, _SPIN_MAXIMUM)
            # A number field, not arrows: nobody sets a window width one pixel
            # at a time, and the arrows do not survive the stylesheet's border.
            # The keyboard arrows and the wheel still step the value.
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            try:
                spin.setValue(int(text))
            except ValueError:
                spin.setValue(int(field.default))
            editor = spin
        elif field.choices:
            combo = QComboBox()
            combo.addItems(list(field.choices))
            combo.setCurrentText(text)
            editor = combo
        else:
            editor = QLineEdit(text)

        editor.setMinimumHeight(_EDITOR_HEIGHT)
        return editor

    def _connect_editors(self) -> None:
        for editor in self.editors.values():
            if isinstance(editor, QCheckBox):
                editor.toggled.connect(self._refresh)
            elif isinstance(editor, QSpinBox):
                editor.valueChanged.connect(self._refresh)
            elif isinstance(editor, QComboBox):
                editor.currentTextChanged.connect(self._refresh)
            elif isinstance(editor, QLineEdit):
                editor.textChanged.connect(self._refresh)

    def _edit_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

        # Text and enabled state are settled by _refresh().
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primaryBtn")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button)
        return layout

    # --- Reading the editors ------------------------------------------------------

    def text_of(self, key: str) -> str:
        """One editor's value, spelled the way config.ini spells it."""
        editor = self.editors[key]
        if isinstance(editor, QCheckBox):
            if editor.isChecked():
                return "true"
            return "false"
        if isinstance(editor, QSpinBox):
            return str(editor.value())
        if isinstance(editor, QComboBox):
            return editor.currentText()
        if isinstance(editor, QLineEdit):
            return editor.text().strip()
        raise TypeError(f"No reader for the editor of {key!r}: {type(editor).__name__}")

    def changes(self) -> dict[str, str]:
        """Every key whose editor no longer holds what it opened with, key -> text."""
        changed = {}
        for key in self.editors:
            text = self.text_of(key)
            if text != self._original[key]:
                changed[key] = text
        return changed

    def _check_paths(self) -> bool:
        """
        Show or hide each path's error line; True if every path is usable.

        Absolute, because a relative path would be resolved against whatever
        directory pypts happened to be started from - a different folder on
        every bench. The Config Handler only insists on non-empty.
        """
        all_usable = True
        for key, error in self.path_errors.items():
            text = self.text_of(key)
            usable = text != "" and Path(text).is_absolute()
            error.setHidden(usable)
            if not usable:
                all_usable = False
        return all_usable

    def _refresh(self) -> None:
        """Keep the error lines and the Save button honest as the operator edits."""
        paths_usable = self._check_paths()
        changed = self.changes()

        if changed:
            self.save_button.setText(f"Save {count_of(len(changed), 'change')}")
        else:
            self.save_button.setText("Save")
        self.save_button.setEnabled(self.problem is None and bool(changed) and paths_usable)

    def _browse(self, key: str) -> None:
        editor = self.editors[key]
        if not isinstance(editor, QLineEdit):
            return
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose the {label_for(key).lower()}", editor.text()
        )
        if chosen:
            # Path() puts the platform's own separators back: Qt hands out "/".
            editor.setText(str(Path(chosen)))

    # --- Saving ---------------------------------------------------------------------

    def _save(self) -> None:
        changed = self.changes()
        if not changed or self.problem is not None:
            return

        # Before sending, so every answer finds its key waiting.
        self.pending = dict(changed)
        self.showing = "saving"
        for editor in self.editors.values():
            editor.setEnabled(False)
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

    # --- Page 2: what was saved -------------------------------------------------------

    def _show_result_page(self) -> None:
        # Hidden and taken out of the layout, not deleted: the caller may still
        # hold a reference to an editor on it.
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
        column = QVBoxLayout(page)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(0)

        if not refused:
            heading = "Saved"
        elif not saved:
            heading = "Not saved"
        else:
            heading = "Partly saved"
        title = QLabel(heading)
        title.setObjectName("configDialogTitle")
        column.addWidget(title)

        if saved:
            summary = f"{count_of(len(saved), 'setting')} saved. {NEXT_START_NOTE}"
        else:
            summary = "Nothing was saved."
        summary_label = QLabel(summary)
        summary_label.setObjectName("configDialogSubtitle")
        column.addWidget(summary_label)

        if saved:
            column.addSpacing(12)
            for result in saved:
                line = QLabel(f"{label_for(result.key)}: {result.value}")
                line.setObjectName("configDialogSaved")
                line.setToolTip(result.key)
                column.addWidget(line)

        if refused:
            column.addSpacing(12)
            heading_label = QLabel("Not saved:")
            heading_label.setObjectName("configDialogSection")
            column.addWidget(heading_label)
            for result in refused:
                line = QLabel(f"{label_for(result.key)}: {result.reason}")
                line.setObjectName("configDialogError")
                line.setToolTip(result.key)
                # A reason from the Config Handler can be a long sentence.
                line.setWordWrap(True)
                column.addSpacing(4)
                column.addWidget(line)

        column.addStretch()
        column.addSpacing(16)
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
