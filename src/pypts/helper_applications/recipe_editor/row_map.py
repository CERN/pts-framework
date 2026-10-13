"""
From a step table row to the step to edit, and from a line of the YAML back.

The table shows the recipe as loaded (`Recipe.to_summary()`), so its rows are not
the steps an author wrote: an Indexed step is one row per parameter set, a
Sequence step is followed by the rows of the sequence it calls. Each row's
`StepSource.origin` (recipe/step_source.py) names the authored step it comes
from; this module turns that into a `StepRef` the model can be edited through.

No Qt here: rows in, references out.
"""

from __future__ import annotations

from dataclasses import dataclass

from pypts.recipe.step_source import StepSource


@dataclass(frozen=True)
class StepRef:
    """
    One authored step: where it is in RecipeModel, and its lines in the text.

    `sequence_index` counts sequences as RecipeModel does (0 is the first
    sequence document, the one after the header). `list_name` is `steps` or
    `teardown_steps`; `step_index` the step's position in that list.
    `first_line` / `last_line` are 0-based and inclusive, in the whole text.
    """

    sequence_index: int
    list_name: str
    step_index: int
    first_line: int
    last_line: int

    @property
    def document(self) -> int:
        """The step's YAML document, as RecipeModel.set_path() counts them."""
        return self.sequence_index + 1

    def path(self, *rest: int | str) -> tuple[int | str, ...]:
        """A path inside the step, from its document: ("steps", 2, *rest)."""
        return (self.list_name, self.step_index, *rest)

    def contains_line(self, line: int) -> bool:
        return self.first_line <= line <= self.last_line


def refs_for_rows(
    sources: tuple[StepSource, ...], sequence_names: list[str]
) -> list[StepRef | None]:
    """
    One StepRef per row, None for a row whose step cannot be found.

    `sequence_names` are the model's sequence names in document order; a row's
    origin names its sequence, which is looked up there case-insensitively, the
    way the parser matches sequence names.
    """
    by_name: dict[str, int] = {}
    for index, name in enumerate(sequence_names):
        key = str(name).lower()
        if key not in by_name:
            by_name[key] = index

    refs: list[StepRef | None] = []
    for source in sources:
        origin = source.origin
        if origin is None:
            refs.append(None)
            continue
        sequence_index = by_name.get(origin.sequence_name.lower())
        if sequence_index is None:
            refs.append(None)
            continue
        refs.append(
            StepRef(
                sequence_index=sequence_index,
                list_name=origin.list_name,
                step_index=origin.index,
                first_line=origin.first_line,
                last_line=origin.last_line,
            )
        )
    return refs


def all_refs(
    sources_by_sequence: dict[str, tuple[StepSource, ...]], sequence_names: list[str]
) -> list[StepRef]:
    """Every authored step of every sequence, once each, in text order."""
    seen: set[tuple[int, str, int]] = set()
    refs: list[StepRef] = []
    for sources in sources_by_sequence.values():
        for ref in refs_for_rows(sources, sequence_names):
            if ref is None:
                continue
            key = (ref.sequence_index, ref.list_name, ref.step_index)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    refs.sort(key=lambda ref: ref.first_line)
    return refs


def ref_at_line(refs: list[StepRef], line: int) -> StepRef | None:
    """The authored step whose lines hold `line` (0-based), or None."""
    for ref in refs:
        if ref.contains_line(line):
            return ref
    return None


def first_row_of(refs: list[StepRef | None], wanted: StepRef) -> int:
    """The first table row that comes from `wanted`, -1 when none does."""
    for row, ref in enumerate(refs):
        if ref is None:
            continue
        same_step = (
            ref.sequence_index == wanted.sequence_index
            and ref.list_name == wanted.list_name
            and ref.step_index == wanted.step_index
        )
        if same_step:
            return row
    return -1
