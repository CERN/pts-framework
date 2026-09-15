.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

API
===

The old public API (``pypts.pts.run_pts``, ``pypts.startup.create_and_start_gui``,
``pypts.recipe``, ``pypts.steps``, ``pypts.report``) no longer exists. Those modules
were part of the pre-refactor single-process architecture.

Driving pypts from Python: ``pypts.api``
-----------------------------------------

``pypts.api`` starts the same Logger and CORE processes as ``python -m pypts`` and
exposes two doors:

.. code-block:: python

   from pypts.api import Pts, open_gui

   if __name__ == "__main__":
       # No window: load, run, read the result.
       with Pts() as pts:
           pts.load_recipe("bench.yml")
           result = pts.run(answer=lambda question: "Yes")
       print(result.result, result.report_dir)

       # The ordinary window, started from code.
       open_gui()                                   # empty
       open_gui("bench.yml")                        # with the recipe loaded
       open_gui("bench.yml", start=True)            # loaded and the main sequence started

- ``Pts.load_recipe(path)`` returns a ``LoadedRecipe`` or raises ``PtsError`` with the
  reason the recipe was refused.
- ``Pts.run(sequence=None, answer=None, on_step=None)`` blocks until the run has
  finished and returns a ``RunResult`` (verdict, one ``StepVerdict`` per step, report
  folder). ``answer`` is called for every operator question and returns the button or
  the text; without it every question is declined.
- ``Pts.stop()`` aborts the running sequence and is safe to call from another thread.
- The calling script must create ``Pts`` / call ``open_gui()`` under
  ``if __name__ == "__main__":`` - pypts starts its processes with spawn.

Every case is shown in ``api_showcase.py`` at the repository root. Module context:
``src/pypts/api/api.md``.

Running pypts directly
----------------------

.. code-block:: text

   python -m pypts [--mode gui|cli] [--log-level LEVEL]

A plugin API for new step types and drivers is planned for Phase 2 (see roadmap §3);
it is separate from the embedding API above.

For the message protocol used between CORE and the HMI, see
``src/pypts/messages/messages.md``.
