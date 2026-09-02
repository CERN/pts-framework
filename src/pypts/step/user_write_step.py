# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
UserWriteStep - ask the operator to type something, and keep what they typed.

The free-text half of the operator interaction pair. UserInteraction asks for
a choice between buttons the recipe wrote; this one asks for a value only the
person in front of the bench knows - a serial number, a batch code, a meter
reading off an instrument that has no interface.

    - steptype: UserWrite
      step_name: get_serial_number
      message: Scan or type the serial number of the unit under test
      image_path: label_location.png
      outputs:
        output: {type: global, global_name: serial_number}

The typed string is the step's output, so the ordinary outputs
vocabulary stores it (`global`, `local`) or judges it (`equals`, `passfail`)
with no machinery of its own.

**The framework has no opinion about what is being asked for.** An earlier
design had a SerialNumberRequest message and a serial-number page in the GUI,
which meant the engine itself believed every unit under test has a serial
number and went and fetched it. Asking is the recipe's job. What the framework
supplies is the prompt and the global scope to keep the answer in; the
convention that the global is called `serial_number` and the step is called
`get_serial_number` is documented in resources/roadmap/best_practices.md and
is a recommendation, not a rule - the Report picks up whichever globals the
recipe's `report_metadata` header names.

**There is no `allow_empty` field.** The GUI keeps OK disabled while the field
is empty, so the only answers that exist are some text or Cancel, and one less
key has to be spelled in a recipe that wants the obvious behaviour.
"""

import uuid
from typing import Any

from pypts.logger.log import log
from pypts.messages.run_events import UserTextRequest
from pypts.step.operator_prompt import ask_or_raise, resolve_image_path
from pypts.step.runtime import Runtime
from pypts.step.step import Step


class UserWriteStep(Step):
    """
    Show the operator a message and a text field; what they type is the output.
    Named `UserWrite` in a recipe's `steptype:`.
    """

    def __init__(
        self,
        message: str,
        image_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.message = str(message)
        self.image_path = image_path

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        request = UserTextRequest(
            request_id=uuid.uuid4(),
            message=self.message,
            image_path=resolve_image_path(self.name, self.image_path, runtime.base_dir),
        )
        log.info("Waiting for the operator to type: '%s'", self.message)
        log.debug("Step '%s' asked request %s.", self.name, request.request_id)
        answer = ask_or_raise(self.name, runtime, request)
        log.info("The operator typed: '%s'.", answer)
        return answer
