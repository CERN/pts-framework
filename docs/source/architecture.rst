.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Architecture Overview
====================

This document describes the overall architecture of the PyPTS (Python Test Sequence) framework and recent improvements made to consolidate and clean up the codebase.

Core Components
---------------

The PyPTS framework is organized into several key modules:

.. _recipe-module:

Recipe Module (``recipe.py``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``recipe.py`` module contains the core framework classes:

* **Recipe**: Main class for loading and executing test recipes from YAML files
* **Runtime**: Execution environment that manages global/local variables and event handling
* **Sequence**: Container for ordered test steps with setup/teardown capabilities
* **Step**: Abstract base class for all test steps
* **StepResult**: Container for step execution results and metadata
* **ResultType**: Enumeration of possible step outcomes (SKIP, DONE, PASS, FAIL, ERROR)

.. _steps-module:

Steps Module (``steps.py``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``steps.py`` module contains all concrete step implementations:

* **PythonModuleStep**: Executes Python modules/methods dynamically
* **SequenceStep**: Executes other sequences as steps
* **IndexedStep**: Wrapper for running steps multiple times with indexed inputs
* **UserInteractionStep**: Pauses execution for user input
* **WaitStep**: Simple time delay step

Recent Architecture Improvements
---------------------------------

.. _consolidation-effort:

Step Implementation Consolidation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Prior to the consolidation, step implementations were duplicated between ``recipe.py`` and ``steps.py``, leading to:

* Code duplication and maintenance burden
* Inconsistent implementations with different capabilities
* Inferior ``__load_module`` method in the ``recipe.py`` version
* Risk of using the wrong implementation

**Solution**: The architecture was refactored to eliminate duplication:

1. **Removed duplicate step classes** from ``recipe.py``
2. **Kept superior implementations** in ``steps.py`` 
3. **Added import statement** at the end of ``recipe.py`` to use ``steps.py`` implementations
4. **Fixed circular import issues** by placing imports after base class definitions

.. _module-loading-improvements:

Module Loading Improvements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``PythonModuleStep`` now uses a robust ``__load_module`` implementation that includes:

**File Validation**:
  * Checks if the module file exists before attempting import
  * Provides clear error messages for missing files

**Path Management**:
  * Safely modifies ``sys.path`` during import
  * Restores original ``sys.path`` after import completes
  * Handles path conflicts and cleanup properly

**Module Conflict Detection**:
  * Detects when a module with the same name is already loaded from a different path
  * Prevents import conflicts and provides clear error messages
  * Supports module reloading scenarios

**Enhanced Error Handling**:
  * Comprehensive exception handling with detailed logging
  * Exception chaining for better debugging (``raise ... from e``)
  * Specific error types for different failure modes

**Logging Integration**:
  * Debug logging for successful imports
  * Error logging with full context
  * Warning messages for potential issues

.. _import-management:

Import Management and Circular Dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Challenge**: The base classes in ``recipe.py`` needed to be available to ``steps.py``, but ``recipe.py`` also needed to use the step implementations from ``steps.py``.

**Solution**: 
  * Base classes (``Step``, ``Runtime``, etc.) remain in ``recipe.py``
  * ``steps.py`` imports base classes: ``from pypts.recipe import Step, Runtime, ...``
  * ``recipe.py`` imports implementations at the end: ``from pypts.steps import PythonModuleStep, ...``
  * Import placement after all base class definitions prevents circular dependency issues

.. _parameter-compatibility:

Parameter Signature Compatibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Standardization**: Updated the base ``Step._step()`` method signature to use consistent parameter naming:

.. code-block:: python

   def _step(self, runtime, input, parent_step_result_uuid):
       # Previously used 'parent_step', now uses 'parent_step_result_uuid'
       # for consistency with steps.py implementations

.. _resource-based-module-loading:

Resource-Based Module Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: The previous file-based module loading approach had several limitations:

* **Working Directory Dependency**: Module paths were resolved relative to the current working directory
* **Distribution Complexity**: Test modules needed to be available as separate files during deployment
* **Path Management Issues**: Complex ``sys.path`` manipulation with potential conflicts
* **Deployment Fragility**: Risk of missing test files in different environments

**Solution**: Implemented a resource-based module loading system using ``importlib.resources``:

1. **Recipe Configuration**: Added ``test_package`` field to recipe YAML files
2. **Package-Based Loading**: Test modules are now loaded as proper Python package resources
3. **Simplified Path Resolution**: Module paths are resolved within the specified package
4. **Robust Error Handling**: Clear error messages for missing packages or modules

**Implementation Details**:

The ``PythonModuleStep`` now uses a completely rewritten ``__load_module`` method that:

**Package Validation**:
  * Verifies the specified ``test_package`` exists and is accessible
  * Uses ``importlib.resources.files()`` to validate package availability
  * Provides clear error messages for missing or inaccessible packages

**Resource-Based Import**:
  * Converts file paths (e.g., ``tests/test_status.py``) to module names (``test_status``)
  * Constructs full module names using the package prefix (``fsi_pts.tests.test_status``)
  * Uses standard Python import mechanisms instead of file system operations

**Simplified Architecture**:
  * Eliminated complex ``sys.path`` manipulation
  * Removed module conflict detection (handled by Python's import system)
  * Streamlined error handling with proper exception chaining

**Recipe Configuration Example**:

.. code-block:: yaml

   ---
   name: FSI PTS
   version: 0.0.1
   description: Test recipe for FSI version check
   test_package: fsi_pts.tests  # NEW: Specifies package containing test modules
   globals: {}

   ---
   sequence_name: Main
   steps:
   - steptype: PythonModuleStep
     step_name: Get FSI Status
     module: test_status.py  # Resolved to fsi_pts.tests.test_status
     method_name: test_status

**Benefits**:

* **Package Consistency**: Tests are bundled as proper package resources
* **Distribution Simplicity**: No separate file management required
* **Environment Independence**: No dependency on current working directory
* **Deployment Robustness**: Tests are guaranteed to be available if the package is installed
* **Python Standards Compliance**: Uses standard Python import mechanisms

Current Architecture Benefits
-----------------------------

.. _benefits:

Clean Separation of Concerns
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Base Framework** (``recipe.py``): Core recipe execution logic
* **Step Implementations** (``steps.py``): Specific step behaviors and capabilities
* **Single Source of Truth**: Each step type has exactly one implementation

Maintainability Improvements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **No Code Duplication**: Changes only need to be made in one place
* **Consistent Behavior**: All instances of a step type use the same implementation
* **Better Testing**: Single implementation to test and validate

Robustness Enhancements
~~~~~~~~~~~~~~~~~~~~~~~~

* **Superior Module Loading**: File validation, error handling, and cleanup
* **Conflict Detection**: Prevents module import conflicts
* **Comprehensive Logging**: Better debugging and troubleshooting capabilities

Future Considerations
---------------------

.. _future-work:

Path Resolution
~~~~~~~~~~~~~~~

✅ **IMPLEMENTED**: Package-aware loading is now available through the ``test_package`` configuration field.

Future improvements may include:

* **Recipe-relative paths**: Resolve module paths relative to the recipe file location (for legacy file-based loading)
* **Multiple package support**: Allow recipes to specify multiple test packages
* **Configurable search paths**: Allow recipes to specify additional module search directories for mixed loading strategies

Extension Points
~~~~~~~~~~~~~~~~

The consolidated architecture provides clear extension points:

* **New Step Types**: Add to ``steps.py`` following existing patterns
* **Custom Loaders**: Override default file loading behavior in ``Recipe`` class
* **Event Handlers**: Extend the event system for custom runtime behavior

Migration Guide
---------------

For existing code using the old architecture:

1. **No changes required** for recipe YAML files
2. **Import updates**: Change imports from ``recipe`` to ``steps`` if directly importing step classes
3. **Parameter names**: Update any custom step implementations to use ``parent_step_result_uuid``

.. code-block:: python

   # Old
   from pypts.recipe import PythonModuleStep
   
   # New  
   from pypts.steps import PythonModuleStep

For migrating to resource-based module loading:

1. **Package Structure**: Organize test modules as Python packages with proper ``__init__.py`` files
2. **Recipe Configuration**: Add ``test_package`` field to recipe YAML files
3. **Module Paths**: Update module paths to be relative to the test package (remove directory prefixes)

.. code-block:: yaml

   # Old (file-based)
   ---
   name: My Recipe
   globals: {}
   
   steps:
   - steptype: PythonModuleStep
     module: tests/my_test.py  # File path
   
   # New (resource-based)
   ---
   name: My Recipe
   test_package: my_package.tests  # Package containing test modules
   globals: {}
   
   steps:
   - steptype: PythonModuleStep
     module: my_test.py  # Resolved to my_package.tests.my_test 