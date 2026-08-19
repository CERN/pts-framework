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

from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from pypts.messages.run_events import RecipeLoaded


class TopBarContent(QWidget):
    """Open / sequence chooser / Start / Stop / recipe name."""

    def __init__(
        self,
        on_open: Callable[[str], None],
        on_start: Callable[[str], None],
        on_stop: Callable[[], None],
        on_sequence_selected: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._on_open = on_open
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_sequence_selected = on_sequence_selected

        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(self.choose_recipe_file)

        self.sequence_combo = QComboBox()
        self.sequence_combo.currentTextChanged.connect(self._sequence_changed)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(
            lambda: self._on_start(self.sequence_combo.currentText())
        )

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._on_stop)

        self.recipe_label = QLabel("No recipe loaded")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)
        row.addWidget(self.open_button)
        row.addWidget(QLabel("Sequence:"))
        row.addWidget(self.sequence_combo)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addStretch()
        row.addWidget(self.recipe_label)

        # Startup state: nothing to run yet.
        self.sequence_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)

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
        """A recipe is in: name it, offer its sequences, allow starting."""
        self.recipe_label.setText(f"{event.recipe_name} (v{event.recipe_version})")
        # blockSignals: refilling fires currentTextChanged per insertion, and
        # the assembler would refill the step table once per sequence.
        self.sequence_combo.blockSignals(True)
        self.sequence_combo.clear()
        for sequence in event.sequences:
            self.sequence_combo.addItem(sequence.sequence_name)
        self.sequence_combo.setCurrentText(event.main_sequence)
        self.sequence_combo.blockSignals(False)
        self.sequence_combo.setEnabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def show_run_started(self) -> None:
        """A run is on: nothing may change under it, only stopping is left."""
        self.open_button.setEnabled(False)
        self.sequence_combo.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def show_run_finished(self) -> None:
        """The run answered - however it went, the operator has the controls back."""
        self.open_button.setEnabled(True)
        self.sequence_combo.setEnabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
