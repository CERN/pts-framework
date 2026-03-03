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
  globals: # Globals can be referenced and used from any step in the whole file
    global_name: value
    other_global: other_value
    continue_on_error: false # Optional Global variable that controls whether execution continues after errors in non-critical steps if it exists. Overrides individual step "continue_on_error": true will stop execution. Requires recipe_version 1.1.0 or higher.
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
*   **report** (str, optional): Selects whether new test results should overwrite the previous report (``overwrite``) or should be added to the report file (``append``). Defaults to ``overwrite``.
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

.. note::
  Notice the indentation inside ``steps`` and the ``-`` in front of the step. Adding this - is crucial for the functionality of the recipe.


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


.. _step_definition_details:

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
   continue_on_error: False


Key fields common to most steps:

*   ``steptype`` (str): Determines the type of action (e.g., ``PythonModuleStep``, ``SequenceStep``, ``UserInteractionStep``, ``WaitStep``). Specific step types may have additional required or optional fields.
*   ``step_name`` (str): A descriptive name for the step.
*   ``id`` (str, optional): A unique identifier. Defaults to a generated UUID.
*   ``description`` (str, optional): More details about the step's purpose.
*   ``skip`` (bool, optional): If ``true``, the step execution is skipped. Defaults to ``false``.
*   ``critical`` (bool, optional): If ``true``, errors in this step will always stop execution, even when ``continue_on_error`` is enabled globally. Defaults to ``false``. Requires ``recipe_version`` 1.1.0 or higher.
*   ``input_mapping`` (dict): Defines how the step gets its input data. See :ref:`input_mapping_details`.
*   ``output_mapping`` (dict): Defines how the step's output is processed and stored. See :ref:`output_mapping_details`.
*   ``continue_on_error`` (bool,optional): Defines wheter this specific step will stop the test if failed. Default to ``false``.


.. _input_mapping_details:


Input Mapping Details (``input_mapping``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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


Step formatting
===================

There are multiple ways of formatting the recipe YAML file. 
One way of doing it is compressing the arguments of ``input_mapping`` and ``output_mapping``. An example is visible below.

.. code-block:: yaml

   steptype: PythonModuleStep
   step_name: Call Python Function
   description: Describe the action of the step
   module: my_module.py 
   action_type: method
   method_name: my_function
   input_mapping:
     arg1: { type: direct, value: "hello" }
     arg2: { type: local, local_name: local_var1 }
   output_mapping:
     result: { type: local, local_name: output_data }
     passed: { type: passfail } # Treats boolean output as pass/fail

The other way of formatting each step is to expand the outputs so we get

.. code-block:: yaml

   steptype: PythonModuleStep
   step_name: Call Python Function
   description: Describe the action of the step
   module: my_module.py 
   action_type: method
   method_name: my_function
   input_mapping:
     arg1:
      type: direct
      value: "hello"
     arg2:
      type: local
      local_name: local_var1
   output_mapping:
     result:
      type: local
      local_name: output_data
     passed:
      type: passfail # Treats boolean output as pass/fail

In this formatting, the indentation of input elements like ``type`` and ``value`` are important to achieve similar structure. The indentation scheme is of same structure as python programming.
Both work as intendedn and either can be used, even mixed together. 

Specific Step Types
===================

Given the required different functionalities required for testing, multiple step types were developed. This section descrives the types, functionality, format and what input/output. The following are the available steptypes:
 - PythonModuleStep
 - WaitStep
 - UserInteractionStep
 - SSHConnectStep
 - UserLoadingStep
 - UserRunMethodStep
 - UserWriteStep
 - SerialNumberStep

Each has its own template of required elements but with overlapping types of elements.
The elements ``step_name`` and ``description`` are not explained further in this section as they're descriptive elements for reporting and GUI with no change between steps. 

.. note::
  The optional arguments ``critical``, ``skip`` and ``continue_on_error`` all apply to the following step types. Check :ref:`_step_definition_details` for information on ``skip`` and ``critical`` and :ref:`_continue_on_error_details` for information on ``continue_on_error``.



PythonModuleStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Executes Python method or code. 

.. code-block:: yaml

   steptype: PythonModuleStep
   step_name: Call Python Function #the name of the 
   description: Describe the action of the step
   module: my_module.py #the name of the file with the test initialization
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

*   ``module`` (str):Name of the Python module. If ``test_package`` is specified in the recipe, this should be just the filename (e.g., ``test_module.py``).
*   ``action_type`` (str): ``method``, ``read_attribute``, or ``write_attribute``.
*   ``method_name`` (str): Name of the method to call. 
*   ``input_mapping`` (dictionary): Inputs to the method. Each input(``arg``) is required to have a ``type``. 
*   ``output_mapping`` (dictionary): outputs of the method. Each output(``arg``) is required to have a ``type``. If multiple outputs, ensure the returned output of method has same label, example ``passed`` as given in output_mapping.


WaitStep
~~~~~~~~~~~~~~~~~~~~

Waits the specified period of time in seconds before next step starts.

.. code-block:: yaml

  steptype: WaitStep
  step_name: Wait for 3s
  description: Waiting 3 seconds on this step
  skip: false
  input_mapping:
    wait_time:
      value: '3'

*   ``steptype`` (str): Determines the type of action.
*  ``input_mapping`` (dict): Inputs the desired period of time to wait before moving on to next step.


UserInteractionStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Allows for user to interact with gui through action on buttons. It allows for adding many buttons but it requires at least one button if test is to be successful. 

.. code-block:: yaml


  steptype: UserInteractionStep
  step_name: Start test
  input_mapping:
    message: {type: direct, value: "Connect the WRS as shown and click Yes", indexed: false}
    image_path: {type: direct, value: "test.png"}
    options: {type: direct, value: [{'yes': 'yes'},{two: 'no'}], indexed: false}
  output_mapping:
    output: {type: equals, value: "yes"}

*   ``steptype`` (str): Determines the type of action.
*  ``input_mapping`` (dict): Inputs the desired period of time to wait before moving on to next step.
*  ``message`` (dict): can write a message that is expected to be relevant for user to do before 
*  ``options`` (dict): options to add buttons. Multiple buttons can be added and cycled through by setting ``indexed`` to `True`. 
These buttons on options are relevant for describing the action the button should take. The name of buttons are determined through key-value pairs as seen in the ``options``. It contains the keys 'yes' and two with each of their values.
The key ``cancel`` or ``'cancel'`` are both hardcoded to cancel a step and stop the entire test and can therefore not be used. keys do not need to be strings to operate unless the keys are ``yes`` or ``no`` as these are compiled to `True` and `False`.

*   ``image_path`` (dict, optional): shows the specified image on gui during this step. Path is not required to find the image, as long as it is one layer deep inside the working directory. 
*   ``output_mapping`` (dict): outputs of the method. Each output(``arg``) is required to have a ``type``.



SSHConnectStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Allows to setup a SSH connection to be used globally during the test.

.. code-block:: yaml

  steptype: SSHConnectStep
  step_name: Find the SSH client connection
  description: Asking user to find the file needed
  continue_on_error: false

*   ``steptype`` (str): Determines the type of action.

This steptype has certain **requirements** to which globals exist. The following required are
*  ``ssh_client: None`` : The variable holding the opened paramiko client to be called in functions.
*  ``host: 129`` :The SSH hostname or IP address.
*  ``user: username``:The SSH username
*  ``password: None`` :Password for SSH auth. 
*  ``private_key: 'path/to/your/key_file'`` :The path to key file. important if no password is given.
*  ``port: None``(int) : SSH port (default: 22).

If password is not supplied, the function will automatically use ``private_key`` as verification.

**Important**. When this steptype is used, **always** put steptype ``SSHCloseStep`` under ``teardownsteps``. It can be placed multiple times, but always one in ``teardownsteps``.

.. code-block:: yaml

  teardown_steps:
  - steptype: SSHCloseStep
    step_name: Closes the SSH client

To use the SSH client, add ``ssh_client`` to input_mapping.

.. code-block:: yaml

     target:
      type: global
      global_name: ssh_client

An Example of using it for a function can be seen below.

.. code-block:: python
  def write_a_simple_filessh(target):
    target.exec_command("echo 'Hello World' > myfile.txt")

    return (True)



UserLoadingStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Used to load a file to be used somewhere else. Could fx be a calibration file or configuration file for certain instruments. 

.. code-block:: yaml

  steptype: UserLoadingStep
  step_name: Load config file
  description: Asking user to find the file needed
  input_mapping:
    message:
      type: direct
      value: 'Find the specified file'
    image_path: 
      type: direct
      value: lego2.jpg
    options:
      type: direct
      value:
      - cancel: 'cancel'
      - file: 'next'
  output_mapping:
    output:
      type: passfail
  file_save_location: 
    type: global
    variable: file

*   ``steptype`` (str): Determines the type of action.
*  ``input_mapping`` (dict): Inputs the desired period of time to wait before moving on to next step.
*  ``message`` (dict): can write a message that is expected to be relevant for user to do before 
*  ``options`` (dict): options to add buttons. Multiple buttons can be added and cycled through by setting ``indexed`` to `True`. 
These buttons on options are relevant for describing the action the button should take. The name of buttons are determined through key-value pairs as seen in the ``options``. It contains the keys 'yes' and two with each of their values.
The key ``cancel`` or ``'cancel'`` are both hardcoded to cancel a step and stop the entire test and can therefore not be used. keys do not need to be strings to operate unless the keys are ``yes`` or ``no`` as these are compiled to `True` and `False`.

*   ``image_path`` (dict, optional): shows the specified image on gui during this step. Path is not required to find the image, as long as it is one layer deep inside the working directory. 
*   ``output_mapping`` (dict): outputs of the method. Each output(``arg``) is required to have a ``type``.
*   ``file_save_location`` (dict, optional): Variable to save the loaded file. . If not existing, will default to ``type: local, variable: file``. 


UserRunMethodStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Executes a method after interacting with next button. Step type is expected to be used in scenarios where an action by the operator is required before running a method.

.. code-block:: yaml

  steptype: UserRunMethodStep
  step_name: Running the specified method
  description: Runs the specified method
  action_type: method
  module: example_tests.py
  input_mapping:
    message:
      type: direct
      value: 'Find the specified file'
    options:
      type: direct
      value:
      - cancel: 'cancel'
      - run: 'Run'
    image_path: 
      type: direct
      value: test.jpg
    method_name:
      type: method
      value: 'is_PSU_disconnected'
    argument1:
      type: global
      global_name: test
    argument2:
      type: local
      local_name: testing
    argument3:
      type: direct
      value: 5
  output_mapping:
    output:
      type: passfail
  trigger_response: "run"

*   ``steptype`` (str): Determines the type of action.
*  ``action_type`` (str): ``method``, ``read_attribute``, or ``write_attribute``.
*   ``module`` (str):Name of the Python module. If ``test_package`` is specified in the recipe, this should be just the filename (e.g., ``test_module.py``).
*  ``input_mapping`` (dict): Inputs the desired period of time to wait before moving on to next step.
*  ``message`` (dict): can write a message that is expected to be relevant for user to do before 
*  ``options`` (dict): options to add buttons. Multiple buttons can be added and cycled through by setting ``indexed`` to `True`. 
These buttons on options are relevant for describing the action the button should take. The name of buttons are determined through key-value pairs as seen in the ``options``. It contains the keys 'yes' and two with each of their values.
The key ``cancel`` or ``'cancel'`` are both hardcoded to cancel a step and stop the entire test and can therefore not be used. keys do not need to be strings to operate unless the keys are ``yes`` or ``no`` as these are compiled to `True` and `False`.
*   ``image_path`` (dict, optional): shows the specified image on gui during this step. Path is not required to find the image, as long as it is one layer deep inside the working directory. 
*   ``method_name`` (dict): specifies the method to run.
*   ``argument1-3`` (dict): Any dict that is not message, option or image path in input mapping will be considered input to method. multiple inputs are possible with them being ordered from top to bottom as inputs to the method.
*   ``output_mapping`` (dict): outputs of the method. Each output(``arg``) is required to have a ``type``.
*   ``trigger_response`` (str): you can choose the key to consider what button to push for a futher action. In this example, the key is "run". Keep the key similar to the specified value key in options.

Example function of input would be for the step above.

.. code-block:: python
  def simpleMethod(argument1, argument2, argument3)
    #the input sequence seen from the above step. It shows the order of the 
    return 


UserWriteStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Executes step to write values to variables or setting up the settings required for a comport. 

.. code-block:: yaml

  steptype: UserWriteStep
  step_name: Writing a command 
  description: Write the ID or the port 
  input_mapping:
    message:
      type: direct
      value: 'Write the ID or serial port of device'
    image_path: 
      type: direct
      value: test.jpg
    options:
      type: direct
      value:
      - 'cancel': 'cancel'
      - 'ID': 'Write'
  output_mapping:
    output:
      type: passfail


*   ``steptype`` (str): Determines the type of action.
*  ``input_mapping`` (dict): Inputs the desired period of time to wait before moving on to next step.
*  ``message`` (dict): can write a message that is expected to be relevant for user to do before 
*  ``options`` (dict): options to add buttons. For the main functionality of this function, two keys are defined: ``'ID'`` for setting up a comport through gui and ``'wrt'`` for writing a string to a variable.
These buttons on options are relevant for describing the action the button should take. The name of buttons are determined through key-value pairs as seen in the ``options``. It contains the keys 'yes' and two with each of their values.
The key ``cancel`` or ``'cancel'`` are both hardcoded to cancel a step and stop the entire test and can therefore not be used. keys do not need to be strings to operate unless the keys are ``yes`` or ``no`` as these are compiled to `True` and `False`.

*   ``image_path`` (dict, optional): shows the specified image on gui during this step. Path is not required to find the image, as long as it is one layer deep inside the working directory. 
*   ``output_mapping`` (dict): outputs of the method. Each output(``arg``) is required to have a ``type``.


This step requires some local variables depending on which **key** is specified under ``options``.
If the **key** chosen is ``'ID'``, it requires the following local variables.
* serial_ID
*  serialport
*  baudrate
When the key is applied and button is pushed, a GUI pops up letting you choose baudrate and what comport that is available you want to connect to. you can send an IDN? command through button and when found to work it will save the values to the local variables.
The output mapping should just be pass/faill for this key.

If the **key** chosen is ``'wrt'``, it requires an output mapping of either global or local scale to a variable. 
The input written into the GUI window is sent to the output mapping to be saved as a ``str``. The following is the required ``output_mapping`` if the **key** is ``'wrt'` on a button.

.. code-block:: yaml

  output_mapping:
    output:
      type: local
      local_name: example



SerialNumberStep
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prompts the operator for a device serial number via the GUI and stores it for the rest of the
recipe run. The serial number is written to both ``runtime.serial_number`` (used automatically
in all reports) and to the global variable ``serial_number`` so that subsequent steps can
reference it.

Add this step wherever serial-number capture fits your workflow — typically as the first step
in the main sequence, but it can equally be placed inside a setup or sub-sequence.

.. code-block:: yaml

  steptype: SerialNumberStep
  step_name: Scan Serial Number
  description: Ask the operator to scan or type the device serial number
  input_mapping: {}
  output_mapping:
    serial_number: {type: global, global_name: serial_number}

*   ``steptype`` (str): Must be ``SerialNumberStep``.
*   ``input_mapping`` (dict): No inputs required — leave as ``{}``.
*   ``output_mapping`` (dict, optional): The step always stores the serial number in
    ``runtime.serial_number`` and the ``serial_number`` global automatically.
    Use the output mapping only when you additionally want to store the value
    in a local variable or a differently-named global.

    .. code-block:: yaml

       # Store additionally in a local variable:
       output_mapping:
         serial_number: {type: local, local_name: device_sn}

.. note::
   The GUI must handle the ``get_serial_number`` event and respond with the serial
   number string on the provided response queue.  See :doc:`gui_event_handling` for
   details on wiring up the signal in your UI.

**Minimal recipe example with serial number capture:**

.. code-block:: yaml

   ---
   name: Example Recipe
   version: 1.0.0
   description: Recipe with serial number capture
   main_sequence: Main
   globals:
     serial_number: null

   ---
   sequence_name: Main
   setup_steps:
     - steptype: SerialNumberStep
       step_name: Scan Serial Number
       input_mapping: {}
       output_mapping: {}
   steps:
     - steptype: PythonModuleStep
       step_name: Run Tests
       module: my_tests.py
       action_type: method
       method_name: run_all
       input_mapping: {}
       output_mapping: {}
   teardown_steps: []
   locals: {}
   parameters: []
   outputs: []


Required globals and locals for certain steps.
============================

To ensure the functionality of some of the step types, certain global and locals are required for different datatypes. This section explains which step requires what specific variables in the recipe.
The following steps that require global or local variables are found below. 

 - **SSHConnectStep**

 Requires the following global variables:
  - cancel_key: 'cancel'
  - ssh_client: None
  - host: Ip of the host
  - user: root or user
  - password: None
  - private_key: 'path/to/private_key'
  - port: SSH port. standard is 22
 - **UserLoadingStep**
 Requires the following global variables:
  - cancel_key: 'cancel'
  - loadFile_key: 'file'
  - **UserRunMethodStep**
Requires the following global variables:
  - cancel_key: 'cancel'
- **UserWriteStep**
Requires the following global variables:
  - cancel_key: 'cancel'
  - ID_key: 'ID'
  - wrt_key: 'wrt'

Requires the following local variables **only** if ID_key is specified under options:
  - serial_ID: None
  - serialport: None
  - baudrate: None

- **SerialNumberStep**

Requires no global or local variables to be pre-declared.  The step automatically
creates or updates the ``serial_number`` global with the value entered by the operator.
If you want to reference the serial number in subsequent steps, declare it in globals:

.. code-block:: yaml

   globals:
     serial_number: null



.. _continue_on_error_details:

Continue On Error Mechanism
============================

Starting with ``recipe_version`` 1.1.0, the pypts framework supports a "Continue On Error" mechanism that allows test execution to continue even after encountering errors in non-critical steps.

Global Setting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

As of release version v0.1.8 The ``continue_on_error`` is not a global setting. It is a step specific setting, however by adding ``continue_on_error`` to globals, it will overwrite and return to similar functionality as pre-v0.1.8.

The ``continue_on_error`` field in the main recipe configuration enables this functionality:

.. code-block:: yaml

   ---
   name: My Recipe
   recipe_version: 1.1.0
   continue_on_error: true  # Enable continue on error globally on version v0.1.7 and below
   globals:
    continue_on_error: true # As of v0.1.8 the continue_on_error is a global value. If it is existing it will overwrite the step specific continue_on_error.
   # ... other fields

When ``continue_on_error`` is ``true``:
- Errors in steps marked as ``critical: false`` (default) will not stop sequence execution
- Errors in steps marked as ``critical: true`` will still stop sequence execution
- All errors are still logged and reported

When ``continue_on_error`` is ``false`` (default):
- Any error in any step stops sequence execution (legacy behavior)
- The ``critical`` field has no effect

Step-Level Critical Flag
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

.. note::
  Notice the indentation inside ``steps`` and the ``-`` in front of the step. Adding this - is crucial for the functionality of the recipe.


Behavior Matrix
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This mechanism is useful for:

- **Diagnostic Tests**: Run optional diagnostic steps that shouldn't fail the entire test if they encounter issues
- **Data Collection**: Continue gathering test data even if some measurements fail
- **Graceful Degradation**: Allow test sequences to complete as much as possible before stopping
- **Critical Safety Checks**: Ensure essential safety or validation steps always stop execution on failure

Example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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