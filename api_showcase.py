# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# Keywords: api, embedding, headless, gui, automation, scripting
# Description: Every way to drive pypts from your own Python code - headless runs and the window

"""
pypts.api, one case at a time.

    python api_showcase.py headless    run a recipe with no window, answering its questions
    python api_showcase.py progress    print each step as it finishes
    python api_showcase.py stop        abort a run from another thread
    python api_showcase.py gui         open the window
    python api_showcase.py gui-load    open the window with a recipe loaded
    python api_showcase.py gui-start   open the window with a recipe loaded and started

Every case uses the demo recipes in resources/recipes.
The run log and the report go where config.ini says, as for any pypts run.

Everything runs under `if __name__ == "__main__":` - pypts starts its processes
with spawn, which imports this file again in every child.
"""

import sys
import threading
from pathlib import Path

from pypts.api import (
    Pts,
    PtsError,
    RunResult,
    UserPathRequest,
    UserPromptRequest,
    UserTextRequest,
    open_gui,
)

RECIPES = Path(__file__).resolve().parent / "resources" / "recipes"

#: Every demo in one run, including the questions, typed answers and picks.
FULL_SHOWCASE = RECIPES / "showcase_recipes" / "showcase_full.yml"

#: Four function calls and no questions - the simplest headless run.
PYTHON_MODULE = RECIPES / "pythonmodulestep_recipes" / "pythonmodulestep_demo.yml"


def answer_like_an_operator(
    request: UserPromptRequest | UserTextRequest | UserPathRequest,
) -> str | None:
    """
    Answer the questions showcase_full.yml asks, the way a technician would.

    A UserTextRequest wants typed text; a UserPathRequest wants an existing
    file or folder, as `request.select` says; a UserPromptRequest wants one of
    its options. Returning None declines, which makes that step an ERROR.
    """
    if isinstance(request, UserTextRequest):
        if "CLOSED" in request.message:
            return "CLOSED"
        if "voltage" in request.message:
            return "12.0"
        return "SN-0001"
    if isinstance(request, UserPathRequest):
        if request.select == "folder":
            return str(RECIPES)
        return str(RECIPES / "common" / "example_tests.py")
    if "serial port" in request.message:
        return "COM2"
    # "Continue" for the connection prompt, "Yes" for the LED.
    return request.options[0]


def print_result(result: RunResult) -> None:
    print(f"\n{result.sequence}: {result.result.name} ({len(result.steps)} steps)")
    for step in result.steps:
        line = f"  {step.result.name:<5} {step.name}"
        if step.info:
            line = f"{line} - {step.info.splitlines()[0]}"
        print(line)
    for error in result.errors:
        print(f"  error: {error}")
    print(f"Report: {result.report_dir}")


def headless() -> None:
    """Load, run with answers, read the result."""
    with Pts() as pts:
        recipe = pts.load_recipe(FULL_SHOWCASE)
        print(f"Loaded '{recipe.name}' - sequences: {', '.join(recipe.sequences)}")
        for warning in recipe.warnings:
            print(f"  warning: {warning}")
        result = pts.run(answer=answer_like_an_operator)
    print_result(result)


def progress() -> None:
    """The same kind of run, printing each step the moment it finishes."""
    with Pts() as pts:
        pts.load_recipe(PYTHON_MODULE)
        result = pts.run(on_step=lambda step: print(f"  finished: {step.name} -> {step.result.name}"))
    print_result(result)


def stop() -> None:
    """stop() is safe from another thread; run() comes back with STOP."""
    with Pts() as pts:
        pts.load_recipe(FULL_SHOWCASE)
        # The answers come at once, so one second in is the Wait group; stop there.
        threading.Timer(1.0, pts.stop).start()
        result = pts.run(answer=answer_like_an_operator)
    print_result(result)


def gui() -> None:
    """The ordinary window - the same as `python -m pypts`."""
    open_gui()


def gui_load() -> None:
    """The window with a recipe already loaded; the operator presses Start."""
    open_gui(FULL_SHOWCASE)


def gui_start() -> None:
    """The window with a recipe loaded and its main sequence already running."""
    open_gui(FULL_SHOWCASE, start=True)


CASES = {
    "headless": headless,
    "progress": progress,
    "stop": stop,
    "gui": gui,
    "gui-load": gui_load,
    "gui-start": gui_start,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        print(__doc__)
        return 2
    try:
        CASES[sys.argv[1]]()
    except PtsError as error:
        print(f"pypts said no: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
