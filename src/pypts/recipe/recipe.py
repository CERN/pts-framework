# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipe data layer: what a recipe *is*, not what running one does.

Empty - the port is roadmap Phase 1, step 1. This docstring records what belongs
here so the shape is agreed before the code arrives. The behaviour to reproduce
is `old_code/recipe.py` (the whole file is commented out - read it with that in
mind), and it is written up field by field in
`resources/roadmap/recipe_guide.md`, which is the reference for the port.

What this module owns
---------------------
Parsing a recipe file into an object tree, and validating it. Nothing else. It
must not execute anything, must not touch a queue and must not import the
Sequencer. That split does not exist in the old code, where `Recipe.run()` both
holds the data and drives it; creating it is half the point of the port.

    Recipe      one file: the header fields, plus the sequences it contains
    Sequence    one named, ordered list of steps, plus its local variables

A `Step` belongs to `pypts.step`; a `Sequence` only holds them.

The file format
---------------
A multi-document YAML file read with `yaml.safe_load_all`, so **document order
is significant**: document 1 is the header, and every document after it is a
sequence keyed by its `sequence_name`.

The loader requires `name`, `description`, `version` and `globals` in the
header, and `main_sequence` in practice. `test_package` is optional: it is the
package root under which a `PythonModuleStep` resolves its `module:` by
recursive search rather than by path.

A sequence holds `locals` and three step lists - `setup_steps`, `steps` and
`teardown_steps`. Setup and steps are concatenated into **one flat list**, so a
setup step is only a step that runs first: no special error handling, no
guarantee, no separate reporting. `teardown_steps` is the one that genuinely
differs - it runs in a `finally`, so it executes after a failure or an abort
too, which is what lets a step leave its hardware in a known state.

Two variable scopes, and steps communicate through nothing else: `globals` (one
flat dict for the whole recipe) and `locals` (one dict per sequence, pushed and
popped on a stack). `serial_number` is injected into globals by the engine at
run start and must never be declared by an author.

Results
-------
`ResultType` is an IntEnum whose *ordering is the aggregation rule*:

    SKIP(0) < DONE(1) < PASS(2) < FAIL(3) < ERROR(4) < STOP(5)

A parent's result is the maximum of its children's. It already exists, in
`messages/common_messages.py`: the engine and both frontends have to agree on
it, so it lives with the messages and this module imports it rather than
declaring a second copy.

Known defects to fix *during* the port, not after
-------------------------------------------------
- Step construction is `eval(step_type + "(**step_data)")`. An unknown steptype
  is a bare `NameError`, an unknown key is a `TypeError`, and a recipe file can
  execute arbitrary Python. It needs a registry.
- A sequence document with no `sequence_name` is logged and silently skipped,
  and a duplicate name silently wins. Both should be refusals.
- Header-level `continue_on_error:` is never read - only
  `globals.continue_on_error` is - yet four of the five example recipes set it.
- `recipe_version:` in the header gates nothing at all.
- Three rule sets disagree about what a valid recipe is: this layer,
  `helper_applications/recipe_verificator/recipe_rules.py`, and the creator.
  The port collapses them into one owner.

The full list, with the finding numbers the roadmap refers to, is section 16 of
the recipe guide.
"""
