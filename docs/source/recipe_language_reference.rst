.. SPDX-FileCopyrightText: 2026 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0
..
.. Generated from recipe_language.schema.json. Do not edit manually.

Recipe Language 2.0 Reference
=============================

This page is generated from the tracked aggregate JSON Schema. It describes
the accepted future recipe language model; production execution still uses
the version 1 language until Phase 6 integration is complete.

:download:`Download the JSON Schema <_static/recipe_language.schema.json>`.

See :doc:`recipe_language_architecture` for parsing, semantic rules,
documentation maintenance, and the planned YamVIEW and sequencer flows.

Documents
---------

.. _recipe-v2-header:

RecipeHeader
~~~~~~~~~~~~

The first YAML document, identifying a recipe and its entry sequence.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``continue_on_error``
     - ``bool | None``
     - optional; default ``null``
     - Recipe-wide error policy. Example: ``false``.
   * - ``description``
     - ``str``
     - required
     - Purpose of the recipe. Example: ``"Acceptance tests."``.
   * - ``globals``
     - ``object``
     - required
     - Recipe-wide variables. Example: ``{}``.
   * - ``main_sequence``
     - ``str``
     - required
     - Sequence where execution begins. Example: ``"Main"``.
   * - ``name``
     - ``str``
     - required
     - Human-readable recipe name. Example: ``"Hardware acceptance"``.
   * - ``recipe_version``
     - ``'2.0.0'``
     - required
     - Version of the recipe language contract. Example: ``"2.0.0"``.
   * - ``report``
     - ``'overwrite' | 'append'``
     - optional; default ``"overwrite"``
     - Report file mode. Example: ``"overwrite"``.
   * - ``report_name_include_serial``
     - ``bool``
     - optional; default ``false``
     - Include the serial number in the report name. Example: ``false``.
   * - ``test_package``
     - ``str | None``
     - optional; default ``null``
     - Package containing recipe test modules. Example: ``"acceptance"``.
   * - ``version``
     - ``str``
     - required
     - Version of this recipe. Example: ``"1.0"``.

.. _recipe-v2-sequence:

Sequence
~~~~~~~~

One named executable sequence document.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``description``
     - ``str``
     - required
     - Purpose of the sequence. Example: ``"Main sequence."``.
   * - ``locals``
     - ``object``
     - required
     - Variables local to the sequence. Example: ``{}``.
   * - ``outputs``
     - ``object``
     - required
     - Reserved sequence output metadata. Example: ``{}``.
   * - ``parameters``
     - ``object``
     - required
     - Reserved sequence input metadata. Example: ``{}``.
   * - ``sequence_name``
     - ``str``
     - required
     - Unique sequence name. Example: ``"Main"``.
   * - ``setup_steps``
     - ``list[Step]``
     - required
     - Steps run before the main steps. Example: ``[]``.
   * - ``steps``
     - ``list[Step]``
     - required
     - Ordered main steps. Example: ``[]``.
   * - ``teardown_steps``
     - ``list[Step]``
     - required
     - Steps run during teardown. Example: ``[]``.

Nested structures
-----------------

.. _recipe-v2-structure-internalsequencereference:

InternalSequenceReference
~~~~~~~~~~~~~~~~~~~~~~~~~

Reference to another sequence in this recipe.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``name``
     - ``str``
     - required
     - Target sequence name. Example: ``"Calibration"``.
   * - ``type``
     - ``'internal'``
     - required
     - Reference kind. Example: ``"internal"``.

.. _recipe-v2-structure-filedestination:

FileDestination
~~~~~~~~~~~~~~~

Destination used by a file-loading step.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``type``
     - ``'local' | 'global'``
     - required
     - Variable scope. Example: ``"local"``.
   * - ``variable``
     - ``str``
     - required
     - Destination variable name. Example: ``"selected_file"``.

.. _recipe-v2-structure-uploadfile:

UploadFile
~~~~~~~~~~

One local-to-remote SSH upload pair.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``local``
     - ``str``
     - required
     - Local file or package resource. Example: ``"bin/tool"``.
   * - ``remote``
     - ``str``
     - required
     - Remote destination path. Example: ``"/tmp/tool"``.

Common step fields
------------------

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``continue_on_error``
     - ``bool``
     - optional; default ``false``
     - Per-step error policy. Example: ``false``.
   * - ``critical``
     - ``bool``
     - optional; default ``false``
     - Stop on error when policy permits continuation. Example: ``false``.
   * - ``description``
     - ``str``
     - required
     - Purpose of the step. Example: ``"Run a test operation."``.
   * - ``id``
     - ``str | None``
     - optional; default ``null``
     - Optional stable step identifier. Example: ``"test-1"``.
   * - ``input_mapping``
     - ``dict[str, InputMapping]``
     - optional
     - Named input sources. Example: ``{}``.
   * - ``output_mapping``
     - ``dict[str, OutputMapping]``
     - optional
     - Named verdicts and destinations. Example: ``{}``.
   * - ``skip``
     - ``bool``
     - optional; default ``false``
     - Skip execution. Example: ``false``.
   * - ``step_name``
     - ``str``
     - required
     - Human-readable step name. Example: ``"Run test"``.

Authorable steps
----------------

.. _recipe-v2-step-pythonmodulestep:

PythonModuleStep
~~~~~~~~~~~~~~~~

Calls a method or reads/writes an attribute in a Python module.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``action_type``
     - ``'method' | 'read_attribute' | 'write_attribute'``
     - required
     - Operation performed on the Python module. Example: ``"method"``.
   * - ``method_name``
     - ``str | None``
     - optional; default ``null``
     - Method name for method actions. Example: ``"run"``.
   * - ``module``
     - ``str``
     - required
     - Python module path. Example: ``"tests.py"``.
   * - ``steptype``
     - ``'PythonModuleStep'``
     - required
     - Canonical registered step type. Example: ``"PythonModuleStep"``.

.. _recipe-v2-step-sshclosestep:

SSHCloseStep
~~~~~~~~~~~~

Closes the SSH client stored in recipe globals.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``steptype``
     - ``'SSHCloseStep'``
     - required
     - Canonical registered step type. Example: ``"SSHCloseStep"``.

.. _recipe-v2-step-sshconnectstep:

SSHConnectStep
~~~~~~~~~~~~~~

Opens the SSH client stored in recipe globals.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``steptype``
     - ``'SSHConnectStep'``
     - required
     - Canonical registered step type. Example: ``"SSHConnectStep"``.

.. _recipe-v2-step-sshuploadstep:

SSHUploadStep
~~~~~~~~~~~~~

Uploads files through an SSH connection.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``files``
     - ``list[UploadFile]``
     - required
     - Local and remote file pairs to upload. Example: ``[{"local": "bin/tool", "remote": "/tmp/tool"}]``.
   * - ``local_package``
     - ``str | None``
     - optional; default ``null``
     - Optional package containing local resources. Example: ``"my_package"``.
   * - ``permissions``
     - ``int | str | None``
     - optional; default ``null``
     - Optional remote permissions. Example: ``"0755"``.
   * - ``skip_if_sha256_match``
     - ``bool``
     - optional; default ``false``
     - Skip files whose remote checksum matches. Example: ``false``.
   * - ``steptype``
     - ``'SSHUploadStep'``
     - required
     - Canonical registered step type. Example: ``"SSHUploadStep"``.

.. _recipe-v2-step-sequencestep:

SequenceStep
~~~~~~~~~~~~

Runs another sequence as a step.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``sequence``
     - ``InternalSequenceReference``
     - required
     - Internal sequence reference. Example: ``{"name": "Calibration", "type": "internal"}``.
   * - ``steptype``
     - ``'SequenceStep'``
     - required
     - Canonical registered step type. Example: ``"SequenceStep"``.

.. _recipe-v2-step-serialnumberstep:

SerialNumberStep
~~~~~~~~~~~~~~~~

Captures the device serial number.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``steptype``
     - ``'SerialNumberStep'``
     - required
     - Canonical registered step type. Example: ``"SerialNumberStep"``.

.. _recipe-v2-step-userinteractionstep:

UserInteractionStep
~~~~~~~~~~~~~~~~~~~

Displays an operator interaction prompt.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``steptype``
     - ``'UserInteractionStep'``
     - required
     - Canonical registered step type. Example: ``"UserInteractionStep"``.

.. _recipe-v2-step-userloadingstep:

UserLoadingStep
~~~~~~~~~~~~~~~

Prompts the operator to select a file.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``file_save_location``
     - ``FileDestination | None``
     - optional; default ``null``
     - Local or global destination for the selected file. Example: ``{"type": "local", "variable": "selected_file"}``.
   * - ``steptype``
     - ``'UserLoadingStep'``
     - required
     - Canonical registered step type. Example: ``"UserLoadingStep"``.

.. _recipe-v2-step-userrunmethodstep:

UserRunMethodStep
~~~~~~~~~~~~~~~~~

Optionally runs a Python method after an operator response.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``action_type``
     - ``str | None``
     - optional; default ``null``
     - Optional Python action type. Example: ``"method"``.
   * - ``method_name``
     - ``str | None``
     - optional; default ``null``
     - Optional Python method name. Example: ``"run"``.
   * - ``module``
     - ``str | None``
     - optional; default ``null``
     - Optional Python module path. Example: ``"tests.py"``.
   * - ``steptype``
     - ``'UserRunMethodStep'``
     - required
     - Canonical registered step type. Example: ``"UserRunMethodStep"``.
   * - ``trigger_response``
     - ``str | list[any] | object | None``
     - optional; default ``null``
     - Operator response that triggers execution. Example: ``"run"``.

.. _recipe-v2-step-userwritestep:

UserWriteStep
~~~~~~~~~~~~~

Writes an operator-provided value to a configured destination.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``steptype``
     - ``'UserWriteStep'``
     - required
     - Canonical registered step type. Example: ``"UserWriteStep"``.

.. _recipe-v2-step-waitstep:

WaitStep
~~~~~~~~

Waits for a non-negative duration in seconds.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``steptype``
     - ``'WaitStep'``
     - required
     - Canonical registered step type. Example: ``"WaitStep"``.

Input mappings
--------------

.. _recipe-v2-input-direct:

DirectInput
~~~~~~~~~~~

Provides a literal value.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``indexed``
     - ``bool``
     - optional; default ``false``
     - Expand a list into indexed steps. Example: ``false``.
   * - ``type``
     - ``'direct'``
     - required
     - Input source type. Example: ``"direct"``.
   * - ``value``
     - ``any``
     - required
     - Literal input value. Example: ``1``.

.. _recipe-v2-input-global:

GlobalInput
~~~~~~~~~~~

Reads a recipe-global variable.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``global_name``
     - ``str``
     - required
     - Global variable name. Example: ``"global_value"``.
   * - ``type``
     - ``'global'``
     - required
     - Input source type. Example: ``"global"``.

.. _recipe-v2-input-local:

LocalInput
~~~~~~~~~~

Reads a sequence-local variable.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``local_name``
     - ``str``
     - required
     - Local variable name. Example: ``"local_value"``.
   * - ``type``
     - ``'local'``
     - required
     - Input source type. Example: ``"local"``.

.. _recipe-v2-input-method:

MethodInput
~~~~~~~~~~~

Resolves a method reference for the step.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``type``
     - ``'method'``
     - required
     - Input source type. Example: ``"method"``.
   * - ``value``
     - ``any``
     - required
     - Method reference. Example: ``"helper"``.

Output mappings
---------------

.. _recipe-v2-output-equals:

EqualsOutput
~~~~~~~~~~~~

Passes when the output equals the configured value.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``type``
     - ``'equals'``
     - required
     - Output mapping type. Example: ``"equals"``.
   * - ``value``
     - ``any``
     - required
     - Expected value. Example: ``3``.

.. _recipe-v2-output-global:

GlobalOutput
~~~~~~~~~~~~

Stores the output in a recipe-global variable.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``global_name``
     - ``str``
     - required
     - Global destination variable. Example: ``"saved"``.
   * - ``type``
     - ``'global'``
     - required
     - Output mapping type. Example: ``"global"``.

.. _recipe-v2-output-image:

ImageOutput
~~~~~~~~~~~

Publishes an image output for presentation.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``type``
     - ``'image'``
     - required
     - Output mapping type. Example: ``"image"``.

.. _recipe-v2-output-local:

LocalOutput
~~~~~~~~~~~

Stores the output in a sequence-local variable.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``local_name``
     - ``str``
     - required
     - Local destination variable. Example: ``"saved"``.
   * - ``type``
     - ``'local'``
     - required
     - Output mapping type. Example: ``"local"``.

.. _recipe-v2-output-passfail:

PassFailOutput
~~~~~~~~~~~~~~

Interprets the output as a pass/fail verdict.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``type``
     - ``'passfail'``
     - required
     - Output mapping type. Example: ``"passfail"``.

.. _recipe-v2-output-passthrough:

PassthroughOutput
~~~~~~~~~~~~~~~~~

Uses the nested result without adding a verdict.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``type``
     - ``'passthrough'``
     - required
     - Output mapping type. Example: ``"passthrough"``.

.. _recipe-v2-output-range:

RangeOutput
~~~~~~~~~~~

Passes when the output is within an inclusive range.

.. list-table:: Fields
   :header-rows: 1
   :widths: 18 19 25 38

   * - Field
     - Type
     - Requirement
     - Description and example
   * - ``max``
     - ``any``
     - required
     - Maximum accepted value. Example: ``4``.
   * - ``min``
     - ``any``
     - required
     - Minimum accepted value. Example: ``1``.
   * - ``type``
     - ``'range'``
     - required
     - Output mapping type. Example: ``"range"``.
