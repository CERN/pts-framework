# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
UserInteractionStep - ask the operator a question and wait for the answer.

The first step type that *blocks on a person*. Everything it needs already
existed - UserPromptRequest/Response, CORE's relay both ways, the GUI's prompt
page, PendingRequests - and the only thing missing was a step that asks. It
asks through one seam, `Runtime.ask`, which the Sequencer fills with
ask_operator(); the step never sees a queue and cannot get the ordering wrong.

The question's fields sit **directly on the step**, the way WaitStep's
wait_time does rather than the way PythonModuleStep's input_mapping does:

    - steptype: UserInteraction
      step_name: Check the LED
      message: Is the red LED lit?
      options: [Yes, No]
      image_path: led.png
      output_mapping:
        output: {type: equals, value: Yes}

The chosen option comes back as the step's output, so the ordinary
output_mapping vocabulary judges it (`equals`) or stores it (`local`,
`global`) with no machinery of its own.

**Not answering is an ERROR.** Timed out, Cancel pressed, run stopped - one
rule, no special cases. The exception text says which it was because that is
worth reading; the verdict does not change. The sequence carries on to the
next step (see Step.run_steps), so one unanswered question does not throw the
remaining nineteen away.
"""

import uuid
from pathlib import Path
from typing import Any

from pypts.logger.log import log
from pypts.messages.run_events import UserPromptRequest
from pypts.step.runtime import Runtime
from pypts.step.step import Step


class PromptUnanswered(Exception):
    """Nobody answered the question: timed out, cancelled, or the run stopped."""


class UserInteractionStep(Step):
    """
    Show the operator a message and some buttons; their choice is the output.
    Named `UserInteraction` in a recipe's `steptype:`.
    """

    def __init__(
        self,
        message: str,
        options: Any,
        image_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.message = str(message)
        # YAML gives a list, the message carries a tuple; a non-string option
        # is coerced rather than refused, so `options: [1, 2]` works and the
        # answer that comes back is comparable with what the recipe wrote.
        self.options: tuple[str, ...] = tuple(str(option) for option in options or ())
        self.image_path = image_path
        if not self.options:
            raise ValueError(
                f"Step '{self.name}': 'options' must list at least one button. "
                f"With none the operator has no way to answer, so the step could "
                f"only ever time out."
            )

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        request = UserPromptRequest(
            request_id=uuid.uuid4(),
            message=self.message,
            options=self.options,
            image_path=self.resolve_image_path(runtime.base_dir),
        )
        log.info("Step '%s': asking the operator: %s", self.name, self.message)
        answer = runtime.ask(request)
        if answer is None:
            if runtime.should_stop():
                raise PromptUnanswered(
                    f"Step '{self.name}': the run was stopped before the operator answered."
                )
            raise PromptUnanswered(
                f"Step '{self.name}': no answer - the operator cancelled, or nothing "
                f"came back before the timeout."
            )
        log.info("Step '%s': the operator answered %r.", self.name, answer)
        return answer

    def resolve_image_path(self, base_dir: str) -> str | None:
        """
        Turn the recipe's `image_path` into an absolute path that exists.

        Absolute because the HMI is a different process and the request is
        pickled to it - a relative path would be resolved against whatever
        directory that process happens to be in. Relative values resolve
        against the recipe's own folder, the way a PythonModule step's
        `module:` does, so an image lives beside the recipe that shows it.

        A path that does not exist raises **here**, before the request is
        sent. The GUI's own handling of a bad path is to fall back to the
        idle logo (interaction_panel._refresh_visual), which would leave the
        operator looking at the wrong picture with nothing said about it.
        """
        if not self.image_path:
            return None
        path = Path(self.image_path)
        if not path.is_absolute():
            base = Path(base_dir) if base_dir else Path()
            path = base / path
        if not path.is_file():
            raise FileNotFoundError(
                f"Step '{self.name}': image '{self.image_path}' not found "
                f"(looked in '{base_dir or '.'}'). Give a path relative to the "
                f"recipe's own folder, or an absolute one."
            )
        return str(path.resolve())
