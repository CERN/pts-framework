# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The YAML behind one step table row, rendered - the recipe's side of the hover panel.

The GUI shows an operator the YAML of the step under the mouse. It is a
different process and it must not learn the recipe format to do that, so the
whole of that knowledge stays here: one function in, already-rendered text out,
keyed by sequence name and indexed by row.

**What a fragment is: the effective step mapping, not a slice of the file.**
`steptype: Indexed` is expanded at load time into one ordinary step per
parameter set (pypts.step.indexed_step), so the ten rows an Indexed step
produces exist in no file and a text slice would show the same block ten times.
Rendering the mapping the engine actually built gives every row its own
fragment, and shows what will run rather than what was written.

The cost is fidelity: the mapping has been through `normalize_sequence()`, so
its keys are lowercased and the author's comments and formatting are gone.
Values keep the case they were written in - `steptype: PythonModule` still
reads as it did in the file. No step-level defaults are invented - `rules.py`
only defaults the header and the sequence - so a fragment is the author's
mapping, lowercased and expanded, and nothing more.

**The ordering contract.** The row list is built exactly as
`recipe_parser._build_sequence()` builds it - steps, then teardown_steps,
each expanded - because that is the order `Sequence.to_summary()`
emits and therefore the order of the rows in the step table. A test in
tests/unit_tests/test_recipe.py pins the two together.
"""

from pathlib import Path
from typing import Any

import yaml

from pypts.logger.log import log
from pypts.recipe import recipe_parser
from pypts.recipe.rules import SEQUENCE_DEFAULTS


def step_yaml_by_sequence(path: str) -> dict[str, tuple[str, ...]]:
    """
    Sequence name -> one rendered YAML fragment per row of its step table.

    Never raises. This is a convenience view, so a file that cannot be read or
    makes no sense costs the panel and nothing else: the recipe itself has
    already been loaded by CORE, which is what decides whether a run is
    possible. A failure is a DEBUG line and an empty result: the operator is
    not missing anything they can act on, only a syntax-coloured panel.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        documents = list(yaml.safe_load_all(text))
    except (OSError, yaml.YAMLError) as error:
        log.debug("No step YAML available for '%s': %s", path, error)
        return {}

    fragments: dict[str, tuple[str, ...]] = {}
    # Document 1 is the header; it has no steps.
    for document in documents[1:]:
        if not isinstance(document, dict):
            continue
        try:
            name, rendered = _one_sequence(document)
        except (ValueError, TypeError, yaml.YAMLError) as error:
            log.debug("No step YAML for one sequence of '%s': %s", path, error)
            continue
        if name:
            fragments[name] = rendered
    return fragments


def _one_sequence(document: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """One sequence document: its name, and a fragment per row of its table."""
    document = recipe_parser.normalize_sequence(document)
    document = recipe_parser.apply_defaults(document, SEQUENCE_DEFAULTS)
    name = str(document.get("sequence_name") or "")

    # The same call, on the same list, as _build_sequence().
    authored = list(document["steps"])
    step_datas = recipe_parser._expand_indexed_steps(name, authored)
    step_datas += recipe_parser._expand_indexed_steps(
        name, list(document["teardown_steps"])
    )
    return name, tuple(_render(step_data) for step_data in step_datas)


def _render(step_data: Any) -> str:
    """
    One step mapping as the text the panel shows.

    `default_flow_style=None` is the setting that matters: it keeps a mapping
    with nothing nested inside it on one line, so an output check renders as
    `voltage: {type: range, min: '11', max: '13'}` - which is how the recipe
    author wrote it, and three lines shorter in a panel than the block form.
    `sort_keys=False` keeps the authored order, so `steptype` and `step_name`
    stay at the top where they are looked for.
    """
    if not isinstance(step_data, dict):
        return ""
    dumped = yaml.safe_dump(
        step_data, sort_keys=False, default_flow_style=None, allow_unicode=True
    )
    return dumped.rstrip()
