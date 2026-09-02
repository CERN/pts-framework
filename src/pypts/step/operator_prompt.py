# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What the two step types that put a question on the operator's screen share.

`UserInteraction` asks for a choice and `UserWrite` asks for a line of text,
but they resolve their picture the same way and they treat an unanswered
question the same way. Both live here as plain functions rather than as a
base class, so the rule in step.md section 4 still holds: a step type
subclasses Step, overrides `_step()` and nothing else.
"""

from pathlib import Path
from typing import Any

from pypts.step.runtime import PromptUnanswered, Runtime


def resolve_image_path(step_name: str, image_path: str | None, base_dir: str) -> str | None:
    """
    Turn a recipe's `image_path` into an absolute path that exists.

    Absolute because the HMI is a different process and the request is pickled
    to it - a relative path would be resolved against whatever directory that
    process happens to be in. Relative values resolve against the recipe's own
    folder, the way a PythonModule step's `module:` does, so an image lives
    beside the recipe that shows it.

    A path that does not exist raises **here**, before the request is sent. The
    GUI's own handling of a bad path is to fall back to the idle logo
    (interaction_panel._refresh_visual), which would leave the operator looking
    at the wrong picture with nothing said about it.
    """
    if not image_path:
        return None
    path = Path(image_path)
    if not path.is_absolute():
        if base_dir:
            base = Path(base_dir)
        else:
            base = Path()
        path = base / path
    if not path.is_file():
        raise FileNotFoundError(
            f"Step '{step_name}': image '{image_path}' not found "
            f"(looked in '{base_dir or '.'}'). Give a path relative to the "
            f"recipe's own folder, or an absolute one."
        )
    return str(path.resolve())


def ask_or_raise(step_name: str, runtime: Runtime, request: Any) -> Any:
    """
    Put the question and return the answer, or raise PromptUnanswered.

    **Not answering is an ERROR.** One rule, no special cases: the timeout ran
    out, the operator pressed Cancel, or the run was stopped. The exception
    text distinguishes them because that is worth reading; the verdict does
    not change. Step.run_steps carries on to the next step, so one unanswered
    question does not throw the rest of the sequence away.
    """
    answer = runtime.ask(request)
    if answer is None:
        if runtime.should_stop():
            raise PromptUnanswered(
                f"Step '{step_name}': the run was stopped before the operator answered."
            )
        raise PromptUnanswered(
            f"Step '{step_name}': no answer - the operator cancelled, or nothing "
            f"came back before the timeout."
        )
    return answer
