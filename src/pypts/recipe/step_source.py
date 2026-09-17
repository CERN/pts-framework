# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The YAML behind one step table row - the recipe's side of the click panel.

The GUI shows an operator the YAML of the step they clicked. It is a different
process and it must not learn the recipe format to do that, so the whole of
that knowledge stays here: one function in, a `StepSource` per row out.

**What a row gets: the whole sequence, as written, and where its step is in it.**
The panel shows the sequence document the step belongs to - the file's own text,
comments and formatting included - and highlights the step's lines. A row inside
a called sequence gets *that* sequence's document, not the caller's. The row of a
Sequence step itself gets the document of the sequence it *calls*, with nothing
highlighted: clicking a call shows what the call runs. The rows an `Indexed`
step expands into exist in no file, so each of them highlights the authored
`Indexed` block they came from.

`recipe_file_text(path)` is the whole file, for the toolbar's recipe preview.

**The ordering contract.** Rows are produced in the order `Sequence.to_summary()`
emits them - steps, then teardown_steps, an Indexed step counted once per
parameter set, and every Sequence step followed by the rows of the sequence it
calls - because that is the order of the rows in the step table. Tests in
tests/unit_tests/test_recipe.py pin the two together.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pypts.logger.log import log
from pypts.recipe import recipe_parser
from pypts.recipe.recipe import RecipeError
from pypts.recipe.rules import SEQUENCE_DEFAULTS
from pypts.step import indexed_step, sequence_step

#: The two step lists of a sequence document, in row order.
_STEP_LISTS = ("steps", "teardown_steps")


@dataclass(frozen=True)
class StepSource:
    """
    What the click panel shows for one row.

    `text` is the sequence document the row's step belongs to, exactly as the
    file has it. `first_line` and `last_line` are the step's lines in that
    text, 0-based and inclusive.
    """

    text: str
    first_line: int
    last_line: int

    @property
    def highlights(self) -> bool:
        """False for a whole sequence shown with nothing picked out in it."""
        return self.first_line >= 0


#: A StepSource's line numbers when nothing in its text is highlighted.
NO_LINE = -1


def recipe_file_text(path: str) -> str:
    """
    The whole recipe file, exactly as written, for the toolbar's preview.

    Empty when the file cannot be read: a preview is a convenience, and CORE has
    already decided whether the recipe loads.
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        log.debug("No recipe text available for '%s': %s", path, error)
        return ""


@dataclass
class _Document:
    """One sequence document: its normalized data, its node, and its text."""

    data: dict[str, Any]
    node: yaml.MappingNode
    text: str
    first_file_line: int


def step_sources_by_sequence(path: str) -> dict[str, tuple[StepSource, ...]]:
    """
    Sequence name -> one StepSource per row of its step table.

    This is a convenience view, so a file that cannot be read, or a sequence
    that cannot be shown, costs the panel and nothing else: the recipe itself
    has already been loaded by CORE, which is what decides whether a run is
    possible. Such a failure is a DEBUG line and an empty result (or a missing
    sequence). It is called right after CORE loaded the same file, so a file
    edited in between is not guarded against.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        loaded = list(yaml.safe_load_all(text))
        nodes = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except (OSError, yaml.YAMLError) as error:
        log.debug("No step YAML available for '%s': %s", path, error)
        return {}
    if len(loaded) != len(nodes):
        # An empty document is data None but no node; the two cannot be paired.
        log.debug("No step YAML available for '%s': an empty YAML document.", path)
        return {}

    lines = text.split("\n")
    documents = _sequence_documents(loaded, nodes, lines)

    sources: dict[str, tuple[StepSource, ...]] = {}
    for document in documents.values():
        name = str(document.data["sequence_name"])
        try:
            sources[name] = tuple(_rows(document, documents, ()))
        except (RecipeError, KeyError, ValueError, TypeError, AttributeError) as error:
            log.debug("No step YAML for sequence '%s' of '%s': %s", name, path, error)
    return sources


def _sequence_documents(
    loaded: list[Any], nodes: list[Any], lines: list[str]
) -> dict[str, _Document]:
    """Every sequence document by lowercased name. Document 1 is the header."""
    documents: dict[str, _Document] = {}
    for data, node in zip(loaded[1:], nodes[1:], strict=True):
        if not isinstance(data, dict) or not isinstance(node, yaml.MappingNode):
            continue
        normalized = recipe_parser.apply_defaults(
            recipe_parser.normalize_sequence(data), SEQUENCE_DEFAULTS
        )
        name = str(normalized.get("sequence_name") or "")
        if not name or name.lower() in documents:
            continue
        first, last = _document_lines(node, lines)
        documents[name.lower()] = _Document(
            data=normalized,
            node=node,
            text="\n".join(lines[first : last + 1]),
            first_file_line=first,
        )
    return documents


def _document_lines(node: yaml.MappingNode, lines: list[str]) -> tuple[int, int]:
    """
    The file lines one document occupies: from just after the `---` above it
    to just before the `---` below it, so the comments an author wrote at the
    top of a sequence come with it. Trailing blank lines are left out.
    """
    first = 0
    for index in range(node.start_mark.line - 1, -1, -1):
        if lines[index].startswith("---"):
            first = index + 1
            break

    last = len(lines) - 1
    for index in range(node.start_mark.line + 1, len(lines)):
        if lines[index].startswith("---"):
            last = index - 1
            break
    while last > first and not lines[last].strip():
        last -= 1
    return first, last


def _rows(
    document: _Document, documents: dict[str, _Document], chain: tuple[str, ...]
) -> list[StepSource]:
    """One document's rows, each call followed by the rows of what it calls."""
    name = str(document.data["sequence_name"])
    chain = (*chain, name.lower())
    text_lines = document.text.split("\n")
    rows: list[StepSource] = []
    for list_name in _STEP_LISTS:
        step_datas = list(document.data[list_name])
        item_nodes = _list_items(document.node, list_name)
        for position, step_data in enumerate(step_datas):
            following = None
            if position + 1 < len(item_nodes):
                following = item_nodes[position + 1]
            first, last = _item_lines(
                item_nodes[position], following, document.first_file_line, text_lines
            )
            source = StepSource(text=document.text, first_line=first, last_line=last)
            if indexed_step.is_indexed_step(step_data):
                # Every generated row points at the Indexed block it came from.
                count = len(indexed_step.expand_indexed_step(step_data))
                rows.extend([source] * count)
                continue
            if not sequence_step.is_sequence_step(step_data):
                rows.append(source)
                continue
            called = documents.get(str(step_data.get("sequence_name")).lower())
            # The parser has refused an unknown name or a cycle already; here
            # they fall back to the call itself and add no rows.
            if called is None or str(called.data["sequence_name"]).lower() in chain:
                rows.append(source)
                continue
            # The call's row shows what the call runs: the called sequence, whole.
            rows.append(StepSource(text=called.text, first_line=NO_LINE, last_line=NO_LINE))
            rows.extend(_rows(called, documents, chain))
    return rows


def _list_items(node: yaml.MappingNode, list_name: str) -> list[yaml.Node]:
    """The item nodes of a `steps` / `teardown_steps` list; keys are case-insensitive."""
    for key, value in node.value:
        if str(key.value).lower() == list_name and isinstance(value, yaml.SequenceNode):
            return list(value.value)
    return []


def _item_lines(
    item: yaml.Node, following: yaml.Node | None, offset: int, text_lines: list[str]
) -> tuple[int, int]:
    """
    The lines one list item occupies in its document's text, 0-based, inclusive.

    A block mapping's end mark is where the next token starts - the next item's
    dash, or column 0 of the line after the list - so the item is bounded by the
    next item's first line, and the blank lines and comments in front of that
    item are trimmed off: they belong to it.
    """
    first = item.start_mark.line - offset
    last = item.end_mark.line - offset
    if item.end_mark.column == 0:
        last -= 1
    if following is not None:
        last = min(last, following.start_mark.line - offset - 1)
    last = min(last, len(text_lines) - 1)
    while last > first:
        stripped = text_lines[last].strip()
        if stripped and not stripped.startswith("#"):
            break
        last -= 1
    return first, last
