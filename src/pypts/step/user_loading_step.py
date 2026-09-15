# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
UserLoadingStep - ask the operator to pick a file or a folder, and keep the path.

The third operator question, beside UserInteraction (a choice) and UserWrite
(a line of text). The recipe needs a path only the person at the bench knows -
the calibration file for this unit, the folder a fixture wrote its dump to.

    - steptype: UserLoading
      step_name: pick_calibration_file
      message: Select the calibration file for this unit.
      select: file
      image_path: cal.png
      outputs:
        output: {type: global, global_name: calibration_file}

The chosen path is the step's output, so the ordinary outputs vocabulary
stores it in a global for later steps to read, with no machinery of its own.

**One request, one response.** The old type pushed the button onto the
response queue first and the chosen path after it, a second untyped value
nothing in the new message layer could model. Here the step sends one
UserPathRequest and gets one UserPathResponse carrying the path, joined by
`request_id` like the other two questions.

**`select` is `file` (the default) or `folder`**, case-insensitive like every
other structural word in a recipe, and anything else is refused when the recipe
loads. There is deliberately no file filter, no start folder and no
"must exist" switch.

**The answer is checked again here.** A frontend is expected to accept only an
existing path of the right kind, but the step does not trust it: a path that
does not exist, or a file where a folder was asked for (or the other way
round), is an ERROR naming the path. What is stored is the absolute, resolved
path as a string.
"""

import uuid
from pathlib import Path
from typing import Any

from pypts.logger.log import log
from pypts.messages.run_events import UserPathRequest
from pypts.step.operator_prompt import ask_or_raise, resolve_image_path
from pypts.step.runtime import Runtime
from pypts.step.step import Step

#: What `select:` may say. The first is the default (recipe/rules.py).
SELECT_FILE = "file"
SELECT_FOLDER = "folder"
SELECT_VALUES: tuple[str, ...] = (SELECT_FILE, SELECT_FOLDER)


class UserLoadingStep(Step):
    """
    Show the operator a message and a file or folder chooser; the chosen path
    is the output. Named `UserLoading` in a recipe's `steptype:`.
    """

    def __init__(
        self,
        message: str,
        select: str = SELECT_FILE,
        image_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.message = str(message)
        self.image_path = image_path
        # Lowercased like a steptype or an outputs `type`, so `select: Folder`
        # works; the message always carries the lowercase word.
        self.select = str(select).strip().lower()
        if self.select not in SELECT_VALUES:
            raise ValueError(
                f"Step '{self.name}': 'select' must be 'file' or 'folder', "
                f"not '{select}'."
            )

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        request = UserPathRequest(
            request_id=uuid.uuid4(),
            message=self.message,
            select=self.select,
            image_path=resolve_image_path(self.name, self.image_path, runtime.base_dir),
        )
        log.info("Waiting for the operator to choose a %s: '%s'", self.select, self.message)
        log.debug("Step '%s' asked request %s.", self.name, request.request_id)
        answer = ask_or_raise(self.name, runtime, request)
        chosen = self.check_answer(str(answer))
        log.info("The operator chose: '%s'.", chosen)
        return chosen

    def check_answer(self, answer: str) -> str:
        """
        Return the answer as an absolute, resolved path, or raise.

        The frontend should already have refused anything else; this is the
        step not taking that on trust. An empty answer is refused explicitly,
        because Path("") is the current directory and would pass as a folder.
        """
        if not answer.strip():
            raise FileNotFoundError(
                f"Step '{self.name}': the operator's answer was an empty path."
            )
        path = Path(answer)
        if not path.exists():
            raise FileNotFoundError(
                f"Step '{self.name}': the chosen path '{answer}' does not exist."
            )
        if self.select == SELECT_FILE and not path.is_file():
            raise IsADirectoryError(
                f"Step '{self.name}': a file was asked for, but '{answer}' is not a file."
            )
        if self.select == SELECT_FOLDER and not path.is_dir():
            raise NotADirectoryError(
                f"Step '{self.name}': a folder was asked for, but '{answer}' is not a folder."
            )
        return str(path.resolve())
