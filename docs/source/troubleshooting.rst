.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _troubleshooting:

Troubleshooting
=========================

This guide provides a basic overview troubleshooting for commonly occuring problems and basic setup of the environment.



basic ``pypts`` environment setup.
------------------------------------------------
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

.. note::
   Python 3.14 requires PySide6 6.10 or newer. The project's historical
   ``PySide6==6.9.1`` pin has no Python 3.14 distribution, so environments using
   Python 3.14 must bump that dependency to at least the 6.10 release line.

.. code-block:: bash

   sudo dnf install libxcb libxcb-devel
   sudo dnf install xcb-util xcb-util-wm xcb-util-keysyms xcb-util-image xcb-util-renderutil


Recipe-related issues. 
-----------------------------------------
Recipe language ``2.0.0`` requires a header document and at least one complete
sequence document. Start from the parser-tested example instead of copying an
isolated fragment:

.. literalinclude:: _examples/recipe_v2.yml
   :language: yaml
   :caption: Valid recipe-language 2 structure

If validation fails, use the diagnostic code, field path, and source position.
The most common migration failures are an old or missing ``recipe_version``, a
lowercase step discriminator, a literal input without ``type: direct``, a
missing description, or the removed sequence ``serial_number`` field. See
:ref:`yaml_format` for migration guidance and the generated
:doc:`_generated/recipe_language_reference` for exact fields.

**ModuleNotFoundError**

Ensure test_package is properly named in the recipe and that the method_name properly name the specific function to run.

.. note::
   As of 13/08/2025, the ``run_tests.py`` will run through all the tests, but will not catch lack of test_package which would appear as an error during runtime.


**Import Errors**: Make sure all directories have ``__init__.py`` files

**Path Issues**: With ``test_package``, use a module path relative to the package. Nested paths are supported.

**Package Installation**: Ensure your package is installed in the Python environment where you're running pypts

**Failing test despite reading a passing value**: Ensure the datatype that is compared against is equal to the read value, i.e. string cannot be compared to integer.
