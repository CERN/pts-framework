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

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from pypts.messages.run_events import RecipeLoaded

_FOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"'
    ' fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round">'
    '<path d="M2 12V5a1 1 0 011-1h3.5l1.5 1.5H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1z"/>'
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


class TopBarContent(QToolBar):
    """Open / sequence chooser / Start / Pause / Stop. A native QToolBar."""

    def __init__(
        self,
        on_open: Callable[[str], None],
        on_start: Callable[[str], None],
        on_stop: Callable[[], None],
        on_pause: Callable[[], None],
        on_sequence_selected: Callable[[str], None],
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
        self._dark = False

        self.open_button = QToolButton()
        self.open_button.setAutoRaise(True)
        self.open_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.open_button.setIconSize(QSize(16, 16))
        self.open_button.setToolTip("Open recipe")
        self.open_button.clicked.connect(self.choose_recipe_file)

        self.start_button = QToolButton()
        self.start_button.setAutoRaise(True)
        self.start_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.start_button.setIconSize(QSize(16, 16))
        self.start_button.setToolTip("Start")
        self.start_button.clicked.connect(
            lambda: self._on_start(self.sequence_combo.currentText())
        )

        self.pause_button = QToolButton()
        self.pause_button.setAutoRaise(True)
        self.pause_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.pause_button.setIconSize(QSize(16, 16))
        self.pause_button.setToolTip("Pause")
        self.pause_button.clicked.connect(self._on_pause)

        self.stop_button = QToolButton()
        self.stop_button.setAutoRaise(True)
        self.stop_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.stop_button.setIconSize(QSize(16, 16))
        self.stop_button.setToolTip("Stop")
        self.stop_button.clicked.connect(self._on_stop)

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

        self._brand = QLabel("pypts")
        self._brand.setStyleSheet("font-size:11px; color:#94a3b8; padding-right:6px;")

        self.addWidget(self.open_button)
        self.addWidget(self.start_button)
        self.addWidget(self.pause_button)
        self.addWidget(self.stop_button)
        self.addWidget(combo_container)
        self.addWidget(spacer)
        self.addWidget(self._brand)

        self.sequence_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

        self._refresh_icons()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._brand.setStyleSheet(
            f"font-size:11px; color:{'#666666' if dark else '#94a3b8'}; padding-right:6px;"
        )
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        icon_color = "#7AABDF" if self._dark else "#424242"
        self.open_button.setIcon(_svg_icon(_FOLDER_SVG.format(color=icon_color)))
        can_start = self.start_button.isEnabled()
        can_pause = self.pause_button.isEnabled()
        can_stop = self.stop_button.isEnabled()
        self.start_button.setIcon(
            _svg_icon(_PLAY_SVG.format(color="#1B5E20" if can_start else "#BDBDBD"))
        )
        self.pause_button.setIcon(
            _svg_icon(_PAUSE_SVG.format(color="#E65100" if can_pause else "#BDBDBD"))
        )
        self.stop_button.setIcon(
            _svg_icon(_STOP_SVG.format(color="#CC0000" if can_stop else "#BDBDBD"))
        )

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

    def show_recipe_loaded(self, event: RecipeLoaded) -> None:
        """A recipe is in: offer its sequences, allow starting."""
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
        self._refresh_icons()

    def show_run_started(self) -> None:
        """A run is on: nothing may change under it, only pausing and stopping are left."""
        self.open_button.setEnabled(False)
        self.sequence_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self._refresh_icons()

    def show_run_finished(self) -> None:
        """The run answered - however it went, the operator has the controls back."""
        self.open_button.setEnabled(True)
        self.sequence_combo.setEnabled(True)
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._refresh_icons()
