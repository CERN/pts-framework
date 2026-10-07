.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

pypts
=====

pypts is a CERN hardware-oriented test framework. Recipes (YAML files) define
sequences of steps that run against hardware and produce CSV + HTML reports.

These pages are an entry point only. The detail lives in the repository:

- ``usage_manual.html`` — how to run it: modes, options, exit codes, where files go.
- ``recipe_guide.html`` — the recipe format and every step type.
- ``pypts_implementation_status.html`` — what is implemented and what comes next.
- ``src/pypts/<module>/<module>.md`` — how each module works.

.. toctree::
   :caption: Getting started
   :maxdepth: 1

   usage
   troubleshooting

.. toctree::
   :caption: Reference
   :maxdepth: 1

   architecture
   api
   genindex
