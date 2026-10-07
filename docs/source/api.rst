.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

API
===

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
- Create ``Pts`` / call ``open_gui()`` under ``if __name__ == "__main__":`` — pypts
  starts its processes with spawn.

Every case is shown in ``api_showcase.py`` at the repository root; the module context
is ``src/pypts/api/api.md``.
