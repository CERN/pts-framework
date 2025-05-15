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

  name: Name of the recipe. Typically the project name.
  version: Allows for tracking different versions of the file
  description: A more complete description of this recipe
  main_sequence: Main # Optional: Name of the sequence to run by default. Defaults typically to "Main".
  globals: # Globals can be referenced and used from any step in the whole file
    global_name: value
    other_global: other_value
    # ...
  # tags:  # Optional tags (Currently commented out in code)
  #   key1: value1

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

*   **module** (str): Path to the Python file.
*   **action_type** (str): ``method``, ``read_attribute``, or ``write_attribute``.
*   **method_name** (str): Name of the method to call (if ``action_type`` is ``method``).
*   Inputs for ``read_attribute``: ``attribute_name``.
*   Inputs for ``write_attribute``: ``attribute_name``, ``attribute_value``.
*   Note: If ``action_type`` is ``method`` and the called function returns a non-dictionary value, the value is made available under the output key ``output``.

SequenceStep
------------

Executes another sequence defined within the same recipe file.

.. code-block:: yaml

   steptype: SequenceStep
   step_name: Run Subsequence
   sequence:
     type: internal # Or 'external' (external currently not implemented)
     name: MySubSequenceName # Name of sequence defined in another doc
   input_mapping:
     sub_param1: { type: global, global_name: global_var1 }
   output_mapping:
     sub_output: { type: local, local_name: sub_result }
     __result: { type: passthrough } # Propagates sub-sequence result

*   **sequence** (dict): Describes the sequence to run.
    *   ``type`` (str): Currently only ``internal`` is supported.
    *   ``name`` (str): The ``sequence_name`` of the sequence to execute.

UserInteractionStep
-------------------

Pauses execution to request input from the user via the UI.

.. code-block:: yaml

   steptype: UserInteractionStep
   step_name: Ask User
   input_mapping:
     message: { type: direct, value: "Please confirm." }
     image_path: { type: direct, value: "path/to/image.png" } # Optional
     options: { type: direct, value: ["Yes", "No", "Cancel"] }
   output_mapping:
     user_choice: { type: local, local_name: choice }
     choice_is_yes: { type: equals, value: "Yes" } # PASS if output == "Yes"

*   Inputs:
    *   ``message`` (str): The text prompt displayed to the user.
    *   ``image_path`` (str, optional): Path to an image file to display.
    *   ``options`` (list[str]): A list of button labels for the user to choose from.
*   Outputs: The step's raw output (available for mapping) is the string label of the button clicked by the user, under the key ``output``.

WaitStep
--------

Pauses execution for a specified duration.

.. code-block:: yaml

   steptype: WaitStep
   step_name: Pause Execution
   input_mapping:
     wait_time: { type: global, global_name: default_wait } # Example: use a global
     # wait_time: { type: direct, value: 5 } # Or direct value
   output_mapping: {} # WaitStep usually has no functional output

*   Input:
    *   ``wait_time`` (int or float): Duration to wait in seconds. Must be provided via ``input_mapping``. 