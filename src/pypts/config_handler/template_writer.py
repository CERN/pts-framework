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

So writing goes through this module instead. The shipped template is the layout:
its comments, blank lines and ordering are copied out verbatim, and only the
value to the right of each `=` is replaced with the current one. Anything the
user added that the template does not know about - a second `[hardware.*]`
section, most likely - is appended afterwards, so nothing is ever lost.

The parsing here is deliberately line based. It has to handle exactly the file
it wrote itself, and a line-based rewrite keeps the output diffable: change one
value and `git diff` shows one line.
"""

import re
from pathlib import Path

#: A section header, e.g. `[hardware.dmm1]`.
SECTION_RE = re.compile(r"^\s*\[(?P<name>[^]]+)\]\s*$")

#: A key assignment, e.g. `level = INFO`. Only `=` is accepted as the separator;
#: configparser also allows `:`, but nothing pypts writes uses it, and accepting
#: it here would make a value containing a colon ambiguous.
KEY_RE = re.compile(r"^(?P<key>[^:=\s][^:=]*?)\s*=(?P<value>.*)$")

#: Heading put above sections that were in the live config but not in the
#: template - user-added hardware, almost always.
EXTRA_SECTIONS_HEADER = [
    "",
    "# ---------------------------------------------------------------------------",
    "# Sections below were added to this file rather than coming from the template,",
    "# so pypts has no comments to restore for them. They are preserved as written.",
    "# ---------------------------------------------------------------------------",
]


def render(template_text: str, values: dict[str, dict[str, str]]) -> str:
    """
    Produce the text of a config file: the template's comments and layout, the
    caller's values.

    Args:
        template_text: contents of config_template.ini.
        values: section -> key -> value, as strings, exactly as they should
            appear in the file.

    Returns:
        The full file contents, newline terminated.

    A key that the template declares but `values` omits keeps the template's own
    value, so a caller may pass only what it wants to change.
    """
    lines: list[str] = []
    seen: dict[str, set[str]] = {}
    current_section = ""
    skipping_continuation = False

    for line in template_text.splitlines():
        section_match = SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("name")
            seen.setdefault(current_section, set())
            skipping_continuation = False
            lines.append(line)
            continue

        key_match = KEY_RE.match(line)
        if key_match and not line.lstrip().startswith(("#", ";")):
            key = key_match.group("key").strip().lower()
            seen.setdefault(current_section, set()).add(key)
            value = values.get(current_section, {}).get(key)
            if value is None:
                value = key_match.group("value").strip()
            lines.append(f"{key} = {value}".rstrip())
            # A value continued on following indented lines has just been
            # replaced by a single-line one; drop what is left of the old value
            # rather than emitting it as if it were still part of the file.
            skipping_continuation = True
            continue

        # Indented text directly after a key is the remainder of a multi-line
        # value. Comments and blank lines end that run and are kept.
        is_continuation = line[:1].isspace() and line.strip() != ""
        if skipping_continuation and is_continuation:
            continue
        skipping_continuation = False
        lines.append(line)

    lines.extend(_render_extras(values, seen))

    return "\n".join(lines).rstrip("\n") + "\n"


def _render_extras(values: dict[str, dict[str, str]], seen: dict[str, set[str]]) -> list[str]:
    """
    Sections and keys present in `values` but absent from the template.

    Keys of a known section are appended to the end of the file rather than to
    their section, which is not pretty but is honest: it makes an unexpected key
    visible instead of hiding it among the documented ones.
    """
    extra_sections = {
        section: keys for section, keys in values.items() if section not in seen
    }
    extra_keys = {
        section: {key: value for key, value in keys.items() if key not in seen[section]}
        for section, keys in values.items()
        if section in seen
    }
    extra_keys = {section: keys for section, keys in extra_keys.items() if keys}

    if not extra_sections and not extra_keys:
        return []

    lines = list(EXTRA_SECTIONS_HEADER)
    for section, keys in extra_sections.items():
        lines.append("")
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {value}" for key, value in keys.items())
    for section, keys in extra_keys.items():
        lines.append("")
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {value}" for key, value in keys.items())
    return lines


def write(path: Path, template_text: str, values: dict[str, dict[str, str]]) -> None:
    """
    Render and write the file, creating its directory if needed.

    Written to a temporary file in the same directory and moved into place, so
    an interrupted write cannot leave a half-written config behind - the file
    the framework needs before it can even open its log.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(render(template_text, values), encoding="utf-8")
    temporary.replace(path)
