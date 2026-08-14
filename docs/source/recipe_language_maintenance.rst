.. SPDX-FileCopyrightText: 2026 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Maintaining the Recipe Language
===============================

This page is for maintainers extending recipe language ``2.0.0`` or preparing
a future language version. For the current data flow and validation stages,
see :doc:`recipe_language_architecture`. Exact fields and variants are listed
in the :doc:`_generated/recipe_language_reference`.

Terminology and ownership
-------------------------

``Step definition``
   Declarative recipe data represented by a strict, frozen Pydantic model in
   ``pypts.recipe_language``. ``StepDefinition`` is the discriminated union of
   every step users may place in YAML.

``Validated recipe definition``
   The aggregate ``pypts.recipe_language.Recipe`` returned by
   ``ParseResult.require_recipe()`` after YAML, structural, and semantic
   validation succeeds.

``Executable step``
   A runtime object implemented in ``pypts.steps``. It owns behavior such as
   ``_step()`` but does not define the authored recipe schema.

``Runtime-only step``
   An internal operation that cannot be written directly in YAML. For example,
   ``IndexedStep`` is created when a validated direct input has ``indexed`` set.

The Pydantic models are the only structural definition of the language. JSON
Schema, generated reference documentation, YamVIEW selectors, and form fields
all derive from them. Do not add a second list of supported steps, mappings,
required fields, defaults, or aliases in a consumer.

Runtime dispatch and dependency direction
-----------------------------------------

``Step.build_step()`` in ``pypts.recipe`` is the single boundary between a
validated step definition and an executable step::

   recipe_language.StepDefinition
                |
                v
       Step.build_step()
                |
                v
       STEP_TYPE_REGISTRY
                |
                v
       executable class in steps.py

``STEP_TYPE_REGISTRY`` is intentionally beside the factory. It answers only:
"Which executable class implements this validated discriminator?" It does not
own fields, defaults, validation rules, or the set exposed by JSON Schema.

Moving the registry into ``steps.py`` would reverse the existing dependency
direction: executable classes in ``steps.py`` derive from or interact with
runtime types defined in ``recipe.py``. Keeping dispatch in ``recipe.py`` avoids
introducing a runtime adapter or circular registration mechanism. A
completeness test requires the registry keys to equal the discriminators in
``STEP_DEFINITION_MODELS`` exactly.

Adding a step definition
------------------------

1. Add the strict Pydantic definition in ``recipe_language.py`` and include it
   in the ``StepDefinition`` discriminated union. Use the exact canonical
   ``steptype`` literal; do not add normalization or lowercase aliases.
2. Implement the executable class in ``steps.py``. Keep recipe-structure
   validation in the definition model or parser rather than its constructor.
3. Add one discriminator-to-class entry to ``STEP_TYPE_REGISTRY`` beside
   ``Step.build_step()``. Do not register runtime-only wrappers.
4. Add parse/dump/reparse coverage, runtime construction assertions, and a
   behavioral execution test. The registry-completeness test must remain exact.
5. Build the documentation and review the generated schema, reference section,
   and YamVIEW selector. These consumers should update without hardcoded lists.

Adding fields or mapping variants
---------------------------------

Put a field's type, required status, default, description, examples, aliases,
and serialization behavior on its Pydantic declaration. A rule concerning one
object belongs in a model validator. A rule requiring other sequences, sibling
values, reference resolution, or execution order belongs in the parser's
aggregate semantic pass so it can produce a structured source-span diagnostic.

For a new input or output mapping, add its definition to the corresponding
discriminated union and test parse, canonical dump, reparse, generated schema,
reference rendering, and YamVIEW mapping rows. Runtime mapping behavior must
also receive a focused execution test.

Preparing a language version upgrade
------------------------------------

A version change is a deliberate compatibility decision, not a normalization
shortcut. Before changing the header's ``recipe_version`` literal:

* define the supported version policy and whether migration is a separate
  release phase;
* document removed, renamed, and newly required fields and discriminators;
* update parser diagnostics for missing, legacy, and unsupported versions;
* update canonical examples, fixtures, schema expectations, and release notes;
* decide explicitly whether multiple versions have separate models and runtime
  paths; never silently coerce one version into another;
* verify that invalid or legacy documents cannot construct executable state;
* review generated JSON Schema and reference artifacts before release.

Documentation and verification
------------------------------

Sphinx generates the JSON Schema first and renders the human reference from
that exact file. Do not hand-edit files below ``docs/source/_generated``. Run::

   python -m pypts.recipe_artifacts
   python -m pytest tests
   python -m ruff check src tests
   python -m sphinx -W -b html docs/source docs/_build/html

At minimum, a recipe-language change must pass deterministic artifact tests,
all discriminator and runtime-registry completeness tests, the full unit and
functional suite, and Sphinx with warnings treated as errors.
