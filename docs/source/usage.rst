.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _usage:

Usage
=====

This guide provides a basic overview of how to run a test recipe using the ``pypts`` framework.

Installation
------------

Before using pypts, you may need to install the following system dependencies:

.. code-block:: bash

   sudo dnf install libxcb libxcb-devel
   sudo dnf install xcb-util xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil

1. Define your Recipe (`my_recipe.yaml`)
-----------------------------------------

Create a YAML file defining your test sequence. The recipe consists of a main document defining metadata and global variables, followed by documents defining named sequences.

.. code-block:: yaml
   :caption: my_recipe.yaml

   # Main recipe definition
   name: MyTestRecipe
   description: Example recipe demonstrating basic steps.
   version: "1.0"
   globals:
     device_address: "COM3"
     test_voltage: 5.0
   ---
   # Main sequence definition
   sequence_name: Main
   parameters:
     # Input parameters for this sequence (if any)
   locals:
     # Local variables initialized for this sequence
     measurement: null
   outputs:
     # Values from locals to expose as sequence output
     - measurement
   setup_steps: []
   steps:
     - steptype: WaitStep
       step_name: Initial Delay
       input_mapping:
         wait_time: { type: direct, value: 2 }
     - steptype: PythonModuleStep
       step_name: Configure Device
       module: path/to/your/device_driver.py
       action_type: method
       method_name: setup_device
       input_mapping:
         port: { type: global, global_name: device_address }
         voltage: { type: global, global_name: test_voltage }
       output_mapping:
         success: { type: passfail }
     - steptype: PythonModuleStep
       step_name: Take Measurement
       module: path/to/your/device_driver.py
       action_type: method
       method_name: read_measurement
       input_mapping: {}
       output_mapping:
         measured_value: { type: local, local_name: measurement }
         # Example pass/fail check
         status: { type: range, min: 4.8, max: 5.2 }
   teardown_steps:
     - steptype: PythonModuleStep
       step_name: Disconnect Device
       module: path/to/your/device_driver.py
       action_type: method
       method_name: disconnect
       input_mapping: {}
       output_mapping: {}

.. note::
   Replace ``path/to/your/device_driver.py`` with the actual path to your Python module containing the methods called by ``PythonModuleStep``.

Alternative: Resource-Based Module Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For better distribution and deployment, you can use resource-based module loading by organizing your test modules as Python packages:

.. code-block:: yaml
   :caption: my_recipe.yaml (resource-based)

   # Main recipe definition with test_package
   name: MyTestRecipe
   description: Example recipe using resource-based loading.
   version: "1.0"
   test_package: my_project.tests  # NEW: Package containing test modules
   globals:
     device_address: "COM3"
     test_voltage: 5.0
   ---
   # Main sequence definition
   sequence_name: Main
   parameters: []
   locals:
     measurement: null
   outputs:
     - measurement
   setup_steps: []
   steps:
     - steptype: PythonModuleStep
       step_name: Configure Device
       module: device_driver.py  # Resolved to my_project.tests.device_driver
       action_type: method
       method_name: setup_device
       input_mapping:
         port: { type: global, global_name: device_address }
         voltage: { type: global, global_name: test_voltage }
       output_mapping:
         success: { type: passfail }
     - steptype: PythonModuleStep
       step_name: Take Measurement
       module: device_driver.py  # Same module, different method
       action_type: method
       method_name: read_measurement
       input_mapping: {}
       output_mapping:
         measured_value: { type: local, local_name: measurement }
         status: { type: range, min: 4.8, max: 5.2 }
   teardown_steps:
     - steptype: PythonModuleStep
       step_name: Disconnect Device
       module: device_driver.py
       action_type: method
       method_name: disconnect
       input_mapping: {}
       output_mapping: {}

**Package Structure Example**:

.. code-block:: text

   my_project/
   ├── __init__.py
   ├── tests/
   │   ├── __init__.py
   │   ├── device_driver.py
   │   └── other_test_modules.py
   └── my_recipe.yaml

**Benefits of Resource-Based Loading**:

* **Distribution**: Test modules are bundled with your package
* **Reliability**: No dependency on current working directory
* **Deployment**: Tests are guaranteed available if package is installed
* **Standards**: Uses Python's standard import mechanism

2. Run the Recipe (`run_my_recipe.py`)
---------------------------------------

Use the ``run_pts`` function from the ``pypts.pts`` module to execute your recipe file. This will start the recipe execution in a background thread.

.. code-block:: python
   :caption: run_my_recipe.py

   import logging
   from pypts.pts import run_pts
   import time

   # Configure logging (optional but recommended)
   logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

   print("Starting the pypts recipe...")
   # Specify the path to your recipe file
   recipe_file = "my_recipe.yaml"

   # Run the default 'Main' sequence
   api = run_pts(recipe_file=recipe_file)

   print(f"Recipe '{recipe_file}' started in background thread.")
   print("Monitoring event queue (press Ctrl+C to stop early):")

   # Example: Monitor the event queue for completion or errors
   # In a real application, you might have more sophisticated handling
   try:
       while True:
           event_name, event_data = api.event_queue.get() # Blocking call
           print(f"EVENT: {event_name} - Data: {event_data}")
           if event_name == "post_run_recipe":
               print("Recipe finished.")
               break
           # Add handling for specific errors or other events if needed
           time.sleep(0.1)
   except KeyboardInterrupt:
       print("\nStopping monitoring.")
   except Exception as e:
       print(f"An error occurred: {e}")

   print("Main script finished.")

3. Check the Reports
--------------------

After execution (or during, for the CSV), check the ``./pts_reports/`` directory (relative to where you ran the Python script) for:

*   ``report.csv``: Incrementally updated CSV file with detailed step results.
*   ``report.html``: HTML version of the report generated after the recipe finishes.

Migrating from File-Based to Resource-Based Loading
----------------------------------------------------

If you have existing recipes using file-based module loading, here's how to migrate:

**Step 1: Organize Test Modules**

Convert your test file structure to a proper Python package:

.. code-block:: bash

   # Before (file-based)
   my_project/
   ├── tests/
   │   ├── test_module1.py
   │   └── test_module2.py
   └── recipe.yaml
   
   # After (resource-based)
   my_project/
   ├── __init__.py                    # NEW: Makes it a package
   ├── tests/
   │   ├── __init__.py               # NEW: Makes tests a subpackage  
   │   ├── test_module1.py
   │   └── test_module2.py
   └── recipe.yaml

**Step 2: Update Recipe Configuration**

Add the ``test_package`` field and simplify module paths:

.. code-block:: yaml

   # Before
   ---
   name: My Recipe
   globals: {}
   
   steps:
   - steptype: PythonModuleStep
     module: tests/test_module1.py     # File path
     method_name: my_test
   
   # After  
   ---
   name: My Recipe
   test_package: my_project.tests     # NEW: Package specification
   globals: {}
   
   steps:
   - steptype: PythonModuleStep
     module: test_module1.py           # Just the filename
     method_name: my_test

**Step 3: Install and Test**

Make sure your package is properly installed:

.. code-block:: bash

   # Install in development mode
   pip install -e .
   
   # Or install normally
   pip install .

**Step 4: Verify Package Structure**

Test that your modules can be imported:

.. code-block:: python

   # This should work without errors
   import my_project.tests.test_module1

Common Migration Issues
~~~~~~~~~~~~~~~~~~~~~~~

**Import Errors**: Make sure all directories have ``__init__.py`` files

**Module Not Found**: Verify the ``test_package`` field matches your actual package structure

**Path Issues**: Remove directory prefixes from module paths in the recipe - just use the filename

**Package Installation**: Ensure your package is installed in the Python environment where you're running pypts
