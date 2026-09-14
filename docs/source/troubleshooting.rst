.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Troubleshooting
===============

GUI does not open (Linux)
-------------------------

Install the Qt system libraries::

   sudo dnf install libxcb libxcb-devel xcb-util xcb-util-wm xcb-util-keysyms \
                    xcb-util-image xcb-util-renderutil

Or run headless: ``QT_QPA_PLATFORM=offscreen python -m pypts``.

Config popup on startup
-----------------------

The launcher shows a popup when ``config.ini`` is missing, unreadable, or has a
wrong structure version. Delete the file to get a fresh one::

   # Windows
   del "%LOCALAPPDATA%\pypts\config.ini"
   # Linux
   rm ~/.config/pypts/config.ini

Recipe fails to load
--------------------

Check these common causes:

- **Unknown steptype** — the new YAML step-type names differ from the old ones.
  See :ref:`yaml_format` for the current names (``PythonModule``, ``UserInteraction``,
  ``Wait``, ``UserWrite``).
- **Missing required sequence keys** — all six sequence keys are required:
  ``sequence_name``, ``parameters``, ``locals``, ``outputs``, ``setup_steps``, ``steps``,
  ``teardown_steps``. An empty list ``[]`` is fine.
- **YAML type coercion** — ``yes``/``no`` are booleans, ``None`` is the string
  ``"None"``. Quote values you want to keep as strings.

ModuleNotFoundError in PythonModuleStep
---------------------------------------

- Verify the module path is relative to the recipe file's directory, or that
  ``test_package`` is set and the package is installed (``pip install -e .``).
- All directories in the package must have ``__init__.py``.

Step type not available
-----------------------

``UserLoadingStep`` is not yet ported. ``UserRunMethodStep`` is deprecated (replace
with a ``UserInteraction`` step followed by a ``PythonModule`` step).
``SSHConnectStep`` / ``SSHCloseStep`` will move to the HAL layer (Phase 3).

Log file location
-----------------

Run log is written to ``<logs_dir>/pypts_<timestamp>.log`` (see config). Pass
``--log-level DEBUG`` to get the full message trace.
