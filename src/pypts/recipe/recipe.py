# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe data layer: what a recipe *is*, not what running one does.

This module owns parsing a recipe file into an object tree, and validating
it. Nothing else. It executes nothing, touches no queue and does not import
the Sequencer. That split did not exist in the old code, where Recipe.run()
both held the data and drove it; creating it is half the point of the port.

    Recipe      one file: the header fields, plus the sequences it contains
    Sequence    one named, ordered list of steps, plus its local variables

A Step belongs to pypts.step; a Sequence only holds them.

The file format
---------------
A multi-document YAML file read with yaml.safe_load_all, so **document order
is significant**: document 1 is the header, and every document after it is a
sequence keyed by its `sequence_name`.

The header requires `name`, `description`, `version`, `globals` and
`main_sequence` (the sequence a frontend offers to run by default - any
sequence can be requested, which the old engine could not do: it overwrote
the requested name with main_sequence, F3). `test_package` is optional: the
package root under which a PythonModuleStep resolves its `module:` - parsed
when that step type is ported. The legacy header keys `continue_on_error`
and `recipe_version` are tolerated and ignored: nothing ever read them
(F1, F2), but four of five example recipes carry them. Roadmap TODO.

A sequence holds `locals` and three step lists - `setup_steps`, `steps` and
`teardown_steps`. Setup and steps are concatenated into **one flat list**,
so a setup step is only a step that runs first. `teardown_steps` genuinely
differs: the engine runs it in a `finally`, after a failure or an abort too.
`parameters` and `outputs` are parsed and stored but consumed by nothing -
the old engine never implemented them either; their design is an open
roadmap question (recipe_guide.md section 18).

Validation
----------
Every load failure is a RecipeError - one type for CORE to catch - and every
silent mistake of the old loader is a loud refusal here: a sequence document
without `sequence_name` (was: skipped), a duplicate sequence name (was: last
one won), an unknown steptype (was: NameError out of eval), an unknown step
key (TypeError, wrapped with which sequence and step), a `main_sequence`
that names no sequence (was: KeyError at run time).
"""

from pathlib import Path
from typing import Any

import yaml

from pypts.messages.run_events import SequenceSummary, StepSummary
from pypts.step.registry import build_step
from pypts.step.step import Step

#: Header keys a recipe must carry, checked one by one so the error names
#: the first missing field rather than dumping the whole header.
REQUIRED_HEADER_FIELDS = ("name", "description", "version", "globals", "main_sequence")

#: Keys a sequence document must carry. `description` is genuinely optional.
REQUIRED_SEQUENCE_FIELDS = (
    "sequence_name",
    "parameters",
    "locals",
    "outputs",
    "setup_steps",
    "steps",
    "teardown_steps",
)

#: Header keys that appear in existing recipes but that nothing reads (F1,
#: F2). Tolerated so those files load; deciding their future is a roadmap
#: TODO (format_version policy, header-level continue_on_error).
IGNORED_HEADER_FIELDS = ("continue_on_error", "recipe_version", "test_package", "tags")


class RecipeError(Exception):
    """A recipe file that cannot be loaded: unreadable, unparseable or invalid."""


class Sequence:
    """One named, ordered list of steps, plus its local variables. Data only."""

    def __init__(
        self,
        name: str,
        description: str,
        locals: dict[str, Any],
        parameters: dict[str, Any],
        outputs: dict[str, Any],
        steps: list[Step],
        teardown_steps: list[Step],
    ) -> None:
        self.name = name
        self.description = description
        self.locals = locals
        self.parameters = parameters
        self.outputs = outputs
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

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "Sequence":
        """Build one sequence from one YAML document; refuse anything malformed."""
        name = document["sequence_name"]
        for field in REQUIRED_SEQUENCE_FIELDS:
            if field not in document:
                raise RecipeError(f"Sequence '{name}' is missing the required key '{field}'")

        # Setup steps are ordinary steps that run first - one flat list.
        steps = [
            _build_step_or_refuse(name, position, step_data)
            for position, step_data in enumerate(
                list(document["setup_steps"]) + list(document["steps"]), start=1
            )
        ]
        teardown_steps = [
            _build_step_or_refuse(name, position, step_data)
            for position, step_data in enumerate(document["teardown_steps"], start=1)
        ]
        return cls(
            name=name,
            description=document.get("description", ""),
            locals=document["locals"],
            parameters=document["parameters"],
            outputs=document["outputs"],
            steps=steps,
            teardown_steps=teardown_steps,
        )


def _build_step_or_refuse(sequence_name: str, position: int, step_data: dict[str, Any]) -> Step:
    """One step via the registry, with every failure wrapped into a RecipeError."""
    step_name = step_data.get("step_name", "<unnamed>")
    try:
        return build_step(step_data)
    except KeyError as error:
        raise RecipeError(
            f"Sequence '{sequence_name}', step {position} ('{step_name}'): "
            f"missing required key {error}"
        ) from error
    except (ValueError, TypeError) as error:
        raise RecipeError(
            f"Sequence '{sequence_name}', step {position} ('{step_name}'): {error}"
        ) from error


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
        file_name: str = "",
        base_dir: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.globals = globals
        self.main_sequence = main_sequence
        self.sequences = sequences
        self.file_name = file_name
        #: The folder the file came from - what a PythonModuleStep's relative
        #: `module:` path resolves against. Empty for a recipe parsed from text.
        self.base_dir = base_dir

    def __repr__(self) -> str:
        return f"Recipe({self.name!r} v{self.version}, {len(self.sequences)} sequence(s))"

    def to_summary(self) -> tuple[SequenceSummary, ...]:
        """Every sequence's summary, in document order."""
        return tuple(sequence.to_summary() for sequence in self.sequences.values())

    @classmethod
    def from_file(cls, path: str) -> "Recipe":
        """Load and validate a recipe file; every failure is a RecipeError."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise RecipeError(f"Cannot read recipe file '{path}': {error}") from error
        recipe = cls.from_yaml_text(text, file_name=Path(path).name)
        recipe.base_dir = str(Path(path).resolve().parent)
        return recipe

    @classmethod
    def from_yaml_text(cls, text: str, file_name: str = "") -> "Recipe":
        """Parse recipe YAML: document 1 is the header, the rest are sequences."""
        try:
            documents = list(yaml.safe_load_all(text))
        except yaml.YAMLError as error:
            raise RecipeError(f"Recipe '{file_name}' is not valid YAML: {error}") from error
        if not documents or documents[0] is None:
            raise RecipeError(f"Recipe '{file_name}' is empty")

        header = documents[0]
        if not isinstance(header, dict):
            raise RecipeError(f"Recipe '{file_name}': the first document is not a mapping")
        for field in REQUIRED_HEADER_FIELDS:
            if field not in header:
                raise RecipeError(
                    f"Recipe '{file_name}' is missing the required header field '{field}'"
                )

        sequences: dict[str, Sequence] = {}
        for number, document in enumerate(documents[1:], start=2):
            if not isinstance(document, dict) or "sequence_name" not in document:
                raise RecipeError(
                    f"Recipe '{file_name}': document {number} is not a sequence - "
                    f"it has no 'sequence_name'"
                )
            sequence = Sequence.from_document(document)
            if sequence.name in sequences:
                raise RecipeError(
                    f"Recipe '{file_name}': duplicate sequence name '{sequence.name}'"
                )
            sequences[sequence.name] = sequence

        main_sequence = header["main_sequence"]
        if main_sequence not in sequences:
            raise RecipeError(
                f"Recipe '{file_name}': main_sequence '{main_sequence}' does not exist. "
                f"Sequences: {', '.join(sequences) or '<none>'}"
            )

        return cls(
            name=header["name"],
            description=header["description"],
            version=str(header["version"]),
            globals=header["globals"],
            main_sequence=main_sequence,
            sequences=sequences,
            file_name=file_name,
        )
