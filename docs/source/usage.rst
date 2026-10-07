.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Usage
=====

From the repository root:

.. code-block:: bash

   python -m pypts                                   # GUI (default)
   python -m pypts --mode cli                        # text shell
   python -m pypts --mode headless --recipe x.yml    # one unattended run, for CI
   python -m pypts --log-level DEBUG                 # full message trace in the run log

On Windows, ``run_pypts.bat`` does the same with the repository's ``.venv``.
To try it, load ``resources/recipes/Development_recipes/wait_recipe.yml``.

Your deliverable is a recipe YAML file and the Python modules it calls; the
framework provides the processes, GUI, logging and reports.
``resources/recipes/Development_recipes/`` has one demo recipe per step type.

On first run the launcher creates a per-user ``config.ini``
(``%LOCALAPPDATA%\pypts\config.ini`` on Windows, ``~/.config/pypts/config.ini``
on Linux). Each run writes its own report folder with ``report.csv`` and
``report.html``.

For every option, mode, exit code and file location see ``usage_manual.html``;
for the recipe format see ``recipe_guide.html``.
