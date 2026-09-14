.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

pypts
=====

pypts is a CERN hardware-oriented test framework. Recipes (YAML files) define
sequences of steps that run against hardware and produce CSV + HTML reports.

Running::

   python -m pypts          # GUI (default)
   python -m pypts --mode cli

.. toctree::
   :caption: Getting started
   :maxdepth: 1

   usage
   migration_instructions
   troubleshooting

.. toctree::
   :caption: Reference
   :maxdepth: 1

   yaml_format
   architecture
   gui_event_handling
   report_generation
   api
   dependency_license_analysis
   pre_refactoring
   genindex
