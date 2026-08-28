.. SPDX-FileCopyrightText: 2026 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _yaml_format:

Recipe YAML Format
==================

PyPTS accepts recipe language ``2.0.0``. Exact fields, types, required status,
defaults, aliases, and discriminator values are generated from the production
models in the :doc:`_generated/recipe_language_reference`. The downloadable
:download:`JSON Schema <_generated/recipe_language.schema.json>` describes the
same contract.

A complete maintained example is included below. This file is parsed by the
test suite with the production parser.

.. literalinclude:: _examples/recipe_v2.yml
   :language: yaml
   :caption: Complete recipe-language 2 example

Multi-document structure
------------------------

A recipe is one YAML stream containing multiple documents, separated by
``---``:

* The first document is a :ref:`recipe-v2-header`. Its required
  ``recipe_version`` is ``2.0.0`` and ``main_sequence`` names an existing
  sequence.
* Every later document is a :ref:`recipe-v2-sequence`. Sequence names must be
  unique, and at least one sequence is required.
* Each sequence owns ``setup_steps``, ``steps``, and ``teardown_steps`` lists.
  Step definitions use one of the exact, case-sensitive canonical
  discriminators listed in the generated reference.

Validation is strict. Unknown fields, wrong scalar types, duplicate YAML keys,
unsafe YAML tags, missing required fields, invalid sequence references, and
unsupported versions produce diagnostics. PyPTS does not repair or silently
normalize legacy syntax.

Variables and mappings
----------------------

``globals`` belong to the recipe header and are available throughout the run.
``locals`` belong to one active sequence. ``parameters`` and ``outputs`` are
currently reserved metadata dictionaries; the runtime does not automatically
bind nested-sequence inputs or outputs from them.

Every input mapping has an explicit ``type``:

.. code-block:: yaml

   input_mapping:
     literal: {type: direct, value: 12}
     repeated: {type: direct, value: [1, 2], indexed: true}
     from_local: {type: local, local_name: expected}
     from_global: {type: global, global_name: target}
     callback: {type: method, value: normalize}

The exact input structures are :ref:`recipe-v2-input-direct`,
:ref:`recipe-v2-input-local`, :ref:`recipe-v2-input-global`, and
:ref:`recipe-v2-input-method`. Indexed direct inputs must contain lists, and
all indexed inputs on one step must have equal lengths.

Output mappings also require an explicit ``type``. ``passfail``, ``equals``,
and ``range`` contribute verdicts; all configured verdict checks must pass.
``passthrough`` consumes an already-computed result and must be the only
verdict mapping on a step. ``local`` and ``global`` store values, while
``image`` publishes report images. See the generated
:ref:`recipe-v2-output-passfail` through :ref:`recipe-v2-output-range`
definitions for exact fields.

On a step with an indexed input, output mappings are split between the iterations
and the wrapper. ``passfail``, ``equals``, ``range`` and ``image`` are evaluated
(or attached to the report) once per iteration, so each iteration gets its own
verdict row and its own images. ``local`` and ``global`` are stored once, by the
wrapper, and receive the **list** of per-iteration values — one entry per
iteration, in iteration order. An indexed step whose indexed lists are empty
skips and stores empty lists. ``indexed`` is an input-only field; it is rejected
on an output mapping.

Runtime-specific behavior
-------------------------

``PythonModuleStep`` resolves ``module`` relative to ``test_package`` when the
header supplies that package. Without ``test_package``, the runtime uses its
file-based module lookup. A method action requires ``method_name``.

``SequenceStep`` references another sequence in the same YAML stream.
``WaitStep`` requires a ``wait_time`` input. SSH steps require the connection
globals documented by the parser and must follow connect, upload, close order.
Exact step-specific fields are linked from the generated reference, beginning
with :ref:`recipe-v2-step-pythonmodulestep`.

Error handling applies to execution errors, not failed verdicts. A header-level
``continue_on_error`` overrides step-level values when present; ``critical``
errors still stop execution. Teardown steps run during sequence cleanup.

Serialization and readable examples
------------------------------------

``recipe_to_yaml()`` accepts a validated aggregate recipe definition and
returns deterministic multi-document YAML text without performing file I/O.
It emits aliases and model defaults, omits ``None``, and always writes explicit
document separators. Parsing that output recreates an equal aggregate
definition.

Serialization is formatting-destructive: comments, quoting choices, key
layout, and other source formatting are not retained. Maintained examples are
therefore kept readable by hand and may include comments. YamVIEW and
programmatic serialization produce normalized YAML instead.

Migrating version 1 recipes
---------------------------

Version 1 is rejected; there is no automatic migration command or runtime
compatibility path. To migrate a file:

1. Set the required header field to ``recipe_version: 2.0.0``.
2. Use exact canonical step names such as ``PythonModuleStep``, ``WaitStep``,
   and ``UserInteractionStep``. Lowercase spellings are invalid.
3. Add ``type: direct`` to every literal input mapping that previously relied
   on the implicit default. All input and output mappings are discriminated
   explicitly.
4. Remove sequence-level ``serial_number``. Use ``SerialNumberStep`` and a
   mapped global or local value when the run needs a serial number.
5. Add every now-required field, including header, sequence, and step
   descriptions, and remove unknown fields.
6. Validate the complete multi-document file. Strict validation reports all
   detected migration issues with paths and source positions; PyPTS never
   changes legacy spelling or meaning silently.

After migration, parse the source, serialize with ``recipe_to_yaml()``, and
parse again. Equal aggregate definitions establish semantic stability; byte
equality and preservation of source comments are intentionally not required.
