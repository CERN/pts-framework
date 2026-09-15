# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Headless mode: one recipe, one sequence, one exit code (migration finding M-2b).

    python -m pypts --mode headless --recipe bench.yml [--sequence Cal]

It loads the recipe, runs the sequence, prints each step as it finishes and
exits with a code a CI pipeline can check. Nobody is at the keyboard, so every
question a step asks is declined, which makes that step an ERROR - exactly as
in the CLI.

It is a thin layer on `Pts`: the same engine, the same run log, the same report
folders. The launcher imports it only in headless mode.
"""

import sys
from pathlib import Path

from pypts.api.embedding import Pts, PtsError, Question, RunResult, StepVerdict
from pypts.logger.log import log
from pypts.messages.common_messages import ResultType
from pypts.utilities.common import describe_step_values

#: The run passed: PASS, or DONE.
EXIT_PASSED = 0

#: At least one step failed.
EXIT_FAILED = 1

#: The run ended in ERROR or STOP, or skipped everything - it did not judge the unit.
EXIT_NOT_JUDGED = 2

#: There was no run: a missing recipe, a refused recipe, an unknown sequence,
#: bad arguments, or an engine that could not start or stopped mid-run.
EXIT_NOT_RUN = 3


class HeadlessPts(Pts):
    """`Pts`, named HEADLESS in the run log instead of API."""

    MODE = "headless"


def exit_code_for(result: ResultType) -> int:
    """The exit code a finished run ends the process with."""
    if result in (ResultType.PASS, ResultType.DONE):
        return EXIT_PASSED
    if result is ResultType.FAIL:
        return EXIT_FAILED
    return EXIT_NOT_JUDGED


def headless_main(
    recipe: str, sequence: str | None = None, log_level: str | None = None,
    debug_monitor: bool = False,
) -> int:
    """
    Run one sequence of one recipe and return the process exit code.

    Args:
        recipe: path to the recipe file.
        sequence: which sequence; None runs the recipe's main sequence.
        log_level: overrides [logging] level in config.ini, as --log-level.
        debug_monitor: open the Debug Monitor on this run's log.
    """
    recipe_path = Path(recipe)
    if not recipe_path.is_file():
        # Checked before anything is started, so a typo costs nothing.
        print(f"Recipe file not found: {recipe_path.resolve()}", file=sys.stderr)
        return EXIT_NOT_RUN

    try:
        pts = HeadlessPts(log_level=log_level, debug_monitor=debug_monitor)
    except Exception as error:  # noqa: BLE001 - any start failure is exit code 3, said in one line
        print(f"pypts could not start: {error}", file=sys.stderr)
        return EXIT_NOT_RUN

    with pts:
        try:
            loaded = pts.load_recipe(recipe_path)
            print(f"Recipe loaded: {loaded.name} (version {loaded.version})")
            for warning in loaded.warnings:
                print(f"WARNING {warning}")

            if sequence is not None and sequence not in loaded.sequences:
                print(
                    f"The recipe has no sequence '{sequence}'. "
                    f"It has: {', '.join(loaded.sequences)}",
                    file=sys.stderr,
                )
                return EXIT_NOT_RUN

            if sequence is None:
                print(f"Running sequence {loaded.main_sequence}")
            else:
                print(f"Running sequence {sequence}")
            result = pts.run(sequence=sequence, answer=decline_question, on_step=print_step)
        except PtsError as error:
            print(str(error), file=sys.stderr)
            return EXIT_NOT_RUN
        except KeyboardInterrupt:
            # Leaving the `with` shuts the engine down; the run did not finish.
            print("Interrupted, shutting pypts down.", file=sys.stderr)
            return EXIT_NOT_JUDGED

    print_result(result)
    return exit_code_for(result.result)


def decline_question(request: Question) -> None:
    """Nobody is there to answer: say so on the console and decline."""
    print(f"  Question declined (headless mode): {request.message}")
    log.warning(
        "Headless mode cannot answer the question '%s', so it was declined.", request.message
    )


def print_step(step: StepVerdict) -> None:
    line = f"  {step.name}: {step.result}"
    if step.info:
        line = f"{line} - {step.info}"
    print(line)
    for values_line in describe_step_values(step.inputs, step.outputs, step.expectations):
        print(f"      {values_line}")


def print_result(result: RunResult) -> None:
    for error in result.errors:
        print(f"ERROR {error}")
    print(f"Run finished: {result.result} ({len(result.steps)} steps)")
    if result.report_dir is not None:
        print(f"Report: {result.report_dir}")
