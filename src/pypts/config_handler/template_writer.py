# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Writing config.ini without throwing the comments away.

`configparser.write()` re-serialises from the parsed structure, and the parsed
structure has no comments in it - so a single write turns a documented file into
a bare list of key = value. That matters here more than it usually would: this
file is meant to be opened and edited by hand, by someone setting up a bench,
and the comments are how they know what `theme` or `timeout_s` mean.

So writing goes through this module instead, in one of two ways:

- `render()` builds a whole file from the shipped template: its comments, blank
  lines and ordering, with the given values filled in. Used only when there is
  no file yet, and by `restore_default()`, which starts over on purpose.
- `replace_value()` changes one value in the user's existing file. The file is
  the user's from the moment it exists, so a change edits that file - one line,
  in its own section - and never rebuilds it from the template. Every other
  line, a key the user added by hand included, stays exactly as it was.

Both are line based, which keeps the output diffable: change one value and
`git diff` shows one line.
"""

import re
from pathlib import Path

#: A section header, e.g. `[hardware.dmm1]`.
SECTION_RE = re.compile(r"^\s*\[(?P<name>[^]]+)\]\s*$")

#: A key assignment, e.g. `level = INFO`. Only `=` is accepted as the separator;
#: configparser also allows `:`, but nothing pypts writes uses it, and accepting
#: it here would make a value containing a colon ambiguous.
KEY_RE = re.compile(r"^(?P<key>[^:=\s][^:=]*?)\s*=(?P<value>.*)$")


def render(template_text: str, values: dict[str, dict[str, str]]) -> str:
    """
    Produce the text of a new config file: the template's comments and layout,
    the caller's values.

    Args:
        template_text: contents of config_template.ini.
        values: section -> key -> value, as strings, exactly as they should
            appear in the file.

    Returns:
        The full file contents, newline terminated.

    A key that the template declares but `values` omits keeps the template's own
    value.
    """
    lines: list[str] = []
    current_section = ""

    for line in template_text.splitlines():
        section_match = SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("name")
            lines.append(line)
            continue

        key_match = KEY_RE.match(line)
        if key_match and not line.lstrip().startswith(("#", ";")):
            key = key_match.group("key").strip().lower()
            value = values.get(current_section, {}).get(key)
            if value is None:
                value = key_match.group("value").strip()
            lines.append(f"{key} = {value}".rstrip())
            continue

        lines.append(line)

    return "\n".join(lines).rstrip("\n") + "\n"


def replace_value(text: str, section: str, key: str, value: str) -> str:
    """
    The same file with one value changed, and nothing else.

    Args:
        text: the current contents of the config file.
        section: the section the key is in, spelled as in its header.
        key: the key whose value changes. Matched regardless of case, the way
            configparser reads it.
        value: the new value, as it should appear in the file.

    Returns:
        `text` with that one line rewritten as `<key as written> = <value>`.

    Raises:
        KeyError: the section has no such key. Only an existing key is ever
            changed - this never adds a line.
    """
    lines = text.splitlines(keepends=True)
    current_section = ""

    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        section_match = SECTION_RE.match(content)
        if section_match:
            current_section = section_match.group("name")
            continue
        if current_section != section:
            continue
        if content.lstrip().startswith(("#", ";")):
            continue

        key_match = KEY_RE.match(content)
        if key_match and key_match.group("key").strip().lower() == key.lower():
            line_ending = line[len(content):]
            written_key = key_match.group("key").rstrip()
            lines[index] = f"{written_key} = {value}".rstrip() + line_ending
            return "".join(lines)

    raise KeyError(f"[{section}] has no key {key!r} in the file")


def write(path: Path, text: str) -> None:
    """
    Write the file, creating its directory if needed.

    Written to a temporary file in the same directory and moved into place, so
    an interrupted write cannot leave a half-written config behind - the file
    the framework needs before it can even open its log.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
