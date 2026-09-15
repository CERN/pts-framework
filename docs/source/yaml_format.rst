.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _yaml_format:

Recipe YAML Format
==================

A recipe is a multi-document YAML file. The first document is the header;
each subsequent document is a sequence.

Header
------

.. code-block:: yaml

   ---
   name: MyRecipe
   version: "1.0"
   description: One-line description.
   main_sequence: Main          # optional, defaults to "Main"
   test_package: my_pkg.tests   # optional; enables package-based module loading
   globals:
     my_var: value

Required header fields: ``name``, ``version``, ``description``, ``globals``.

Sequence
--------

.. code-block:: yaml

   ---
   sequence_name: Main
   parameters: []       # inputs when called as a subsequence (not yet supported)
   locals: {}           # variables scoped to this sequence
   outputs: []          # locals to expose as outputs (not yet supported)
   setup_steps: []
   steps:
     - ...
   teardown_steps: []

All seven keys are required (empty lists / dicts are fine).

Step common fields
------------------

.. code-block:: yaml

   steptype: PythonModule   # see table below
   step_name: My step
   description: optional
   skip: false              # optional, default false
   continue_on_error: true  # optional, default true; false ends the run on ERROR or FAIL

Step types
----------

.. list-table::
   :header-rows: 1

   * - ``steptype``
     - What it does
     - Status
   * - ``PythonModule``
     - Call a method in a Python module
     - Available
   * - ``UserInteraction``
     - Show a message + buttons; wait for operator response
     - Available
   * - ``Wait``
     - Sleep for N seconds
     - Available
   * - ``UserWrite``
     - Prompt operator to type a string (text-entry mode only)
     - Available
   * - ``UserLoading``
     - Prompt operator to pick a file or a folder (``select: file`` / ``folder``);
       the absolute path is the output
     - Available
   * - ``SSHConnectStep`` / ``SSHCloseStep``
     - Open / close an SSH connection
     - **Moved to HAL (Phase 3+)**
   * - ``UserRunMethodStep``
     - User-triggered method call
     - **Deprecated** — use ``UserInteraction`` + ``PythonModule``
   * - ``SequenceStep``
     - Run another sequence as a step
     - **Dropped**

.. note::
   Old recipes used ``PythonModuleStep``, ``UserInteractionStep``, ``WaitStep`` etc.
   The new names drop the ``Step`` suffix. See :ref:`migration_instructions` for details.

PythonModule
~~~~~~~~~~~~

.. code-block:: yaml

   steptype: PythonModule
   step_name: Run my test
   module: my_module.py        # filename; resolved against recipe dir or test_package
   action_type: method
   method_name: my_function
   input_mapping:
     arg1: { type: direct, value: 42 }
     arg2: { type: global, global_name: device_port }
     arg3: { type: local, local_name: result }
   output_mapping:
     passed: { type: passfail }
     value:  { type: local, local_name: result }

``action_type``: ``method`` only (``read_attribute`` / ``write_attribute`` are dropped).

UserInteraction
~~~~~~~~~~~~~~~

.. code-block:: yaml

   steptype: UserInteraction
   step_name: Confirm connection
   input_mapping:
     message: { type: direct, value: "Connect the device and click OK." }
     image_path: { type: direct, value: setup.png }   # optional
     options: { type: direct, value: [{ ok: ok }, { cancel: cancel }] }
   output_mapping:
     output: { type: equals, value: ok }

Wait
~~~~

.. code-block:: yaml

   steptype: Wait
   step_name: Settle time
   wait_time: '3'   # seconds as a string

UserWrite
~~~~~~~~~

.. code-block:: yaml

   steptype: UserWrite
   step_name: Enter serial number
   input_mapping:
     message: { type: direct, value: "Enter the device serial number:" }
   output_mapping:
     output: { type: global, global_name: serial_number }

Input mapping
-------------

Each entry maps a step input name to a source:

.. list-table::
   :header-rows: 1

   * - ``type``
     - Required extra key
     - Meaning
   * - ``direct`` (default)
     - ``value``
     - Literal value
   * - ``global``
     - ``global_name``
     - Recipe-level global variable
   * - ``local``
     - ``local_name``
     - Sequence-level local variable

Output mapping
--------------

.. list-table::
   :header-rows: 1

   * - ``type``
     - Extra keys
     - Meaning
   * - ``passfail``
     - —
     - Boolean output → PASS / FAIL
   * - ``equals``
     - ``value``
     - Exact match → PASS / FAIL
   * - ``range``
     - ``min``, ``max``
     - Inclusive range check → PASS / FAIL
   * - ``local``
     - ``local_name``
     - Store in local variable
   * - ``global``
     - ``global_name``
     - Store in global variable
   * - ``passthrough``
     - —
     - Propagate ``ResultType`` directly

If no ``passfail`` / ``equals`` / ``range`` mapping exists, the step finishes
as ``DONE`` (equivalent to PASS for aggregation purposes).

YAML pitfalls
-------------

- ``yes`` / ``no`` → Python ``True`` / ``False``. Quote them to keep as strings.
- ``None`` → the string ``"None"``. Use ``null`` for a YAML null value.
- Indentation determines structure — use consistent spaces, not tabs.
