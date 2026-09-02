# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The panel that appears beside the cursor with one step's YAML in it.

Shown by `step_table.py` while the pointer rests on a row and no run is in
progress; the text it shows is rendered by `recipe/step_source.py`, so this
widget knows nothing about recipes - it is handed a string.

**Why a `Qt.ToolTip` window and not a `QToolTip`.** A real tooltip is Qt's to
size, time and dismiss, and it cannot hold a `QSyntaxHighlighter`. This is an
ordinary frame that borrows the tooltip *window flag*, which is what makes it a
top level that takes no focus, never steals the click and stays above the
window without being a dialog. Nothing here blocks the GUI thread (gui.md
section 3).

**Why the text is truncated rather than scrolled.** The panel sits under the
pointer, and the pointer is over the table: a wheel event goes to the table
beneath, so a scroll bar in here would be decoration. A fragment longer than
`_MAX_LINES` is cut and given a final `# ... N more lines` line, which the
highlighter paints as the comment it is. Rendered step mappings run five to
fifteen lines, so this is the guard for a pathological recipe, not the norm.

Styling is written here at runtime rather than added to the two sheets in
`styles.py`, following `interaction_panel.py`: the blanket `QWidget` rule and
the `QPlainTextEdit` rule in both sheets reach this widget and would otherwise
paint it as a log panel. The syntax colours are per-character formats, which no
stylesheet can reach at all - `set_dark()` is what carries a theme change into
them.
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QVBoxLayout, QWidget

from pypts.hmi.gui.palette import get_palette
from pypts.hmi.gui.yaml_highlighter import YamlHighlighter

#: How much of a fragment is shown before it is cut. See the module docstring.
_MAX_LINES = 30

#: The widest line measured when sizing the panel. A longer line wraps.
_MAX_COLUMNS = 90

#: How far from the cursor the panel sits, so it never lands under the pointer.
_CURSOR_OFFSET_X = 16
_CURSOR_OFFSET_Y = 12

#: The gap kept between the panel and the edge of the screen.
_SCREEN_MARGIN = 8


class StepYamlPopup(QFrame):
    """One step's YAML, syntax coloured, beside the mouse."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setObjectName("stepYamlPopup")
        self._dark = False

        self.text_view = QPlainTextEdit()
        self.text_view.setObjectName("stepYamlPopupText")
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.highlighter = YamlHighlighter(self.text_view.document(), self._dark)

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(10, 8, 10, 8)
        self._column.addWidget(self.text_view)
        self.set_dark(False)

    # --- Showing ---------------------------------------------------------------

    def show_for(self, text: str, global_x: int, global_y: int) -> None:
        """Show `text` next to that screen position, kept on the screen."""
        if not text.strip():
            self.hide()
            return
        self.text_view.setPlainText(_capped(text))
        self._resize_to_contents()
        position = self._placed_at(global_x, global_y)
        self.move(position[0], position[1])
        self.show()
        self.raise_()

    def _resize_to_contents(self) -> None:
        """Size to the text: the panel is as big as it has to be, never more."""
        metrics = QFontMetrics(self.text_view.font())
        lines = self.text_view.toPlainText().split("\n")
        widest = max((metrics.horizontalAdvance(line) for line in lines), default=0)
        widest = min(widest, metrics.horizontalAdvance("x") * _MAX_COLUMNS)
        margins = self._column.contentsMargins()
        width = widest + margins.left() + margins.right() + 12
        height = metrics.lineSpacing() * len(lines) + margins.top() + margins.bottom() + 8
        self.text_view.setFixedSize(widest + 6, metrics.lineSpacing() * len(lines) + 4)
        self.setFixedSize(width, height)

    def _placed_at(self, global_x: int, global_y: int) -> tuple[int, int]:
        """
        Beside the cursor, flipped back over it rather than off the screen.

        A row near the right or the bottom edge would otherwise put half the
        panel outside the display - which on a bench with one screen means the
        half with the interesting keys in it.
        """
        x = global_x + _CURSOR_OFFSET_X
        y = global_y + _CURSOR_OFFSET_Y
        # The screen the *cursor* is on, not the one the panel was last on:
        # the panel has not been moved yet when this is asked.
        screen = QGuiApplication.screenAt(QPoint(global_x, global_y))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return x, y

        area = screen.availableGeometry()
        if x + self.width() > area.right() - _SCREEN_MARGIN:
            x = global_x - self.width() - _CURSOR_OFFSET_X
        if y + self.height() > area.bottom() - _SCREEN_MARGIN:
            y = global_y - self.height() - _CURSOR_OFFSET_Y
        x = max(x, area.left() + _SCREEN_MARGIN)
        y = max(y, area.top() + _SCREEN_MARGIN)
        return x, y

    # --- Theme -----------------------------------------------------------------

    def set_dark(self, dark: bool) -> None:
        """The frame from the stylesheet, the syntax colours from the highlighter."""
        self._dark = dark
        palette = get_palette(dark)
        self.setStyleSheet(
            "QFrame#stepYamlPopup {"
            f"background-color:{palette.panel_background};"
            f"border:1px solid {palette.border};"
            "border-radius:6px;"
            "}"
        )
        self.text_view.setStyleSheet(
            "QPlainTextEdit#stepYamlPopupText {"
            "background-color:transparent; border:none;"
            "font-family:'Consolas','Courier New',monospace; font-size:12px;"
            f"color:{palette.text};"
            "}"
        )
        self.highlighter.set_dark(dark)


def _capped(text: str) -> str:
    """At most _MAX_LINES lines, with a comment saying what was left out."""
    lines = text.split("\n")
    if len(lines) <= _MAX_LINES:
        return text
    hidden = len(lines) - _MAX_LINES
    shown = lines[:_MAX_LINES]
    shown.append(f"# ... {hidden} more lines")
    return "\n".join(shown)
