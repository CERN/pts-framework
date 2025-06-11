.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _API_docs:

pypts API documentation
========================

This section provides detailed documentation for the public modules and classes within the ``pypts`` framework.

Core Runner (`pts`)
-------------------
.. automodule:: pypts.pts
   :members: run_pts, PtsApi
   :undoc-members:
   :show-inheritance:

Recipe Components (`recipe`)
----------------------------
.. automodule:: pypts.recipe
   :members: Recipe, Sequence, Step, ResultType, StepResult, Runtime
   :undoc-members:
   :show-inheritance:

Step Implementations (`steps`)
------------------------------
.. automodule:: pypts.steps
   :members: PythonModuleStep, SequenceStep, IndexedStep, UserInteractionStep, WaitStep
   :undoc-members:
   :show-inheritance:

Reporting (`report`)
--------------------
.. automodule:: pypts.report
   :members: Report, report_listener, generate_html_report
   :undoc-members:
   :show-inheritance:
