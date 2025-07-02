.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _yaml_format:

####################
Recipe YAML Format
####################

The recipe file is a multi-document YAML file. The first document defines
the main recipe metadata and global variables, while subsequent documents
define individual sequences that make up the test flow.

Document 1: Main Recipe Configuration
======================================

.. code-block:: yaml
   :caption: Example Main Recipe Document

  ---
  name: Name of the recipe. Typically the project name.
  version: Allows for tracking different versions of the file
  recipe_version: Version of the recipe format specification. Use "1.1.0" or higher to enable continue_on_error functionality.
  description: A more complete description of this recipe
  main_sequence: Main # Optional: Name of the sequence to run by default. Defaults typically to "Main".
  test_package: my_package.tests # Optional: Python package containing test modules for PythonModuleStep
  continue_on_error: false # Global setting that controls whether execution continues after errors in non-critical steps. Defaults to false. When true, only errors in steps marked as critical: true will stop execution. Requires recipe_version 1.1.0 or higher.
  globals: # Globals can be referenced and used from any step in the whole file
    global_name: value
    other_global: other_value
    # ...
  # tags:  # Optional tags (Currently commented out in code)
  #   key1: value1

Main Recipe Configuration Fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*   **name** (str): Name of the recipe, typically the project name.
*   **version** (str): Version string for tracking different versions of the recipe.
*   **recipe_version** (str): Version of the recipe format specification. Use "1.1.0" or higher to enable continue_on_error functionality.
*   **description** (str): A detailed description of the recipe's purpose.
*   **main_sequence** (str, optional): Name of the sequence to run by default. Defaults to "Main".
*   **test_package** (str, optional): Python package containing test modules for ``PythonModuleStep``. When specified, ``PythonModuleStep`` uses resource-based module loading instead of file-based loading. See :ref:`resource_based_loading`.
*   **continue_on_error** (bool, optional): Global setting that controls whether execution continues after errors in non-critical steps. Defaults to ``false``. When ``true``, only errors in steps marked as ``critical: true`` will stop execution. Requires ``recipe_version`` 1.1.0 or higher.
*   **globals** (dict): Global variables that can be referenced from any step in the recipe.

.. _resource_based_loading:

Resource-Based Module Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``test_package`` is specified, ``PythonModuleStep`` loads test modules as Python package resources instead of files:

**Benefits:**
  * Modules are bundled with your package during distribution
  * No dependency on current working directory  
  * Uses Python's standard import mechanism
  * More reliable deployment

**Example:**

.. code-block:: yaml

   ---
   name: My Recipe
   test_package: my_project.tests
   globals: {}
   
   ---
   sequence_name: Main
   steps:
   - steptype: PythonModuleStep
     module: test_module.py  # Resolves to my_project.tests.test_module
     action_type: method
     method_name: my_test

**Package Structure Required:**

.. code-block:: text

   my_project/
   ├── __init__.py
   ├── tests/
   │   ├── __init__.py          # Required for Python package
   │   ├── test_module.py
   │   └── other_tests.py
   └── recipe.yaml

**Migration from File-Based:**
  * Add ``__init__.py`` files to make directories into packages
  * Add ``test_package`` field to recipe
  * Remove directory prefixes from module paths (use just the filename)
  * Install your package with ``pip install -e .``

--- # Separator for the next document

Document 2...N: Sequence Definition
===================================

Each subsequent document defines a sequence.

.. code-block:: yaml
   :caption: Example Sequence Document

   sequence_name: Name of the sequence. A sequence defines a list of steps
   description: Description of the sequence
   setup_steps: [] # Steps that run first and are used to setup environments. Typically utility steps necessary for the next ones to work properly.
   steps: [] # Main steps of the sequence. These are run in order by the execution environment
   teardown_steps: [] # Teardown steps are run even if there is an error during the run. This is to make sure we run some shutdown routines no matter what happens.
   locals: # List of variables local to the sequence in scope (contrasted with global variables defined in recipe document)
     local_name: local_value
     # ...
   parameters: [] # List of which locals can be set by the execution environment if this sequence is run as a subsequence
   outputs: [] # List of which locals are to be used as outputs of the sequence when run as a subsequence


Step Definition
===============

Each item in `setup_steps`, `steps`, and `teardown_steps` is a dictionary representing a Step.

.. code-block:: yaml
   :caption: Example Step Structure

   steptype: PythonModuleStep | UserInteractionStep | SequenceStep | WaitStep | ... # Determines the type of action
   step_name: Name of the step # A descriptive name for the step
   id: unique_id # Optional: A unique identifier. Defaults to a generated UUID.
   description: More details about the step # Optional: More details about the step's purpose.
   skip: false # Optional: If true, the step execution is skipped. Defaults to false.
   critical: false # Optional: If true, errors in this step will always stop execution, even when continue_on_error is enabled globally. Defaults to false. Requires recipe_version 1.1.0 or higher.
   # --- Fields specific to certain steptypes ---
   action_type: method # e.g., For PythonModuleStep: 'method', 'read_attribute', 'write_attribute'
   module: path/to/my_module.py # e.g., For PythonModuleStep: Path to the Python file
   method_name: my_function # e.g., For PythonModuleStep with action_type 'method': Name of the function to run
   # ... other specific fields depending on steptype ...
   # --- Input/Output Mapping ---
   input_mapping: {} # Defines how the step gets its input data. See below.
   output_mapping: {} # Defines how the step's output is processed. See below.


Key fields common to most steps:

*   ``steptype`` (str): Determines the type of action (e.g., ``PythonModuleStep``, ``SequenceStep``, ``UserInteractionStep``, ``WaitStep``). Specific step types may have additional required or optional fields.
*   ``step_name`` (str): A descriptive name for the step.
*   ``id`` (str, optional): A unique identifier. Defaults to a generated UUID.
*   ``description`` (str, optional): More details about the step's purpose.
*   ``skip`` (bool, optional): If ``true``, the step execution is skipped. Defaults to ``false``.
*   ``critical`` (bool, optional): If ``true``, errors in this step will always stop execution, even when ``continue_on_error`` is enabled globally. Defaults to ``false``. Requires ``recipe_version`` 1.1.0 or higher.
*   ``input_mapping`` (dict): Defines how the step gets its input data. See :ref:`input_mapping_details`.
*   ``output_mapping`` (dict): Defines how the step's output is processed and stored. See :ref:`output_mapping_details`.

.. _input_mapping_details:

Input Mapping Details (``input_mapping``)
------------------------------------------

The ``input_mapping`` dictionary maps internal step input names (e.g., argument names for a ``PythonModuleStep``) to data sources. The keys of ``input_mapping`` are the names the step internally uses for its inputs, and the values specify where that data comes from.

Each value in the ``input_mapping`` dictionary is *another* dictionary with the following keys:

*   ``type`` (str, optional): Source of the value. Must be one of ``direct``, ``local``, or ``global``. If omitted, defaults to ``direct``.
*   ``value``: Required if ``type`` is ``direct`` (or omitted). Provides the literal value directly.
*   ``local_name``: Required if ``type`` is ``local``. Specifies the name of the sequence's local variable to read from.
*   ``global_name``: Required if ``type`` is ``global``. Specifies the name of the recipe's global variable to read from.
*   ``indexed`` (bool, optional): Defaults to ``false``. If ``true`` for one or more inputs, the step becomes an ``IndexedStep`` internally. It runs multiple times, once for each item in the *shortest* input list marked as ``indexed: true``. Non-indexed inputs are repeated (their value is used as-is) for each run of the indexed step.

.. code-block:: yaml
   :caption: Example Input Mapping Options

   input_mapping:
     # Input 'arg1' gets the literal integer value 3 (type defaults to direct)
     arg1: {value: 3, indexed: false}

     # Input 'arg2' gets its value from the sequence's local variable 'my_local_var'
     arg2: {type: local, local_name: my_local_var, indexed: false}

     # Input 'arg3' gets its value from the recipe's global variable 'my_global_var'
     arg3: {type: global, global_name: my_global_var, indexed: false}

     # Input 'items_to_process' comes from a direct list.
     # Because indexed is true, the step will run 3 times.
     # Run 1: items_to_process = 1
     # Run 2: items_to_process = 2
     # Run 3: items_to_process = 3
     # Inputs arg1, arg2, arg3 will keep their mapped values for each of these runs.
     items_to_process: {type: direct, value: [1, 2, 3], indexed: true}

.. _output_mapping_details:

Output Mapping Details (``output_mapping``)
--------------------------------------------

The ``output_mapping`` dictionary defines how the step's raw output is processed, evaluated for pass/fail status, and stored back into variables. The keys of the ``output_mapping`` dictionary correspond to the keys in the step's raw output data (typically a dictionary). If the step produces a non-dictionary output (e.g., a ``PythonModuleStep`` method returns a single value like a boolean or number), it's treated as a dictionary with a single key ``output`` (e.g., ``{"output": returned_value}``).

Each value in the ``output_mapping`` dictionary is *another* dictionary specifying the action to take:

*   ``type`` (str): How to handle the output value associated with this key. Must be one of ``local``, ``global``, ``passfail``, ``equals``, ``range``, or ``passthrough``.
*   ``local_name``: Required if ``type`` is ``local``. The name of the sequence's local variable where this output value should be stored.
*   ``global_name``: Required if ``type`` is ``global``. The name of the recipe's global variable where this output value should be stored.
*   ``value``: Required if ``type`` is ``equals``. The target value for comparison. If the step's output value for this key equals ``value``, the check passes.
*   ``min``, ``max``: Required if ``type`` is ``range``. The inclusive lower (``min``) and upper (``max``) bounds for comparison. If the step's output value for this key falls within [min, max], the check passes.
*   ``passthrough``: Used to propagate a `ResultType` directly. This is often used with the implicit ``__result`` output key from a `SequenceStep` to propagate the overall status of the subsequence, or internally by `IndexedStep` to represent the aggregate result.

**Pass/Fail Determination:**

*   If any output key is mapped with ``type: passfail``, the boolean value of that output determines the step's Pass/Fail status.
*   If any output key is mapped with ``type: equals`` or ``type: range``, the comparison result determines the step's Pass/Fail status. If multiple such mappings exist, *all* must pass for the step to pass.
*   If *no* output keys are mapped to ``passfail``, ``equals``, or ``range``, the step automatically finishes with a status of ``DONE``, which is generally treated as equivalent to ``PASS``.

.. code-block:: yaml
   :caption: Example Output Mapping Options

   output_mapping:
     # Store the value associated with the output key 'result_data'
     # into the local variable 'my_local_result'.
     result_data: {type: local, local_name: my_local_result}

     # Store the value associated with the output key 'shared_value'
     # into the global variable 'my_global_result'.
     shared_value: {type: global, global_name: my_global_result}

     # Use the boolean value associated with the output key 'test_passed'
     # to determine if the step passes or fails.
     test_passed: {type: passfail}

     # Check if the value associated with the output key 'status_code'
     # is exactly equal to 200. If yes, pass; otherwise, fail.
     status_code: {type: equals, value: 200}

     # Check if the value associated with the output key 'measurement'
     # is between 3.0 and 6.5 (inclusive). If yes, pass; otherwise, fail.
     measurement: {type: range, min: 3.0, max: 6.5}

     # For SequenceStep: Propagate the overall Pass/Fail/Done status
     # of the subsequence using its implicit '__result' output.
     __result: { type: passthrough }

Specific Step Types
===================

PythonModuleStep
----------------

Executes Python code.

.. code-block:: yaml

   steptype: PythonModuleStep
   step_name: Call Python Function
   module: path/to/my_module.py
   action_type: method # Or 'read_attribute', 'write_attribute'
   method_name: my_function # Required if action_type is 'method'
   input_mapping:
     arg1: { type: direct, value: "hello" }
     arg2: { type: local, local_name: local_var1 }
     # For read_attribute:
     # attribute_name: { type: direct, value: "my_attr" }
     # For write_attribute:
     # attribute_name: { type: direct, value: "my_attr" }
     # attribute_value: { type: direct, value: 10 }
   output_mapping:
     result: { type: local, local_name: output_data }
     passed: { type: passfail } # Treats boolean output as pass/fail

*   **module** (str): Path to the Python module. If ``test_package`` is specified in the recipe, this should be just the filename (e.g., ``test_module.py``). Otherwise, this is a file path relative to the current working directory.
*   **action_type** (str): ``method``, ``read_attribute``, or ``write_attribute``.
*   **method_name** (str): Name of the method to call (if ``

Continue On Error Mechanism
============================

Starting with ``recipe_version`` 1.1.0, the pypts framework supports a "Continue On Error" mechanism that allows test execution to continue even after encountering errors in non-critical steps.

Global Setting
--------------

The ``continue_on_error`` field in the main recipe configuration enables this functionality:

.. code-block:: yaml

   ---
   name: My Recipe
   recipe_version: 1.1.0
   continue_on_error: true  # Enable continue on error globally
   # ... other fields

When ``continue_on_error`` is ``true``:
- Errors in steps marked as ``critical: false`` (default) will not stop sequence execution
- Errors in steps marked as ``critical: true`` will still stop sequence execution
- All errors are still logged and reported

When ``continue_on_error`` is ``false`` (default):
- Any error in any step stops sequence execution (legacy behavior)
- The ``critical`` field has no effect

Step-Level Critical Flag
------------------------

Individual steps can be marked as critical using the ``critical`` field:

.. code-block:: yaml

   steps:
   - steptype: PythonModuleStep
     step_name: Optional Diagnostic Test
     critical: false  # Default - errors won't stop execution if continue_on_error is true
     # ... other fields

   - steptype: PythonModuleStep
     step_name: Essential Safety Check
     critical: true   # Errors will always stop execution
     # ... other fields

Behavior Matrix
---------------

The interaction between ``continue_on_error`` and ``critical`` settings:

+-------------------+------------------+------------------------+
| continue_on_error | step critical    | Error Behavior         |
+===================+==================+========================+
| false             | false (default)  | Stop execution         |
+-------------------+------------------+------------------------+
| false             | true             | Stop execution         |
+-------------------+------------------+------------------------+
| true              | false (default)  | Continue execution     |
+-------------------+------------------+------------------------+
| true              | true             | Stop execution         |
+-------------------+------------------+------------------------+

Use Cases
---------

This mechanism is useful for:

- **Diagnostic Tests**: Run optional diagnostic steps that shouldn't fail the entire test if they encounter issues
- **Data Collection**: Continue gathering test data even if some measurements fail
- **Graceful Degradation**: Allow test sequences to complete as much as possible before stopping
- **Critical Safety Checks**: Ensure essential safety or validation steps always stop execution on failure

Example
-------

.. code-block:: yaml

   ---
   name: Hardware Test Suite
   recipe_version: 1.1.0
   continue_on_error: true
   globals: {}

   ---
   sequence_name: Main
   steps:
   - steptype: PythonModuleStep
     step_name: Initialize Hardware
     critical: true          # Setup failure should stop everything
     # ... configuration

   - steptype: PythonModuleStep
     step_name: Optional Calibration
     critical: false         # Calibration failure shouldn't stop the test
     # ... configuration

   - steptype: PythonModuleStep
     step_name: Core Functionality Test
     critical: true          # Main test failure should stop execution
     # ... configuration

   - steptype: PythonModuleStep
     step_name: Performance Metrics
     critical: false         # Metrics failure shouldn't stop cleanup
     # ... configuration

   teardown_steps:
   - steptype: PythonModuleStep
     step_name: Hardware Cleanup
     critical: true          # Cleanup failure is critical for safety
     # ... configuration

In this example:
- If "Initialize Hardware" fails, execution stops immediately
- If "Optional Calibration" fails, execution continues to "Core Functionality Test"
- If "Core Functionality Test" fails, execution stops before "Performance Metrics"
- If "Performance Metrics" fails, execution continues to teardown
- If "Hardware Cleanup" fails, it's reported as a critical failure