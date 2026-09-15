# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
pypts.api - drive pypts from another Python program.

Two doors, and deliberately nothing more:

- `Pts` - the engine with no window. Load a recipe, run a sequence, get the
  result back; operator questions are answered by a function you pass.
- `open_gui()` - the normal window, started from code: empty, with a recipe
  loaded, or with a recipe loaded and a sequence already started.

    from pypts.api import Pts

    if __name__ == "__main__":
        with Pts() as pts:
            pts.load_recipe("bench.yml")
            result = pts.run()
        print(result.result, result.report_dir)

Everything a caller needs is importable from here. resources/examples/
api_showcase.py walks through every case.
"""

from pypts.api.embedding import (
    LoadedRecipe,
    Pts,
    PtsError,
    RunResult,
    StepVerdict,
    open_gui,
)
from pypts.messages.common_messages import ResultType
from pypts.messages.run_events import UserPathRequest, UserPromptRequest, UserTextRequest

__all__ = [
    "LoadedRecipe",
    "Pts",
    "PtsError",
    "ResultType",
    "RunResult",
    "StepVerdict",
    "UserPathRequest",
    "UserPromptRequest",
    "UserTextRequest",
    "open_gui",
]
