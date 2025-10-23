.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _usage:

Usage
=====

This guide provides a basic overview of how to install and run a test recipe using the ``pypts`` framework.

Installation
------------
This section provides the neccesary information needed to setup the environment and test to run.
Before using pypts, you may need to install the following system dependencies for PySide6 (Qt GUI framework):

.. code-block:: bash

   sudo dnf install libxcb libxcb-devel
   sudo dnf install xcb-util xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil


To setup the test, start in the desired directory. Make a virtual environment. Name is arbitrary.

.. code-block:: bash
  
   python -m venv .venv

Activate the environment. Install the package from Acc-PyPI CERN.

.. code-block:: bash

   python -m pip install pts-framework==0.2.0


There are two ways of setting up the pypts framework after the package has been installed. A package-based setup or a minimal setup consisting of only test and recipe. 

1. Minimal setup pypts-framework
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The minimal setup does not use package-based recipe, see :ref:`_yaml_format`, but uses a gui. Through the gui, the recipe is loaded, which runs the tests.
An example of the package structure is:

.. code-block:: text

   my_cwd/
   ├── tests/
   │   ├── __init__.py
   │   └── tests.py
   └── my_recipe.yaml

But the only requirements is the recipe and the tests described in the recipe. **Note**: tests and  are required to be at least one directory down from the ``cwd``. 
To run the test, the following command is required.

.. code-block:: bash

   python -m pypts

This initializes the GUI where the recipe can be loaded and run.
This ``pypts`` framework should **not** have a package in its recipe.

2. Package based pypts-framework
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the test is expected to be package-based, a different setup is required. With the installed package based, the following is required.

.. code-block:: bash

   CWD/
  ├── requirements.txt             # or pyproject.toml, at root
  └── package/
      ├── __init__.py              # package root
      ├── __main__.py              # required to initialize the package
      ├── recipe.yaml              # inside package folder
      └── tests/                   # Not required to put tests in their own directory.
          ├── __init__.py          # tests as subpackage
          ├── test_module1.py
          └── test_module2.py

The recipe is not required to be inside the package, however the tests are.
To compile into its own package, run:

.. code-block:: bash

  pip install -e .


This will initialize your software as a package that can now be called. 

.. code-block:: bash

  python -m package

That can run the desired package and the tests inside. 
The package requires a ``__main__.py`` file. See :ref:`__main__` for how the code in the main file should look. 
The ``__main__.py`` is similar between the pypts-framework package and the new package.

1. Define your Recipe (`my_recipe.yaml`)
-----------------------------------------

Create a YAML file defining your test sequence. The recipe consists of a main document defining metadata and global variables, followed by documents defining named sequences. See :ref:`_yaml_format` for full explaination of all steps available for recipe.

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
       module: device_driver.py
       action_type: method
       method_name: setup_device
       input_mapping:
         port: { type: global, global_name: device_address }
         voltage: { type: global, global_name: test_voltage }
       output_mapping:
         success: { type: passfail }
     - steptype: PythonModuleStep
       step_name: Take Measurement
       module: device_driver.py
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
       module: device_driver.py
       action_type: method
       method_name: disconnect
       input_mapping: {}
       output_mapping: {}

.. note::
   Replace ``device_driver.py`` with the actual name of your Python module containing the methods called by ``PythonModuleStep``. Adding the path should not be done as the system automatically 
   detects the path to the specified test. Therefore, avoid naming modules the same unless you specify a ``test_package`` as described below.


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
* **Naming**: Avoids errors appearing as a result of tests having the same name between packages


2. Run the Recipe (`__main__.py`)
---------------------------------------


In situations where a level of user interaction with buttons is required, the one above is not enough. For a level of user interaction with steptype ``UserInteractionStep``, a GUI is added.
As the above, use the ``run_pts`` function from the ``pypts.pts`` module to execute the recipe file. Use the function ``create_and_start_gui()`` from the ``pypts.startup`` module to create a gui and start it, using the execution of the ``run_pts``.

.. code-block:: python
   :caption: __main__.py

   from pypts._version import version as __version__
   import logging
   import sys
   import os
   from pypts.pts import run_pts
   from pypts.startup import create_and_start_gui

   logger = logging.getLogger(__name__)
   # Configure basic logging
   log_format = '%(levelname)s : %(name)s : %(message)s'
   logging.basicConfig(level=logging.DEBUG, format=log_format)
   # Reduce verbosity of noisy libraries
   logging.getLogger("paramiko.transport").setLevel("WARN")


   if __name__ == '__main__':
       """Main entry point for the PTS application.
       
       Sets up the QApplication, MainWindow, logging, RecipeEventProxy, 
       and connects signals/slots between the proxy and the window.
       Starts the recipe execution and event processing threads.
       """
       api = run_pts()
 
       window, app = create_and_start_gui(api)
 
       exit_code = app.exec()
       sys.exit(exit_code)


It can also be initialized through the command:

.. code-block:: bash

  python -m pypts




3. Check the Reports
--------------------

After execution (or during, for the CSV), check the ``./pts_reports/`` directory (relative to where you ran the Python script) for:

*   ``report.csv``: Incrementally updated CSV file with detailed step results.
*   ``report.html``: HTML version of the report generated after the recipe finishes.

Migrating from File-Based to Resource-Based Loading
----------------------------------------------------
Both file-based and ressource-based loading are possible for the framework.
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