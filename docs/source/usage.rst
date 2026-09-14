.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Usage
=====

Installation
------------

.. code-block:: bash

   pip install pts-framework

PySide6 on Linux requires::

   sudo dnf install libxcb libxcb-devel xcb-util xcb-util-wm xcb-util-keysyms \
                    xcb-util-image xcb-util-renderutil

Running
-------

.. code-block:: bash

   python -m pypts                    # GUI mode (default)
   python -m pypts --mode cli         # CLI mode
   python -m pypts --log-level DEBUG  # full message trace in the log

There is no ``__main__.py`` to write. The framework handles the process model,
GUI, logging and reporting. Your only deliverable is a recipe YAML file and the
Python modules it calls.

Config file
-----------

On first run the launcher writes a config file:

- Windows: ``%LOCALAPPDATA%\pypts\config.ini``
- Linux: ``~/.config/pypts/config.ini``

Edit it to change ``[paths] logs_dir`` / ``reports_dir`` or the default log
level. A version-mismatched or unreadable file is discarded for that run and
re-created on the next.

Writing a recipe
----------------

See :ref:`yaml_format` for the full format. Minimal working recipe:

.. code-block:: yaml

   ---
   name: MyRecipe
   version: "1.0"
   description: Checks the widget.
   globals:
     device_port: COM3

   ---
   sequence_name: Main
   parameters: []
   locals: {}
   outputs: []
   setup_steps: []
   steps:
     - steptype: PythonModule
       step_name: Check widget
       module: my_tests.py
       action_type: method
       method_name: check_widget
       input_mapping:
         port: { type: global, global_name: device_port }
       output_mapping:
         ok: { type: passfail }
   teardown_steps: []

Reports
-------

Each run writes to ``<reports_dir>/<timestamp>_<recipe_name>/``:

- ``report.csv`` — incremental, written step-by-step.
- ``report.html`` — generated after the run finishes.
