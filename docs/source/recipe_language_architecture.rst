.. SPDX-FileCopyrightText: 2026 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Recipe Language Architecture
============================

This page describes the recipe language model, the isolated parser, and the
rules for evolving them.  The parser is currently independent of recipe
execution, ``verify_recipe``, YamVIEW, and Sphinx reference publication.  Those
runtime and UI consumers will move onto the shared model in later integration
work.

Design goals
------------

The recipe language has one contract and one parsing path.  YAML loading,
language validation, normalized data, and runtime construction are separate
responsibilities.  In particular, parsing a recipe must never import or invoke
the runtime, steps, GUI, or documentation machinery.

The current architecture has two source modules:

``pypts.recipe_language``
   Defines the framework-independent contract.  Its field and step
   specifications describe accepted recipe documents, while
   ``validate_recipe_documents`` validates already-loaded Python values.  It
   has no YAML or runtime dependency.

``pypts.recipe_parser``
   Safely loads YAML, records source locations, delegates language rules to the
   contract, and constructs immutable typed definitions.  It also serializes a
   typed recipe into canonical YAML.

``pypts.recipe_reference``
   Validates the registered examples and generates the deterministic standalone
   RST language reference.  The generated artifact remains outside the Sphinx
   source tree until framework integration is accepted.

The intended flow is::

   recipe YAML
       |
       v
   safe YAML loading and source indexing
       |
       v
   recipe_language contract validation
       |
       +---- errors and warnings with source spans
       |
       v
   immutable RecipeDefinition
       |
       +---- dump_recipe() -> canonical recipe YAML
       |
       +---- generated reference, and future runtime and GUI consumers

Parser operation
----------------

``parse_recipe_text`` and ``parse_recipe_file`` return a ``ParseResult``.  The
parser performs these stages in order:

#. Reject non-text, empty, or unreadable input.
#. Compose the YAML with ``SafeLoader`` to index nodes and their one-based line
   and column positions.  Duplicate mapping keys and recursive aliases are
   diagnosed here.
#. Safely construct the YAML documents.  Malformed YAML, unsafe tags, and
   construction failures become diagnostics rather than runtime objects.
#. Pass the loaded documents to ``validate_recipe_documents``.  This is where
   header, sequence, step, mapping, reference, and lifecycle rules are applied.
#. Attach the closest available source span to each contract diagnostic and
   emit warnings for accepted legacy spellings or implicit forms.
#. If any error exists, return no recipe.  Otherwise, normalize the documents
   into an immutable ``RecipeDefinition``.

``ParseResult.errors`` and ``ParseResult.warnings`` split diagnostics by
severity.  ``ParseResult.require_recipe()`` returns the model on success and
raises ``RecipeParseError`` with all diagnostics on failure.  Callers that need
to present every issue should inspect the result before requiring the model.

Diagnostics contain a stable code, message, semantic path, severity, source
name, and optional ``SourceSpan``.  Consumers should branch on the code rather
than matching message text.  A source span is half-open; its line and column
values are one-based and its character offset is zero-based.

Typed and normalized model
--------------------------

The model is made of frozen definitions for the recipe header, sequences,
steps, and each input and output mapping variant.  Arbitrary mappings that are
part of recipe data use the immutable, insertion-ordered ``FrozenMap``.  Source
spans and source names do not participate in semantic equality, which makes a
parse/dump/reparse comparison independent of file location.

Normalization currently includes:

* canonical step type casing;
* explicit typed input and output definitions;
* false defaults for step flags;
* empty mappings for optional mapping fields;
* recipe report defaults; and
* removal of runtime-ignored legacy sequence metadata from the typed model.

``dump_recipe`` emits stable, explicit-start, multi-document YAML.  It writes
canonical step names, explicit input types, explicit defaults, and stable field
ordering.  It does not preserve comments or the source's original formatting.
The semantic guarantee is therefore model round-trip equality, not textual
round-trip equality.

Using the parser
----------------

Parse in-memory YAML when the caller already owns the text:

.. code-block:: python

   from pypts.recipe_parser import parse_recipe_text

   result = parse_recipe_text(source, source_name="recipe.yml")
   if result.errors:
       for diagnostic in result.errors:
           print(diagnostic.code, diagnostic.path, diagnostic.span)
   else:
       recipe = result.require_recipe()

Use ``parse_recipe_file`` when the parser should read the file and report I/O
or decoding failures as diagnostics.  Use ``dump_recipe`` only with a valid
``RecipeDefinition``.

Architecture boundaries
-----------------------

Keep the dependency direction narrow:

* ``recipe_language`` must not depend on YAML, runtime classes, concrete steps,
  YamVIEW, or Sphinx.
* ``recipe_parser`` may depend on PyYAML and ``recipe_language`` but not on
  runtime, concrete steps, YamVIEW, or Sphinx.
* Runtime and UI adapters may consume parser models after integration; parser
  models must not consume those adapters.
* Syntax reference fields, constraints, and examples are generated and checked
  from the language specifications.  Architecture prose explains
  responsibilities and extension workflows rather than duplicating field
  tables.

These rules keep syntax inspection safe and make the parser usable by command
line tools, editors, the GUI, tests, and documentation without constructing
hardware-facing runtime objects.

Maintaining the language
------------------------

Adding or changing a step
~~~~~~~~~~~~~~~~~~~~~~~~

#. Update its ``StepSpec`` and ``FieldSpec`` entries in
   ``pypts.recipe_language``.  Do not create a second field list in a consumer.
#. Add semantic checks beside the shared contract validation when a constraint
   cannot be represented by required fields and value types.
#. Add a valid executable parser fixture and focused invalid cases for every
   new constraint.
#. Confirm canonical serialization contains the step-specific configuration in
   specification order and parse/dump/reparse preserves the model.
#. During framework integration, update only the adapter that constructs the
   runtime step from ``StepDefinition``.
#. Regenerate and check the standalone syntax reference::

      python -m pypts.recipe_reference docs/generated/recipe_language_reference.rst
      python -m pypts.recipe_reference --check docs/generated/recipe_language_reference.rst

Changing input or output mappings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Update the allowed and required fields in the contract validator.
#. Add or adjust the corresponding frozen mapping definition, model builder,
   and serializer branch in ``recipe_parser``.
#. Test accepted values, every relevant failure, source spans, normalization,
   and canonical round trips.
#. Check runtime and GUI adapters after integration.  They should dispatch on
   typed mapping definitions instead of maintaining supported-type lists.

Evolving ``recipe_version``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Recipe format changes must be explicit.  Do not silently reinterpret an
existing version.  First describe compatibility and migration behavior, then
add version-specific contract handling and fixtures.  Preserve parsing for a
supported old version or emit a precise unsupported-version diagnostic.  A
canonical dump must state the version whose semantics it writes.

Retiring legacy syntax
~~~~~~~~~~~~~~~~~~~~~~

Legacy syntax should move through an observable sequence: accept and normalize
with a stable warning, document the canonical replacement, measure and migrate
the bundled examples and consumers, and only then reject it in a declared
recipe version.  Never remove an accepted form merely by changing a runtime
constructor.

Verification
------------

The parser and language tests are in ``tests/unit_tests/test_recipe_parser.py``
and ``tests/unit_tests/test_recipe_language.py``.  Run them directly while
editing the contract, then run the complete suite:

.. code-block:: console

   python -m pytest tests/unit_tests/test_recipe_language.py tests/unit_tests/test_recipe_parser.py
   python -m pytest

The acceptance corpus consists of every non-empty bundled recipe.  Each must
parse, dump, reparse, and compare equal as a model.  The comment-only draft is
intentionally invalid.  Isolation tests also protect the parser from importing
runtime, step, GUI, or Sphinx modules.

After the integration phase, verification must also cover runtime construction
equivalence, GUI-produced canonical YAML, successful Sphinx builds with
warnings treated as errors, and the absence of duplicated consumer-side field
or type registries.
