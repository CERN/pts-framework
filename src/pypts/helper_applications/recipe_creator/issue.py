from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ValidationIssue:
    """One problem found in a recipe file.

    severity  'error'   - the recipe will not load; the problem must be fixed.
              'warning' - the recipe will load but something looks wrong or
                          uses a removed feature.
    field     Dotted path to the field in question, e.g.
              'header.name', "sequence 'Main'.steps[2].wait_time".
    message   Short description of what is wrong.
    hint      What to do to fix it, with a YAML example where useful.
    line      1-based line number in the YAML source, or None if not trackable.
    document  0-based index of the YAML document the problem is in (0 is the
              header), or None where it is about no one document.
    path      Where in that document, as the schema found it - e.g.
              ('steps', 1, 'outputs', 'r', 'max'). Empty where there is no
              field to point at (structure, cross-document checks, warnings).
              For a tool that marks the field itself (Recipe Editor v2).
    """

    severity: Literal["error", "warning"]
    field: str
    message: str
    hint: str
    line: int | None = None
    document: int | None = None
    path: tuple[int | str, ...] = ()

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"

    def __str__(self) -> str:
        location = f" (line {self.line})" if self.line is not None else ""
        tag = "ERROR" if self.is_error else "WARNING"
        return f"[{tag}]{location} {self.field}: {self.message}"
