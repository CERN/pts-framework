.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

API
===

The old public API (``pypts.pts.run_pts``, ``pypts.startup.create_and_start_gui``,
``pypts.recipe``, ``pypts.steps``, ``pypts.report``) no longer exists. Those modules
were part of the pre-refactor single-process architecture.

The new framework has no embeddable Python API. The entry point is::

   python -m pypts [--mode gui|cli] [--log-level LEVEL]

A plugin API (``pypts.api``) is planned for Phase 2 (see roadmap §3). Until then,
integration is done by:

1. Writing a recipe YAML file (see :ref:`yaml_format`).
2. Writing Python modules called by ``PythonModule`` steps.
3. Running ``python -m pypts`` in GUI or CLI mode and loading the recipe.

For the message protocol used between CORE and the HMI, see
``src/pypts/messages/messages.md``.
