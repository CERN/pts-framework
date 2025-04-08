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

   name: MyRecipeName
   description: A detailed description of what this recipe does.
   version: 1.0.0
   globals:
     global_var1: value1
     global_var2: 123
   # tags:  # Optional tags (Currently commented out in code)
   #   key1: value1

--- # Separator for the next document

Document 2...N: Sequence Definition
===================================

Each subsequent document defines a sequence.

.. code-block:: yaml
   :caption: Example Sequence Document

   sequence_name: Main # Or any other sequence name
   parameters: # Inputs expected by this sequence when called as a step
     param1: description
     param2: description
   locals: # Variables local to this sequence's execution scope
     local_var1: default_value
     some_list: []
   outputs: # List of local variables to be returned as output
     - local_var1
     - output_data
   setup_steps: # Steps run before the main steps
     - steptype: ... # Step definition (see below)
       # ... other step fields
   steps: # Main execution steps
     - steptype: PythonModuleStep
       step_name: Call Python Function
       # ... (step fields shown below)
     # ... more steps
   teardown_steps: # Steps run after main steps, even if errors occurred
     - steptype: ... # Step definition
       # ... other step fields


Step Definition
===============

Each item in `setup_steps`, `steps`, and `teardown_steps` is a dictionary representing a Step. Key fields:

*   ``steptype`` (str): Determines the type of action (e.g., ``PythonModuleStep``, ``SequenceStep``, ``UserInteractionStep``, ``WaitStep``).
*   ``step_name`` (str): A descriptive name for the step.
*   ``id`` (str, optional): A unique identifier. Defaults to a generated UUID.
*   ``description`` (str, optional): More details about the step's purpose.
*   ``skip`` (bool, optional): If ``true``, the step execution is skipped. Defaults to ``false``.
*   ``input_mapping`` (dict): Defines how the step gets its input data. See :ref:`input_mapping_details`.
*   ``output_mapping`` (dict): Defines how the step's output is processed and stored. See :ref:`output_mapping_details`.

.. _input_mapping_details:

Input Mapping Details (``input_mapping``)
------------------------------------------

Maps internal step input names to data sources. Each value is a dictionary:

*   ``type`` (str): Source of the value (``direct``, ``local``, ``global``).
*   ``value``: Required if ``type`` is ``direct``. The literal value.
*   ``local_name``: Required if ``type`` is ``local``. Name of the sequence's local variable.
*   ``global_name``: Required if ``type`` is ``global``. Name of the recipe's global variable.
*   ``indexed`` (bool, optional): If ``true`` for one or more inputs, the step becomes an ``IndexedStep``. It runs multiple times, once for each item in the shortest input list marked as indexed. Non-indexed inputs are repeated for each run.

.. _output_mapping_details:

Output Mapping Details (``output_mapping``)
--------------------------------------------

Maps the step's raw output keys to actions or result evaluations. Each value is a dictionary:

*   ``type`` (str): How to handle the output (``passthrough``, ``passfail``, ``equals``, ``range``, ``local``, ``global``).
*   ``value``: Required for ``equals``. The target value for comparison.
*   ``min``, ``max``: Required for ``range``. The inclusive bounds for comparison.
*   ``local_name``: Required for ``local``. Target local variable name.
*   ``global_name``: Required for ``global``. Target global variable name.

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
     wait_time: { type: direct, value: 5 } # Wait time in seconds
   output_mapping: {} # WaitStep usually has no functional output

*   Input:
    *   ``wait_time`` (int or float): Duration to wait in seconds. 