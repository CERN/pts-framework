# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The TopBar content: the run controls.

A pure view in the assembler shape (gui.md section 6): callbacks in through
the constructor, update methods out, no protocol knowledge. The enable/disable
lifecycle is the old toolbar's state machine made event-driven - every
transition is caused by a message CORE sent, never by waiting for one
(gui.md section 5.4), so nothing here ever blocks.
"""

from collections.abc import Callable

from PySide6.QtCore import QByteArray, QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QHelpEvent, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QToolTip,
    QWidget,
)

from pypts.hmi.gui.palette import get_palette
from pypts.messages.run_events import RecipeLoaded

_FOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round">'
    '<path d="M2 12V5a1 1 0 011-1h3.5l1.5 1.5H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1z"/>'
    "</svg>"
)
_REPORT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"'
    ' stroke-linejoin="round">'
    '<path d="M9.5 1.5H4a1 1 0 00-1 1v11a1 1 0 001 1h8a1 1 0 001-1V5z"/>'
    '<path d="M9.5 1.5V5H13"/>'
    '<path d="M5.5 8.5h5M5.5 11h5"/>'
    "</svg>"
)
_PLAY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="{color}"><polygon points="4,2 14,8 4,14"/></svg>'
)
_STOP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="{color}"><rect x="3" y="3" width="10" height="10" rx="1.5"/></svg>'
)
_PAUSE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="{color}"><rect x="3" y="2" width="4" height="12" rx="1"/>'
    '<rect x="9" y="2" width="4" height="12" rx="1"/></svg>'
)


def _svg_icon(svg_str: str, size: int = 16) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg_str.encode()))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def describe(widget: QWidget, title: str, detail: str) -> None:
    """
    One description, in the two places it has to be.

    The tooltip is rich text so the action name reads as a heading above what it
    does; `accessibleName`/`accessibleDescription` carry the same words in plain
    text, which is what a screen reader announces. Setting one without the other
    means a sighted operator and an assisted one are told different things.
    """
    widget.setToolTip(f"<b>{title}</b><br>{detail}")
    widget.setAccessibleName(title)
    widget.setAccessibleDescription(detail)


class TopBarContent(QToolBar):
    """Open / sequence chooser / Start / Pause / Stop. A native QToolBar."""

    def __init__(
        self,
        on_open: Callable[[str], None],
        on_start: Callable[[str], None],
        on_stop: Callable[[], None],
        on_pause: Callable[[], None],
        on_sequence_selected: Callable[[str], None],
        on_open_report: Callable[[], None],
    ) -> None:
        super().__init__()
        self.setMovable(False)
        self.setObjectName("PtsToolBar")
        self.setIconSize(QSize(16, 16))

        self._on_open = on_open
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_pause = on_pause
        self._on_sequence_selected = on_sequence_selected
        self._on_open_report = on_open_report
        self._dark = False
        self._running = False
        self._metadata: dict[str, str] = {}
        self._paused = False

        self.open_button = QToolButton()
        self.open_button.setAutoRaise(True)
        self.open_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.open_button.setIconSize(QSize(16, 16))
        self.open_button.clicked.connect(self.choose_recipe_file)

        self.start_button = QToolButton()
        self.start_button.setAutoRaise(True)
        self.start_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.start_button.setIconSize(QSize(16, 16))
        self.start_button.clicked.connect(
            lambda: self._on_start(self.sequence_combo.currentText())
        )

        self.pause_button = QToolButton()
        self.pause_button.setAutoRaise(True)
        self.pause_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.pause_button.setIconSize(QSize(16, 16))
        self.pause_button.clicked.connect(self._on_pause)

        self.stop_button = QToolButton()
        self.stop_button.setAutoRaise(True)
        self.stop_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.stop_button.setIconSize(QSize(16, 16))
        self.stop_button.clicked.connect(self._on_stop)

        # What the run has learned about the unit on the bench: the globals the
        # recipe named in `report_metadata`, most often its serial number. Empty
        # and invisible until a run sets one, so a recipe that names none costs
        # no space in the bar.
        self.metadata_label = QLabel("")
        self.metadata_label.setObjectName("runMetadataLabel")
        self.metadata_label.setVisible(False)

        self.sequence_combo = QComboBox()
        self.sequence_combo.currentTextChanged.connect(self._sequence_changed)

        combo_container = QWidget()
        combo_layout = QHBoxLayout(combo_container)
        combo_layout.setContentsMargins(4, 0, 4, 0)
        combo_layout.setSpacing(4)
        combo_layout.addWidget(QLabel("Sequence:"))
        combo_layout.addWidget(self.sequence_combo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.report_button = QToolButton()
        self.report_button.setAutoRaise(True)
        self.report_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.report_button.setIconSize(QSize(16, 16))
        self.report_button.clicked.connect(self._on_open_report)

        self.addWidget(self.open_button)
        self.addWidget(self.start_button)
        self.addWidget(self.pause_button)
        self.addWidget(self.stop_button)
        self.addWidget(combo_container)
        self.addWidget(spacer)
        self.addWidget(self.metadata_label)
        self.addWidget(self.report_button)

        self.sequence_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

        self._refresh_controls()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        """Icons and descriptions both depend on the state, so they move together."""
        self._refresh_icons()
        self._refresh_descriptions()

    def _refresh_icons(self) -> None:
        palette = get_palette(self._dark)
        icon_color = palette.accent_text if self._dark else palette.toolbutton
        disabled = palette.icon_disabled
        self.open_button.setIcon(_svg_icon(_FOLDER_SVG.format(color=icon_color)))
        can_start = self.start_button.isEnabled()
        can_pause = self.pause_button.isEnabled()
        can_stop = self.stop_button.isEnabled()
        self.start_button.setIcon(
            _svg_icon(_PLAY_SVG.format(color=palette.icon_start if can_start else disabled))
        )
        self.pause_button.setIcon(
            _svg_icon(_PAUSE_SVG.format(color=palette.icon_pause if can_pause else disabled))
        )
        self.stop_button.setIcon(
            _svg_icon(_STOP_SVG.format(color=palette.icon_stop if can_stop else disabled))
        )
        self.report_button.setIcon(_svg_icon(_REPORT_SVG.format(color=icon_color)))

    def _refresh_descriptions(self) -> None:
        """
        What each control does, or why it cannot be used right now.

        The disabled wording is the point of this being state-driven: a greyed
        button that does not say why is the thing an operator files a bug about.
        """
        describe(
            self.open_button,
            "Open recipe",
            "Choose a YAML recipe file to load."
            if self.open_button.isEnabled()
            else "Not while a run is in progress - stop the run first.",
        )
        describe(
            self.start_button,
            "Start",
            "Run the selected sequence from its first step."
            if self.start_button.isEnabled()
            else self._why_no_start(),
        )
        if self._paused:
            describe(
                self.pause_button,
                "Resume",
                "Continue the run from the step it was held at.",
            )
        else:
            describe(
                self.pause_button,
                "Pause",
                "Hold the run before the next step. The window stays live, so "
                "results can be browsed while it waits."
                if self.pause_button.isEnabled()
                else "Nothing is running.",
            )
        describe(
            self.stop_button,
            "Stop",
            "Abort the running sequence. The application stays open."
            if self.stop_button.isEnabled()
            else "Nothing is running.",
        )
        describe(
            self.report_button,
            "Open report folder",
            "Open this run's report folder. Before the first run of a session, "
            "opens the folder holding every report.",
        )
        describe(
            self.sequence_combo,
            "Sequence",
            "Which sequence of the loaded recipe Start will run."
            if self.sequence_combo.isEnabled()
            else "Open a recipe first.",
        )

    def _why_no_start(self) -> str:
        if self._running:
            return "A run is already in progress."
        return "Open a recipe first."

    def event(self, incoming: QEvent) -> bool:
        """
        Answer tooltip requests on a disabled button's behalf.

        Qt shows no tooltip for a disabled widget - a disabled widget receives no
        mouse events at all - and here the disabled tooltips are the ones worth
        reading ("Open a recipe first"). The event falls through to the toolbar
        instead, so the toolbar finds the child under the cursor and shows its
        text. An *enabled* child handles its own tooltip and this never sees it.
        """
        if incoming.type() == QEvent.Type.ToolTip and isinstance(incoming, QHelpEvent):
            text = self.tooltip_at(incoming.pos())
            if text:
                QToolTip.showText(incoming.globalPos(), text, self)
                return True
        return super().event(incoming)

    def tooltip_at(self, position: QPoint) -> str:
        """
        The description of whatever control is at `position`, or "" if there is
        nothing there to describe.

        Split out of `event()` because `event()` cannot be asserted on: the base
        implementation accepts a ToolTip event whatever happens, so its return
        value says nothing about which branch ran.
        """
        child = self.childAt(position)
        if child is None:
            return ""
        return child.toolTip()

    def set_paused(self, paused: bool) -> None:
        """Paused: the Pause button resumes, so it has to stop saying "Pause"."""
        self._paused = paused
        self._refresh_controls()

    def choose_recipe_file(self) -> None:
        """The Open button: a file dialog, then the recipe path to the assembler."""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Open Recipe", "", "Recipes (*.yml *.yaml);;All Files (*)"
        )
        if path:
            self._on_open(path)

    def _sequence_changed(self, sequence_name: str) -> None:
        if sequence_name:
            self._on_sequence_selected(sequence_name)

    # --- State transitions, each caused by a message ---------------------------

    def show_run_metadata(self, values: tuple[tuple[str, str], ...]) -> None:
        """Show the run's metadata beside the report button."""
        self._metadata.update(dict(values))
        shown = " | ".join(f"{name}: {value}" for name, value in self._metadata.items())
        self.metadata_label.setText(shown)
        self.metadata_label.setVisible(bool(shown))

    def clear_run_metadata(self) -> None:
        """A new recipe describes a different unit, so the old one stops showing."""
        self._metadata = {}
        self.metadata_label.setText("")
        self.metadata_label.setVisible(False)

    def show_recipe_loaded(self, event: RecipeLoaded) -> None:
        """A recipe is in: offer its sequences, allow starting."""
        self.clear_run_metadata()
        self.sequence_combo.blockSignals(True)
        self.sequence_combo.clear()
        for sequence in event.sequences:
            self.sequence_combo.addItem(sequence.sequence_name)
        self.sequence_combo.setCurrentText(event.main_sequence)
        self.sequence_combo.blockSignals(False)
        self.sequence_combo.setEnabled(True)
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._refresh_controls()

    def show_run_started(self) -> None:
        """A run is on: nothing may change under it, only pausing and stopping are left."""
        self._running = True
        self._paused = False
        self.open_button.setEnabled(False)
        self.sequence_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self._refresh_controls()

    def show_run_finished(self) -> None:
        """The run answered - however it went, the operator has the controls back."""
        self._running = False
        self._paused = False
        self.open_button.setEnabled(True)
        self.sequence_combo.setEnabled(True)
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._refresh_controls()
