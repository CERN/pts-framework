# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
YAML syntax colouring for the step table's hover panel.

Adapted from the working highlighter in
`helper_applications/recipe_creator/customGUIModules.py`. **Copied, not
imported**: nothing in `hmi/` imports `helper_applications/` and this is not
the place to make that the first time - the dependency would run the wrong
way, from the framework into a helper app.

Two things changed in the move. The colours come from `palette.py` instead of
being written here, because no file in `hmi/gui/` may hold a hex literal and a
unit test enforces it; and the rules were tightened for what this panel
actually shows. A rendered step mapping (`recipe/step_source.py`) is mostly
*unquoted* scalars - `module: example_tests.py`, `step_name: Add numbers` - and
the original's rules coloured the key and left every one of those values plain.

The rules are applied in order and a later one overwrites an earlier one, which
is the whole precedence mechanism. Broadest first: `string` paints everything
after a colon - an unquoted scalar is a string in YAML, so one rule covers
`module: example_tests.py` and `value: 'Hello'` alike. Then `key` and
`punctuation` take back what is structure, including inside a flow mapping like
`{type: equals, value: 5}`, then number/boolean/null repaint the scalars that
are really those, and `comment` runs last so it wins over all of them.
"""

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from pypts.hmi.gui.palette import get_palette

#: token name -> the pattern that finds it. Order matters; see the module
#: docstring. The token names are the `yaml_*` fields of `Palette`, minus the
#: prefix, so a rule cannot name a colour that does not exist.
_RULES: tuple[tuple[str, str], ...] = (
    # Everything after a colon, quoted or not. An unquoted scalar is a string
    # in YAML, so this is the one value colour and the rules below only repaint
    # the values that are something more specific.
    ("string", r"(?<=:)\s+\S.*$"),
    # A key sits before a colon: at the start of a line, after the list dash
    # that opens a step, or after a `{` or `,` inside a flow mapping. The
    # excluded characters are what stops it swallowing a whole flow mapping.
    ("key", r"(?:^\s*(?:-\s+)?|[{,]\s*)[^:\n{}\[\],]+(?=:)"),
    # The structure itself: the list dash, and the braces and commas of
    # `{type: equals, value: 5}`.
    ("punctuation", r"^\s*-|[{}\[\],]"),
    ("number", r"(?<=:\s)-?\d+(?:\.\d+)?\s*(?=[,}\]]|$)"),
    ("boolean", r"(?<=:\s)(?:true|false|True|False|yes|no|on|off)\s*(?=[,}\]]|$)"),
    ("null", r"(?<=:\s)(?:null|Null|NULL|~)\s*(?=[,}\]]|$)"),
    ("comment", r"#.*$"),
)


class YamlHighlighter(QSyntaxHighlighter):
    """Colours a YAML document from the palette, and re-colours on a theme flip."""

    def __init__(self, document: QTextDocument, dark: bool = False) -> None:
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self.set_dark(dark)

    def set_dark(self, dark: bool) -> None:
        """
        Rebuild every format for the new theme and repaint what is on screen.

        The same contract as `LogPanel` and the step table's verdict chips: a
        `QTextCharFormat` is baked into the document when the text is written,
        so a stylesheet swap does nothing for it and the theme change has to
        come through here (gui.md section 10).
        """
        palette = get_palette(dark)
        self._rules = []
        for token, pattern in _RULES:
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(getattr(palette, f"yaml_{token}")))
            if token == "key":
                text_format.setFontWeight(QFont.Weight.Bold)
            elif token == "comment":
                text_format.setFontItalic(True)
            self._rules.append((QRegularExpression(pattern), text_format))
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt's own name
        for pattern, text_format in self._rules:
            matches = pattern.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)
