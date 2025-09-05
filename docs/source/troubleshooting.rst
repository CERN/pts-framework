.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _troubleshooting:

Troubleshooting
=====

This guide provides a basic overview troubleshooting for commonly occuring problems and basic setup of the environment.



basic ``pypts`` environment setup.
------------
Issues can often occur due to missing libraries, conflicting versions or conflicting elements in the environment.

If you come into any difficulties, making a fresh virtual environment is recommended.
To do so, create a new virtual environment in the project folder in a similar position as this.

.. code-block:: text

     my_project/
     ├── .venv/
     ├── /src/pypts/
     ├── ├── __init__.py
     ├── ├── __main__.py
     ├── ├── recipes/
     ├── ├── ├── simple_recipe_GOLDEN_COPY.yml
     ├── tests/unit_tests/
     │   └── other_test_modules.py
     └── README.md

Activate the environment and install the package within the environment.

.. code-block:: bash

   # Install in development mode
   pip install -e .
   
   # Or install normally
   pip install .

Before using pypts, you may need to install the following system dependencies for PySide6 (Qt GUI framework):

.. code-block:: bash

   sudo dnf install libxcb libxcb-devel
   sudo dnf install xcb-util xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil


Recipe-related issues. 
-----------------------------------------
Issues related to the recipe are often related to a difference or lack of keys.

**Required framework for recipe**

The specifics in the framework below is required in the prelude of the recipe to run the framework.

.. code-block:: yaml

     name: Example Test Recipe
     version: 0.1.0
     recipe_version: 1.0.0
     description: A sample description of a recipe
     main_sequence: Main
     test_package: test_package
     globals: {}

The Main sequence is also required and consists of the rest of the test cases which exists of the following elements.

.. code-block:: yaml
    
     sequence_name: Main
     description: The main sequence of steps for the example recipe.
     parameters:
         target_value: '0'
     locals:
         target_value: '45'
         test_name: Hello
     outputs:
         my_output: None
     setup_steps: []
     steps:
     - steptype: UserInteractionStep
         step_name: Are you all right?
         description: Asking user for something
         skip: false
         input_mapping:
             message:
                 type: direct
                 value: 'example'
             image_path:
                 type: direct
                 value: example.jpg
             options:
                 type: direct
                 value:
                 - 'yes': ''
                 - 'no': ''
         output_mapping:
             user_response:
                 type: equals
                 value: 'yes'
         - steptype: PythonModuleStep
         step_name: Run a other_test
         action_type: method
         module: example_tests.py
         method_name: other_test
         input_mapping: {}
         output_mapping:
             some_return:
                 type: passfail
             value:
                 type: local
                 local_name: test_value
    
Above we see an example of an UserInteractionStep type and a PythonModuleStep setup. The UserInteractionStep is used for when the system is awaiting an action from user.
The PythonModuleStep shows a requirement for determining which module to use and a specification of the method_name to be used.

.. note::
    Notice that the output_mapping for ``UserInteractionStep`` is user_response, respective to a response on a pushed button. 

**ModuleNotFoundError**

Ensure test_package is properly named in the recipe and that the method_name properly name the specific function to run.

.. note::
   As of 13/08/2025, the ``run_tests.py`` will run through all the tests, but will not catch lack of test_package which would appear as an error during runtime.


**Import Errors**: Make sure all directories have ``__init__.py`` files

**Path Issues**: Remove directory prefixes from module paths in the recipe - just use the filename. Requires the test_package.

**Package Installation**: Ensure your package is installed in the Python environment where you're running pypts

**Failing test despite reading a passing value**: Ensure the datatype that is compared against is equal to the read value, i.e. string cannot be compared to integer.

