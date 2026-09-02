# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe data layer: what a recipe *is*, not what running one does.

Data only. The objects the Sequencer executes:

    Recipe      one file: the header fields, plus the sequences it contains
    Sequence    one named, ordered list of steps

A Step belongs to pypts.step; a Sequence only holds them. This module
executes nothing, touches no queue and does not import the Sequencer.

The rest of the package: `rules.py` holds the format definitions,
`validator.py` the mandatory-field checks, `recipe_parser.py` the whole
loading pipeline (read, normalize, validate, version-check, defaults,
build). `Recipe.from_file()` / `Recipe.from_yaml_text()` are thin facades
over that parser, so callers keep one obvious entry point; every load
failure is a RecipeError - one type for CORE to catch.
"""

from typing import Any

from pypts.messages.run_events import SequenceSummary, StepSummary
from pypts.step.step import Step


class RecipeError(Exception):
    """A recipe file that cannot be loaded: unreadable, unparseable or invalid."""


class Sequence:
    """One named, ordered list of steps. Data only."""

    def __init__(
        self,
        name: str,
        description: str,
        steps: list[Step],
        teardown_steps: list[Step],
    ) -> None:
        self.name = name
        self.description = description
        self.steps = steps
        self.teardown_steps = teardown_steps

    def __repr__(self) -> str:
        return f"Sequence({self.name!r}, {len(self.steps)} steps)"

    def to_summary(self) -> SequenceSummary:
        """
        The pickle-safe projection a frontend receives, mirroring
        StepResult.to_outcome(). One row per step that will emit events during
        a run - which includes the teardown steps, at the end.
        """
        rows = tuple(
            StepSummary(step_id=step.id, step_name=step.name, description=step.description)
            for step in self.steps + self.teardown_steps
        )
        return SequenceSummary(sequence_name=self.name, steps=rows)


class Recipe:
    """One recipe file: the header fields, plus the sequences it contains."""

    def __init__(
        self,
        name: str,
        description: str,
        version: str,
        globals: dict[str, Any],
        main_sequence: str,
        sequences: dict[str, Sequence],
        report_metadata: tuple[str, ...] = (),
        version_notice: str = "",
        file_name: str = "",
        base_dir: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.globals = globals
        self.main_sequence = main_sequence
        self.sequences = sequences
        #: The globals the Report stamps on every row and in the report
        #: header. The recipe names them; the framework only carries them.
        self.report_metadata = report_metadata
        #: Empty when the recipe's `version` matches the running pypts.
        #: Otherwise the sentence the operator should see: the parser
        #: knows the format, CORE owns the channel to the frontend, so
        #: the text is written here and reported there.
        self.version_notice = version_notice
        self.file_name = file_name
        #: The folder the file came from - what a PythonModule step's relative
        #: `module:` path resolves against. Empty for a recipe parsed from text.
        self.base_dir = base_dir

    def __repr__(self) -> str:
        return f"Recipe({self.name!r} v{self.version}, {len(self.sequences)} sequence(s))"

    def to_summary(self) -> tuple[SequenceSummary, ...]:
        """Every sequence's summary, in document order."""
        return tuple(sequence.to_summary() for sequence in self.sequences.values())

    # --- the facades over the parser -----------------------------------------
    # Imported inside the methods because the parser imports this module's
    # classes - the one-way module-level dependency is parser -> data.

    @classmethod
    def from_file(cls, path: str) -> "Recipe":
        """Load and validate a recipe file; every failure is a RecipeError."""
        from pypts.recipe import recipe_parser

        return recipe_parser.load_recipe(path)

    @classmethod
    def from_yaml_text(cls, text: str, file_name: str = "") -> "Recipe":
        """Parse recipe YAML; every failure is a RecipeError."""
        from pypts.recipe import recipe_parser

        return recipe_parser.parse_recipe(text, file_name=file_name)
