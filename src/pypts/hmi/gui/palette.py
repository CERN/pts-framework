# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Every colour the GUI uses, in one file.

Nothing else in `hmi/gui/` may write a hex literal. `styles.py` builds the two
stylesheets out of these tokens, and the widgets that colour something
themselves - the verdict chips in the step table, the level prefixes in the log
panel, the toolbar icons - read them from here too. Changing how the GUI looks is
therefore an edit to this file and to nothing else.

Three kinds of colour live here, and the difference matters:

* **`Palette`** - what changes with the theme. Two instances, `LIGHT` and `DARK`,
  with the same field names, so every token exists in both. `get_palette(dark)`
  picks one.
* **The verdict chips** (`LIGHT_VERDICTS` / `DARK_VERDICTS`, reached through
  `get_palette(dark).verdicts`) - PASS/FAIL/DONE/SKIP/ERROR/STOP plus PENDING and
  RUNNING. **The hue is fixed and the value is themed**: an operator reads a bench
  screen by colour, so green stays PASS and red stays FAIL in both themes, but a
  pastel fill that reads as a soft chip on white glares on charcoal - so on dark
  the fill goes dark and the text carries the colour instead.
* **`LOG_LEVEL_COLORS` and the placeholder constants** - genuinely theme-
  independent. They are text or artwork with no fill behind them to compete with.

Run this file to see the whole thing on screen:

    python -m pypts.hmi.gui.palette

which opens a window with every token swatched, named and labelled with its hex,
so a change can be judged before it is committed.
"""

from dataclasses import dataclass, fields

# --- the chips ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chip:
    """A background plus the text colour that stays readable on it."""

    background: str
    text: str


#: Verdict -> chip on a light background, keyed by `ResultType.name` plus the two
#: states a step is in before it has one. Pastel fills with dark text, inherited
#: from the old GUI (`old_code/utils.py get_step_result_colors`).
LIGHT_VERDICTS: dict[str, Chip] = {
    "PASS": Chip("#C8E6C9", "#1B4F24"),
    "FAIL": Chip("#F28B82", "#7B0000"),
    "DONE": Chip("#B2EBF2", "#004D52"),
    "SKIP": Chip("#FFF9C4", "#C49000"),
    "ERROR": Chip("#FFCC80", "#BF360C"),
    "STOP": Chip("#D3D3D3", "#4B4B4B"),
    "PENDING": Chip("#E8EAF0", "#555555"),
    "RUNNING": Chip("#DBEAFE", "#1D4ED8"),
}

#: The same verdicts on a dark background. **The hue is what an operator reads,
#: so the hue is what stays**: green is still PASS, red still FAIL. What changes
#: is the value - a pastel fill that reads as a soft chip on white glares on
#: charcoal, so the fill goes dark and the text takes over the colour.
DARK_VERDICTS: dict[str, Chip] = {
    "PASS": Chip("#1E3D26", "#8FD69B"),
    "FAIL": Chip("#4A2320", "#F2A79E"),
    "DONE": Chip("#123C42", "#8AD3DD"),
    "SKIP": Chip("#3E3A1C", "#E3D28C"),
    "ERROR": Chip("#48331A", "#F0B67C"),
    "STOP": Chip("#3A3A3A", "#C4C4C4"),
    "PENDING": Chip("#33383D", "#A6AFB9"),
    "RUNNING": Chip("#1C2E4A", "#8FB8F0"),
}

#: For a verdict nobody mapped - white on black, visibly wrong on purpose.
UNKNOWN_VERDICT = Chip("#FFFFFF", "#000000")

#: Log level -> the colour of its prefix in the log panel. Not themed: these are
#: text on the panel background, with no fill to compete with, and the six are
#: already mid-tone enough to read on either.
LOG_LEVEL_COLORS: dict[str, str] = {
    "INFO": "#6abf69",
    "DEBUG": "#6897bb",
    "WARNING": "#FFCC80",
    "WARN": "#FFCC80",
    "ERROR": "#F28B82",
    "CRITICAL": "#ff7c9c",
}

#: The placeholder drawn when an image a recipe asked for cannot be loaded.
PLACEHOLDER_FILL = "#eef3fb"
PLACEHOLDER_BORDER = "#c7d4ea"
PLACEHOLDER_TEXT = "#5f7898"


# --- the themed tokens --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Palette:
    """One theme. Every field is a CSS hex colour."""

    #: What the theme is called, for the showcase and the log.
    name: str

    # Brand. CERN blue is the identity and does not change with the theme;
    # what changes is how much of it a dark background can carry.
    brand: str
    brand_dark: str
    brand_accent: str
    #: Selected-tab text, and the accent a dark theme uses where light uses
    #: `brand_accent` - a saturated blue is unreadable on charcoal.
    accent_text: str
    tab_text: str

    # Surfaces, from the back of the window forwards.
    window: str
    menu_background: str
    toolbar_background: str
    table_background: str
    row_alternate: str
    header_background: str
    status_background: str
    panel_background: str
    log_background: str

    # Text.
    text: str
    text_muted: str
    text_on_brand: str
    section_label: str
    toolbutton: str
    toolbutton_disabled: str
    log_text: str
    log_text_muted: str

    # Lines.
    border: str
    header_underline: str
    button_border: str

    # Interaction.
    menu_highlight: str
    toolbutton_hover: str
    button_background: str
    button_hover: str
    selection_background: str
    selection_text: str

    # The stop button, and anything else that has to look like a refusal.
    danger: str
    danger_background: str
    danger_border: str

    # Scrollbars.
    scroll_track: str
    scroll_handle: str
    scroll_handle_hover: str
    scroll_handle_pressed: str

    #: The lines *inside* a table. Separate from `border`, which is the frame
    #: around it: a frame may be quiet, but a grid that cannot be seen stops
    #: being a grid.
    grid_line: str

    # The toolbar's action icons. Green go, orange hold, red stop - the bench
    # convention, and the one thing an operator finds without reading. Themed
    # because a dark green that reads as "go" on white disappears on charcoal.
    icon_start: str
    icon_pause: str
    icon_stop: str
    icon_disabled: str

    # The step table's hover panel, which shows one step's YAML syntax
    # coloured (step_yaml_popup.py). Themed rather than shared with
    # LOG_LEVEL_COLORS: these are six colours side by side on one small
    # surface, and the light theme's greys for a comment or a null go muddy
    # on charcoal. `yaml_punctuation` is the structural characters - the
    # colons, dashes and braces - which are deliberately quiet.
    yaml_key: str
    yaml_string: str
    yaml_number: str
    yaml_boolean: str
    yaml_null: str
    yaml_comment: str
    yaml_punctuation: str

    #: What the CERN logo is recoloured to, or None to draw the artwork as it
    #: is. The file is a dark blue line drawing: correct on white, nearly
    #: invisible on charcoal, so the dark theme tints it.
    logo_tint: str | None

    #: The verdict chips, LIGHT_VERDICTS or DARK_VERDICTS.
    verdicts: dict[str, Chip]


LIGHT = Palette(
    name="Light",
    brand="#0033A0",
    brand_dark="#002080",
    brand_accent="#005BAC",
    accent_text="#005BAC",
    tab_text="#B3CFF0",
    window="#f5f7fa",
    menu_background="#ffffff",
    toolbar_background="#F8FAFC",
    table_background="#ffffff",
    row_alternate="#fafbfe",
    header_background="#F0F4FA",
    status_background="#F0F4FA",
    panel_background="#F0F4FA",
    log_background="#f5f5f5",
    text="#1a1a2e",
    text_muted="#718096",
    text_on_brand="#ffffff",
    section_label="#94a3b8",
    toolbutton="#424242",
    toolbutton_disabled="#BDBDBD",
    log_text="#333333",
    log_text_muted="#555555",
    border="#e2e8f0",
    header_underline="#B3CFF0",
    button_border="#B3CFF0",
    menu_highlight="#E3ECF9",
    toolbutton_hover="#E3ECF9",
    button_background="#E3ECF9",
    button_hover="#c8d8f4",
    selection_background="#EEF5FF",
    selection_text="#1a1a2e",
    danger="#CC0000",
    danger_background="#FFEBEE",
    danger_border="#FFCDD2",
    scroll_track="#edf2f7",
    scroll_handle="#b7c7db",
    scroll_handle_hover="#90a9c9",
    scroll_handle_pressed="#6e8eb7",
    # Qt's own default grid, kept exactly: making the grid a token was a dark
    # theme fix, and the light theme was not asked to change. `border` (#e2e8f0)
    # is the alternative if a bluer, softer grid is ever wanted.
    grid_line="#d8d8d8",
    icon_start="#1B5E20",
    icon_pause="#E65100",
    icon_stop="#CC0000",
    icon_disabled="#BDBDBD",
    yaml_key="#0B5394",
    yaml_string="#1B7F4B",
    yaml_number="#8C4A00",
    yaml_boolean="#8B2E8B",
    yaml_null="#7A7A7A",
    yaml_comment="#6B7A8C",
    yaml_punctuation="#94a3b8",
    logo_tint=None,
    verdicts=LIGHT_VERDICTS,
)

DARK = Palette(
    name="Dark",
    brand="#0033A0",
    # The dark theme's "pressed" border is the accent, not a darker brand:
    # #002080 on charcoal is a hole in the screen.
    brand_dark="#005BAC",
    brand_accent="#005BAC",
    accent_text="#7AABDF",
    tab_text="#B3CFF0",
    window="#2b2b2b",
    menu_background="#2b2b2b",
    toolbar_background="#232323",
    table_background="#3c3f41",
    row_alternate="#404346",
    header_background="#2b2b2b",
    status_background="#1e1e1e",
    panel_background="#1e1e1e",
    log_background="#1e1e1e",
    text="#f0f0f0",
    text_muted="#AFBAC6",
    text_on_brand="#ffffff",
    section_label="#AFBAC6",
    toolbutton="#f0f0f0",
    toolbutton_disabled="#555555",
    log_text="#DEE4EB",
    log_text_muted="#D5DBE3",
    border="#4d565f",
    # Eight hex digits: the last two are alpha. A solid line here is louder
    # than the header it underlines.
    header_underline="#005BAC44",
    button_border="#5a5a5a",
    menu_highlight="#444444",
    toolbutton_hover="#3a3a3a",
    button_background="#3c3f41",
    button_hover="#5c5c5c",
    selection_background="#1a2840",
    selection_text="#f0f0f0",
    danger="#F28B82",
    danger_background="#3a1a1a",
    danger_border="#5a2a2a",
    scroll_track="#232a33",
    scroll_handle="#55697f",
    scroll_handle_hover="#6b829b",
    scroll_handle_pressed="#85a2c4",
    grid_line="#4d565f",
    icon_start="#57C25E",
    icon_pause="#FFA726",
    icon_stop="#EF5350",
    icon_disabled="#6E7681",
    yaml_key="#9CC3F0",
    yaml_string="#6abf69",
    yaml_number="#F0A868",
    yaml_boolean="#D6A2E8",
    yaml_null="#9AA5B1",
    yaml_comment="#8894A3",
    yaml_punctuation="#7D8894",
    logo_tint="#9CC3F0",
    verdicts=DARK_VERDICTS,
)


def get_palette(dark: bool = False) -> Palette:
    """The palette for the theme in use. The one accessor every widget calls."""
    return DARK if dark else LIGHT


#: Fields of Palette that are not a single colour, so nothing may treat them as
#: one: the theme's own name, and the chip table (shown as chips, not swatches).
NON_COLOUR_FIELDS = ("name", "verdicts")


def token_names() -> list[str]:
    """Every themed colour token, in declaration order."""
    return [field.name for field in fields(Palette) if field.name not in NON_COLOUR_FIELDS]


# --- the showcase -------------------------------------------------------------
#
# Everything below this line exists only for `python -m pypts.hmi.gui.palette`.
# Nothing in the framework imports it, and it may import PySide6 freely because
# it only ever runs when someone asks to look at the colours.


#: Width of one swatch. Fixed, and the labels are fixed to it as well, so a long
#: token name cannot stretch its grid column and push the row off the window.
_SWATCH_WIDTH = 158


def _swatch(color: str, label: str, sublabel: str, dark: bool):
    """One rectangle of colour with its name and hex under it."""
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

    palette = get_palette(dark)

    box = QFrame()
    box.setFixedSize(_SWATCH_WIDTH, 44)
    box.setStyleSheet(
        f"background-color: {color}; border: 1px solid {palette.border}; border-radius: 4px;"
    )

    name = QLabel(label)
    name.setFixedWidth(_SWATCH_WIDTH)
    name.setWordWrap(True)
    name.setStyleSheet(f"color: {palette.text}; font-size: 11px; font-weight: 600;")

    value = QLabel(sublabel)
    value.setFixedWidth(_SWATCH_WIDTH)
    value.setStyleSheet(f"color: {palette.text_muted}; font-size: 10px;")

    holder = QWidget()
    holder.setFixedWidth(_SWATCH_WIDTH)
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    column.addWidget(box)
    column.addWidget(name)
    column.addWidget(value)
    return holder


def _chip_row(chips: dict, dark: bool):
    """The verdict chips, drawn as the step table draws them."""
    from PySide6.QtWidgets import QHBoxLayout, QLabel

    row = QHBoxLayout()
    row.setSpacing(8)
    for chip_name, chip in chips.items():
        label = QLabel(chip_name)
        label.setFixedSize(96, 34)
        label.setStyleSheet(
            f"background-color: {chip.background}; color: {chip.text};"
            f"font-size: 12px; font-weight: 600; qproperty-alignment: AlignCenter;"
            f"border-radius: 4px;"
        )
        row.addWidget(label)
    row.addStretch()
    return row


def _theme_page(dark: bool):
    """One scrollable page: every token of one theme, grouped as declared."""
    from PySide6.QtWidgets import (
        QGridLayout,
        QLabel,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )

    palette = get_palette(dark)
    page = QWidget()
    page.setStyleSheet(f"background-color: {palette.window};")
    column = QVBoxLayout(page)
    column.setContentsMargins(16, 16, 16, 16)
    column.setSpacing(14)

    def heading(text: str):
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {palette.accent_text}; font-size: 13px; font-weight: 700;"
        )
        return label

    column.addWidget(heading(f"{palette.name} theme — Palette tokens"))
    grid = QGridLayout()
    grid.setColumnStretch(5, 1)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(10)
    for position, token in enumerate(token_names()):
        value = getattr(palette, token)
        if not isinstance(value, str):
            # `verdicts` is the chip table, shown as chips below; `logo_tint` is
            # None in the light theme, where the artwork is drawn untouched.
            value = palette.window
            label = f"{token} (none)"
        else:
            label = token
        grid.addWidget(_swatch(value, label, str(getattr(palette, token)), dark),
                       position // 5, position % 5)
    column.addLayout(grid)

    column.addWidget(heading("Verdict chips — same hue in both themes, themed value"))
    column.addLayout(_chip_row(palette.verdicts, dark))

    column.addWidget(heading("Log levels and the image placeholder — not themed"))
    extras = QGridLayout()
    extras.setColumnStretch(5, 1)
    extras.setHorizontalSpacing(12)
    extras.setVerticalSpacing(10)
    others = [(f"LOG {level}", color) for level, color in LOG_LEVEL_COLORS.items()]
    others += [
        ("PLACEHOLDER_FILL", PLACEHOLDER_FILL),
        ("PLACEHOLDER_BORDER", PLACEHOLDER_BORDER),
        ("PLACEHOLDER_TEXT", PLACEHOLDER_TEXT),
    ]
    for position, (label, value) in enumerate(others):
        extras.addWidget(_swatch(value, label, value, dark), position // 5, position % 5)
    column.addLayout(extras)
    column.addStretch()

    scroller = QScrollArea()
    scroller.setWidget(page)
    scroller.setWidgetResizable(True)
    return scroller


def show_palette() -> int:
    """Open the showcase window. Returns the Qt exit code."""
    import sys

    from PySide6.QtWidgets import QApplication, QTabWidget

    app = QApplication(sys.argv)
    tabs = QTabWidget()
    tabs.setWindowTitle("pypts — GUI colour palette")
    tabs.addTab(_theme_page(dark=False), "Light")
    tabs.addTab(_theme_page(dark=True), "Dark")
    tabs.resize(1040, 760)
    tabs.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(show_palette())
