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
wait_time does rather than the way PythonModuleStep's `inputs` entries do:

    - steptype: UserInteraction
      step_name: Check the LED
      message: Is the red LED lit?
      options: [Yes, No]
      image_path: led.png
      outputs:
        output: {type: equals, value: Yes}

The chosen option comes back as the step's output, so the ordinary
outputs vocabulary judges it (`equals`) or stores it (`local`,
`global`) with no machinery of its own.

**Not answering is an ERROR.** Timed out, Cancel pressed, run stopped - one
rule, no special cases, applied by `operator_prompt.ask_or_raise` for this
type and for UserWrite alike.
"""

import uuid
from typing import Any

from pypts.logger.log import log
from pypts.messages.run_events import UserPromptRequest
from pypts.step.operator_prompt import ask_or_raise, resolve_image_path
from pypts.step.runtime import Runtime
from pypts.step.step import Step


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
            image_path=resolve_image_path(self.name, self.image_path, runtime.base_dir),
        )
        log.info("Step '%s': asking the operator: %s", self.name, self.message)
        answer = ask_or_raise(self.name, runtime, request)
        log.info("Step '%s': the operator answered %r.", self.name, answer)
        return answer
