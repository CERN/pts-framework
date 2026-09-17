# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The panel that shows recipe YAML: a step's whole sequence, or the whole recipe.

Two uses, one widget. The step table opens it beside the cursor with the
sequence a clicked step belongs to (a `Qt.ToolTip` window, closed by the table
when the pointer wanders off). The toolbar's recipe preview opens it under its
button with the whole recipe file (a `Qt.Popup` window, which Qt closes on any
click outside it, or on Esc).

Shown by `step_table.py` when a row is clicked and no run is in progress. It is
handed the sequence document as the recipe file has it and the lines of the
clicked step (`recipe/step_source.py`), so this widget knows nothing about
recipes: it shows a string, paints a band behind some of its lines and scrolls
them into view.

**Why a `Qt.ToolTip` window and not a `QToolTip`.** A real tooltip is Qt's to
size, time and dismiss, and it cannot hold a `QSyntaxHighlighter`. This is an
ordinary frame that borrows the tooltip *window flag*, which is what makes it a
top level that takes no focus, never steals the click and stays above the
window without being a dialog. Nothing here blocks the GUI thread (gui.md
section 3).

**Why it scrolls.** A sequence runs to dozens of lines, so the panel is capped
at `_MAX_SCREEN_FRACTION` of the screen's height and scrolls past that. The
step table keeps the panel open while the pointer is over it, so the wheel
reaches it; when it opens it is already scrolled to the clicked step.

Styling is written here at runtime rather than added to the two sheets in
`styles.py`, following `interaction_panel.py`: the blanket `QWidget` rule and
the `QPlainTextEdit` rule in both sheets reach this widget and would otherwise
paint it as a log panel. The syntax colours and the step band are
per-character and per-line formats, which no stylesheet can reach at all -
`set_dark()` is what carries a theme change into them.
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QTextCursor, QTextFormat
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from pypts.hmi.gui.palette import get_palette
from pypts.hmi.gui.yaml_highlighter import YamlHighlighter

#: The tallest the panel grows, as a share of the available screen height.
_MAX_SCREEN_FRACTION = 0.6

#: The widest line measured when sizing the panel. A longer line scrolls.
_MAX_COLUMNS = 100

#: How many lines above the clicked step stay in view when it is scrolled to.
_CONTEXT_LINES = 3

#: How far from the cursor the panel sits, so it never lands under the pointer.
_CURSOR_OFFSET_X = 16
_CURSOR_OFFSET_Y = 12

#: The gap kept between the panel and the edge of the screen.
_SCREEN_MARGIN = 8


class StepYamlPopup(QFrame):
    """A sequence's YAML, syntax coloured, one step picked out, beside the mouse."""

    def __init__(
        self,
        parent: QWidget | None = None,
        window_type: Qt.WindowType = Qt.WindowType.ToolTip,
        max_screen_fraction: float = _MAX_SCREEN_FRACTION,
    ) -> None:
        super().__init__(parent, window_type)
        self.setObjectName("stepYamlPopup")
        self._dark = False
        self._max_screen_fraction = max_screen_fraction
        #: The highlighted lines, 0-based and inclusive; (-1, -1) for none.
        self._step_lines = (-1, -1)
        self._offset = (_CURSOR_OFFSET_X, _CURSOR_OFFSET_Y)

        self.text_view = QPlainTextEdit()
        self.text_view.setObjectName("stepYamlPopupText")
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.highlighter = YamlHighlighter(self.text_view.document(), self._dark)

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(10, 8, 10, 8)
        self._column.addWidget(self.text_view)
        self.set_dark(False)

    # --- Showing ---------------------------------------------------------------

    def show_for(
        self,
        text: str,
        first_line: int,
        last_line: int,
        global_x: int,
        global_y: int,
        offset: tuple[int, int] = (_CURSOR_OFFSET_X, _CURSOR_OFFSET_Y),
    ) -> None:
        """
        Show `text` next to that screen position, kept on the screen, with lines
        `first_line`..`last_line` (0-based, inclusive) picked out and in view.
        A negative `first_line` picks nothing out and shows the top.

        `offset` is how far from the position the panel's corner sits: away from
        a cursor by default, so it never lands under the pointer.
        """
        if not text.strip():
            self.hide()
            return
        self._offset = offset
        self.text_view.setPlainText(text)
        self._step_lines = (first_line, last_line)
        self._paint_step_band()
        self._resize_to_contents(global_x, global_y)
        position = self._placed_at(global_x, global_y)
        self.move(position[0], position[1])
        self.show()
        self.raise_()
        # The application's stylesheet reaches a top level only once it is shown,
        # and it can take a few pixels the measurement did not know about. The
        # scroll bars then say by how much: take that room too, within the cap.
        if self._grow_to_fit(global_x, global_y):
            position = self._placed_at(global_x, global_y)
            self.move(position[0], position[1])
        self._scroll_to_step()

    def _paint_step_band(self) -> None:
        """A full-width band behind every line of the clicked step."""
        first, last = self._step_lines
        selections = []
        if first >= 0:
            band = QColor(get_palette(self._dark).yaml_step_highlight)
            document = self.text_view.document()
            for line in range(first, last + 1):
                block = document.findBlockByNumber(line)
                if not block.isValid():
                    break
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(band)
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selection.cursor = QTextCursor(block)
                selections.append(selection)
        self.text_view.setExtraSelections(selections)

    def _scroll_to_step(self) -> None:
        """
        Bring the clicked step into view with a few lines of context above it.

        A QPlainTextEdit without wrapping scrolls by whole lines, so the scroll
        value *is* the first visible line.
        """
        first, last = self._step_lines
        metrics = QFontMetrics(self.text_view.font())
        visible = self.text_view.viewport().height() // max(metrics.lineSpacing(), 1)
        target = 0
        # Only scroll when the step would not be in view from the top: a short
        # sequence keeps its header on screen.
        if last >= visible and first > _CONTEXT_LINES:
            target = first - _CONTEXT_LINES
        self.text_view.verticalScrollBar().setValue(target)

    def _grow_to_fit(self, global_x: int, global_y: int) -> bool:
        """
        Widen and heighten by what the scroll bars still hide, up to the caps.

        Returns True when the panel changed size. A scroll bar that is only
        there because the text is longer or wider than the caps allow stays.
        """
        metrics = QFontMetrics(self.text_view.font())
        hidden_lines = self.text_view.verticalScrollBar().maximum()
        hidden_pixels = self.text_view.horizontalScrollBar().maximum()
        extra_height = 0
        extra_width = 0
        if hidden_lines > 0:
            extra_height = hidden_lines * metrics.lineSpacing()
        if 0 < hidden_pixels <= metrics.horizontalAdvance("x") * 4:
            extra_width = hidden_pixels
        if not extra_height and not extra_width:
            return False

        max_height = self._max_height(global_x, global_y)
        new_view_height = min(self.text_view.height() + extra_height, max_height - self._chrome())
        new_view_width = self.text_view.width() + extra_width
        if new_view_height == self.text_view.height() and not extra_width:
            return False
        growth_h = new_view_height - self.text_view.height()
        growth_w = new_view_width - self.text_view.width()
        self.text_view.setFixedSize(new_view_width, new_view_height)
        self.setFixedSize(self.width() + growth_w, self.height() + growth_h)
        return True

    def _max_height(self, global_x: int, global_y: int) -> int:
        """The tallest the panel may be on the screen the cursor is on."""
        screen = self._screen_at(global_x, global_y)
        if screen is None:
            return 600
        return int(screen.availableGeometry().height() * self._max_screen_fraction)

    def _chrome(self) -> int:
        """The frame's own height around the text view."""
        margins = self._column.contentsMargins()
        return margins.top() + margins.bottom() + 8

    def _resize_to_contents(self, global_x: int, global_y: int) -> None:
        """Size to the text, capped by the screen: as big as it has to be, never more."""
        # The monospace font comes from the stylesheet, which only reaches the
        # widget once it is polished - measuring before that measures the
        # default font, and every long line is then cut short.
        self.ensurePolished()
        self.text_view.ensurePolished()
        # Measured in bold: the highlighter paints keys bold, and bold is wider.
        font = self.text_view.font()
        font.setBold(True)
        metrics = QFontMetrics(font)
        lines = self.text_view.toPlainText().split("\n")
        needed = max((metrics.horizontalAdvance(line) for line in lines), default=0)
        widest = min(needed, metrics.horizontalAdvance("x") * _MAX_COLUMNS)
        # The document keeps a margin inside the view on every side, and the view
        # keeps a little more around its viewport.
        inner = int(2 * self.text_view.document().documentMargin()) + 16
        text_height = metrics.lineSpacing() * len(lines) + inner
        if needed > widest:
            # A line longer than the cap scrolls sideways; the bar takes a line.
            text_height += self.text_view.horizontalScrollBar().sizeHint().height()

        max_height = self._max_height(global_x, global_y)
        margins = self._column.contentsMargins()
        chrome = self._chrome()
        scrollbar = self.text_view.verticalScrollBar().sizeHint().width()

        view_height = min(text_height, max_height - chrome)
        view_width = widest + inner
        if view_height < text_height:
            # The vertical bar takes room from the text; give it back.
            view_width += scrollbar
        self.text_view.setFixedSize(view_width, view_height)
        self.setFixedSize(view_width + margins.left() + margins.right() + 6, view_height + chrome)

    def _screen_at(self, global_x: int, global_y: int):
        """The screen the cursor is on, or the primary one."""
        screen = QGuiApplication.screenAt(QPoint(global_x, global_y))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen

    def _placed_at(self, global_x: int, global_y: int) -> tuple[int, int]:
        """
        Beside the cursor, flipped back over it rather than off the screen.

        A row near the right or the bottom edge would otherwise put half the
        panel outside the display - which on a bench with one screen means the
        half with the interesting keys in it.
        """
        x = global_x + self._offset[0]
        y = global_y + self._offset[1]
        # The screen the *cursor* is on, not the one the panel was last on:
        # the panel has not been moved yet when this is asked.
        screen = self._screen_at(global_x, global_y)
        if screen is None:
            return x, y

        area = screen.availableGeometry()
        if x + self.width() > area.right() - _SCREEN_MARGIN:
            x = global_x - self.width() - self._offset[0]
        if y + self.height() > area.bottom() - _SCREEN_MARGIN:
            y = area.bottom() - _SCREEN_MARGIN - self.height()
        x = max(x, area.left() + _SCREEN_MARGIN)
        y = max(y, area.top() + _SCREEN_MARGIN)
        return x, y

    # --- Theme -----------------------------------------------------------------

    def set_dark(self, dark: bool) -> None:
        """The frame from the stylesheet, the colours from the highlighter and the band."""
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
        self._paint_step_band()
