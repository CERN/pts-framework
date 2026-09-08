# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The console is ASCII, and stays ASCII.

`print()` and the Logger's stdout handler encode with whatever the locale says.
On a bench whose locale is C that is plain ASCII, and one non-ASCII character
then raises UnicodeEncodeError inside the handler. There is no stream-level net
under that any more - this test *is* the guarantee, and it works by keeping the
strings out of the source in the first place, which is the half that can simply
be got right.

It reads the source rather than running anything, because the failure it guards
against is invisible on the machine where the line is written: a developer on a
UTF-8 terminal sees an em-dash, and the technician on a C-locale bench loses
the record that line was supposed to be.

**Log calls and `print()` only.** Qt widget text is deliberately not checked -
the Debug Monitor's window titles and column placeholders are full of em-dashes
and arrows, they never touch a byte stream, and Qt has handled Unicode natively
since long before this project existed. Narrowing to what actually reaches a
console is what keeps this test from being a blanket ban nobody would keep.

Scope is the framework: `old_code/` is frozen and `helper_applications/` is
pre-refactor and ported in Phase 6 - the same line ruff and mypy already draw.
`recipe_verificator/verify_recipe.py` prints emoji from its `__main__` and would
fail today; that is recorded as a roadmap TODO rather than fixed here.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "pypts"

#: Excluded wholesale, and why. See the module docstring.
EXCLUDED_DIRS = ("old_code", "helper_applications")

#: The logging methods. `log` is the framework's root logger, exported from
#: pypts.logger.log; `logger` catches a module that bound its own name to one.
LOG_OBJECTS = ("log", "logger", "logging")
LOG_METHODS = ("debug", "info", "warning", "error", "critical", "exception")


def framework_sources() -> list[pathlib.Path]:
    """Every framework .py file, in a stable order so a failure is reproducible."""
    return sorted(
        path
        for path in SRC.rglob("*.py")
        if not any(part in EXCLUDED_DIRS for part in path.relative_to(SRC).parts)
    )


def is_console_call(node: ast.Call) -> bool:
    """True for `print(...)` and for `log.info(...)` and its siblings."""
    if isinstance(node.func, ast.Name):
        return node.func.id == "print"
    if isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS:
        target = node.func.value
        return isinstance(target, ast.Name) and target.id in LOG_OBJECTS
    return False


def literal_text(node: ast.AST) -> list[tuple[int, str]]:
    """
    Every string literal inside one call argument, with its line number.

    An f-string is an ast.JoinedStr whose literal halves are Constants, so this
    walks the argument rather than only looking at its top level: the text
    around a substitution is written by us and is checked, the substituted value
    is not and cannot be.
    """
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.append((child.lineno, child.value))
    return found


def non_ascii_console_strings(path: pathlib.Path) -> list[str]:
    """Every offending literal in one file, formatted for the assertion message."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    offences = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_console_call(node):
            continue
        for line_number, text in literal_text(node):
            if text.isascii():
                continue
            stray = sorted({character for character in text if not character.isascii()})
            offences.append(
                f"{path.name}:{line_number}: {''.join(stray)!r} in {text!r}"
            )
    return offences


@pytest.mark.parametrize("path", framework_sources(), ids=lambda path: path.name)
def test_console_strings_are_ascii(path):
    """
    A log line or a print() that is not ASCII cannot be shown on a C-locale
    console: the handler raises UnicodeEncodeError and the record is lost.

    Write the ASCII form: `->` not an arrow, `-` not an em-dash, `...` not an
    ellipsis. If a real character is genuinely needed, it belongs somewhere that
    is not a byte stream - a Qt widget, or the run log file, which is UTF-8.
    """
    offences = non_ascii_console_strings(path)

    assert not offences, "Non-ASCII text on its way to the console:\n" + "\n".join(offences)


def test_the_scan_finds_something_to_scan():
    """
    The guard on the guard. Every assertion above passes trivially if the file
    list is empty, which is exactly what a moved directory or a renamed package
    would do to it.
    """
    sources = framework_sources()

    assert len(sources) > 20
    assert any(path.name == "core.py" for path in sources)


def test_the_scan_catches_a_planted_offence(tmp_path):
    """
    And the guard on *that*: proof the walk actually inspects log calls and
    print() rather than passing because it inspected nothing.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        'log.info("The File → Open Recent list.")\n'
        'print("plain ascii is fine")\n'
        'widget.setWindowTitle("Monitor — not checked, never printed")\n',
        encoding="utf-8",
    )

    offences = non_ascii_console_strings(planted)

    assert len(offences) == 1
    assert "→" in offences[0]
