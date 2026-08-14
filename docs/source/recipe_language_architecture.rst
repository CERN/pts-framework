.. SPDX-FileCopyrightText: 2026 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Recipe Language 2 Architecture
==============================

.. important::

   Recipe language ``2.0.0`` is the only production parsing and execution
   path. Maintained recipes and setup templates use version 2; external
   version 1 files are rejected with migration diagnostics.

Exact version 2 fields, types, defaults, and examples are in the generated
:doc:`_generated/recipe_language_reference`.  The aggregate schema is also available as
:download:`recipe_language.schema.json
<_generated/recipe_language.schema.json>`.

Design and dependency direction
-------------------------------

The version 2 design has one structural definition.  Strict, frozen Pydantic
models own field names, types, required status, defaults, descriptions,
examples, aliases, discriminators, serialization metadata, and JSON Schema.
Consumers inspect either the typed model or its generated schema; they do not
maintain another field registry.

The modules and artifacts have deliberately one-way dependencies::

   pypts.recipe_language
      |  Pydantic fields and discriminated unions
      +--------------------------+
      |                          |
      v                          v
   pypts.recipe_parser      JSON Schema generator
      |                          |
      |                          v
      |               recipe_language.schema.json
      |                          |
      |                          v
      |                 JSON-only RST renderer
      |                          |
      v                          v
   typed Recipe             generated reference RST
      |                          |
      v                          v
   recipe.py runtime            Sphinx
   construction

``recipe_language`` never imports YAML, runtime classes, concrete steps, YamVIEW, or
Sphinx.  ``recipe_parser`` depends on the models and PyYAML, but still does not
import runtime or UI code.  Documentation generation reads the model only to
create JSON Schema; the RST renderer reads the JSON generated for the current
build and has no Pydantic or Sphinx dependency.

Parsing and information flow
----------------------------

Pydantic validates already-constructed Python values; it is not a YAML parser.
Safe loading, source positions, structural validation, and application
semantics therefore remain separate stages::

   recipe YAML text/file
           |
           v
   PyYAML YAML front end
           |                              source information
           +--> compose_all(SafeLoader) --> node/path/span index -----+
           |        |                                               |
           |        +--> duplicate/recursive-alias diagnostics ------+
           |
           +--> safe_load_all() --> safe Python documents            |
                                           |                         |
                                           v                         |
                                  strict Pydantic models              |
                                           |                         |
                                           v                         |
                               cross-document semantic pass           |
                                           |                         |
                                           +--> diagnostics <---------+
                                           |    code, path, severity,
                                           |    source, nearest span
                                           v
   frozen aggregate Recipe
           |
           +--> canonical multi-document YAML
           |
           +--> recipe.py runtime construction

``parse_recipe_text`` and ``parse_recipe_file`` return ``ParseResult``.  A
valid result owns an aggregate :ref:`recipe-v2-header` plus one or more
:ref:`recipe-v2-sequence` models.  ``require_recipe()`` raises with the complete
diagnostic tuple when errors exist. ``recipe_to_yaml`` returns deterministic
version 2 YAML without file I/O; comments, quoting, and original formatting
are not preserved. Parse/serialize/reparse preserves the aggregate definition.

Here, "composition" is PyYAML terminology, not a PyPTS adapter or an additional
recipe representation.  ``yaml.compose_all(..., Loader=yaml.SafeLoader)``
returns PyYAML node objects with source marks, which the parser uses to detect
duplicate keys and recursive aliases and to index diagnostic spans.
``yaml.safe_load_all()`` separately constructs ordinary safe Python values for
Pydantic.  Both operations use PyYAML's safe loader; neither constructs runtime
``Recipe`` or ``Step`` objects.

Structural and custom semantic rules
------------------------------------

Rules local to one model stay beside that model.  Pydantic reports them with a
precise nested location, which the parser translates to the PyPTS diagnostic
envelope and nearest YAML span.

For example, an indexed :ref:`recipe-v2-input-direct` must hold a list:

.. literalinclude:: ../../src/pypts/recipe_language.py
   :language: python
   :start-after: # docs:indexed-direct-start
   :end-before: # docs:indexed-direct-end
   :dedent: 4

A Python method action requires ``method_name``:

.. literalinclude:: ../../src/pypts/recipe_language.py
   :language: python
   :start-after: # docs:method-name-start
   :end-before: # docs:method-name-end
   :dedent: 4

Likewise, :ref:`recipe-v2-step-waitstep` requires a named ``wait_time`` input:

.. literalinclude:: ../../src/pypts/recipe_language.py
   :language: python
   :start-after: # docs:wait-time-start
   :end-before: # docs:wait-time-end
   :dedent: 4

Other rules require context that no individual JSON object or JSON Schema can
see.  They remain in one explicit semantic pass.  Sequence names must be
unique and ``main_sequence`` must resolve:

.. literalinclude:: ../../src/pypts/recipe_parser.py
   :language: python
   :start-after: # docs:sequence-semantics-start
   :end-before: # docs:sequence-semantics-end
   :dedent: 4

Every :ref:`recipe-v2-step-sequencestep` target is then resolved across all
loaded documents:

.. literalinclude:: ../../src/pypts/recipe_parser.py
   :language: python
   :start-after: # docs:nested-reference-start
   :end-before: # docs:nested-reference-end
   :dedent: 12

Indexed lists on one step must have equal lengths, while
:ref:`recipe-v2-output-passthrough` must be the only verdict-producing output:

.. literalinclude:: ../../src/pypts/recipe_parser.py
   :language: python
   :start-after: # docs:mapping-semantics-start
   :end-before: # docs:mapping-semantics-end
   :dedent: 12

SSH rules need both recipe globals and execution order.  The semantic pass
checks required connection globals and credentials, rejects an upload before a
connection, and requires an opened connection to be closed:

.. literalinclude:: ../../src/pypts/recipe_parser.py
   :language: python
   :start-after: # docs:ssh-semantics-start
   :end-before: # docs:ssh-semantics-end
   :dedent: 8

These rules are documented manually because JSON Schema describes the
aggregate structure, not multi-document YAML safety, source spans, equality
between sibling list lengths, reference resolution, or ordered lifecycle
state.

How YamVIEW consumes the language
---------------------------------

YamVIEW treats the aggregate JSON Schema as its form description.  The
``Step``, ``InputMapping``, and ``OutputMapping`` discriminator maps enumerate
available variants; referenced definitions provide properties, required
fields, strict types, defaults, descriptions, examples, and allowed literal
values.

The editor flow is::

   generated/published JSON Schema
           |
           +--> discriminator choices --> step/mapping selectors
           |
           +--> referenced properties --> labels, controls, help, defaults
                                         |
                                         v
   edited aggregate document --> canonical YAML text
                                         |
                                         v
                              parse_recipe_text()
                                  |           |
                                  |           +--> diagnostics and source spans
                                  v
                             typed Recipe

Local widget code may choose a suitable control for a JSON type, but it must
not own supported step names or field rules.  Whole-recipe validation always
goes through the parser so semantic rules and YAML diagnostics are identical
between YamVIEW, command-line tools, and runtime loading.

How the sequencer consumes the model
------------------------------------

Runtime construction begins only after parsing succeeds.  It receives the
aggregate typed model, not raw YAML or loosely typed dictionaries::

   ParseResult.require_recipe()
              |
              v
       frozen Recipe model
              |
              v
      recipe.py: Recipe
         |    |
         |    +-------> sequence table and nested reference binding
         v
      recipe.py: Sequence
         |
         v
      Step.build_step() for each typed definition
         |
         v
      STEP_TYPE_REGISTRY --> concrete classes in steps.py
         |
         v
      setup_steps -> steps -> teardown_steps

This is implemented in the existing runtime construction path, not a separate
adapter module. ``Recipe`` receives the validated aggregate model, ``Sequence``
iterates typed definitions, and ``Step.build_step()`` is the sole typed factory
that selects an executable class from ``steps.py``.

The runtime registry remains because a canonical discriminator such as
``PythonModuleStep`` must be associated with the Python class that implements
its behavior.  It is a behavior registry, not a second language schema: field
names, types, defaults, and structural rules remain exclusively in the
Pydantic models.  A completeness test requires every step-definition model
discriminator to have exactly one executable implementation.

Concrete ``_step()`` methods in ``steps.py`` continue to own execution.  For
example, the executable ``PythonModuleStep`` still imports and invokes Python
code; it no longer validates an untrusted recipe dictionary. Common definition
fields are dumped once by ``Step.build_step()`` and passed to the existing
constructors. ``IndexedStep`` remains a runtime-generated wrapper and is
never added to the ``StepDefinition`` model union.

Synthetic runtime operations are also constructed directly.  For example,
``Recipe.run()`` must not fabricate a recipe dictionary merely to execute the
main sequence.  No runtime construction reparses YAML or repeats Pydantic
structural validation, and invalid recipes never instantiate executable steps.
Execution events, error policy, reports, hardware access, and GUI interaction
remain downstream of the frozen language model.

Canonical documentation recipe
------------------------------

This documentation-owned fixture demonstrates the version 2 header, two
sequences, nested execution, canonical step names, explicit discriminators,
indexed input, every input variant, and representative verdict, storage,
image, and passthrough outputs. Tests validate and round-trip it with the
production parser. It is not a bundled recipe.

.. literalinclude:: _examples/recipe_v2.yml
   :language: yaml
   :caption: Canonical recipe language 2 example

Maintaining the documentation
-----------------------------

See :doc:`recipe_language_maintenance` for the complete extension and version
upgrade workflow, including the definition/runtime boundary and the purpose of
``STEP_TYPE_REGISTRY``.

Every Sphinx build generates both artifacts before reading documentation
sources::

   Pydantic models
         |
         v
   _generated/recipe_language.schema.json
         |
         v
   JSON-only RST renderer
         |
         v
   _generated/recipe_language_reference.rst

The Sphinx ``builder-inited`` hook writes these files to an ignored staging
directory under ``docs/source``.  The schema is copied into the HTML output as a
download, and the generated RST is included in the toctree.  Neither generated
file is maintained manually or treated as a committed source artifact.

Pydantic is a core production dependency. CI and any documentation build image
must install the ``doc`` extra and include the model, schema generator, and
JSON-only renderer sources.

The documentation contract is protected by tests that generate into temporary
directories, verify deterministic model-to-JSON and JSON-to-RST output, count
all discriminator variants, validate the example, check literal-include
markers, and build Sphinx with warnings treated as errors.  Generation failure
therefore fails the same build that would publish the documentation.
