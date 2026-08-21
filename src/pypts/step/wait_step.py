# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
WaitStep - sleep for a fixed time.

One concrete step type per module; the package docstring in __init__.py
holds the map of the ported types and of what still lives in old_code.
"""

import time
from typing import Any

from pypts.logger.log import log
from pypts.step.runtime import Runtime
from pypts.step.step import Step


class WaitStep(Step):
    """
    Sleep for `wait_time` seconds. The simplest step there is.
    Named `Wait` in a recipe's `steptype:`.

    It exists to pace a sequence around slow hardware, and here also as the
    first ported type: it exercises the whole base lifecycle with no
    dependencies at all. `wait_time` is written directly on the step - a
    fixed wait has no inputs to resolve and no outputs to judge, so it
    carries no input_mapping and no output_mapping. Returns {} - with no
    output to judge, the verdict is DONE.
    """

    def __init__(self, wait_time: float | str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.wait_time = wait_time

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> dict[str, Any]:
        wait_time = float(self.wait_time)
        if wait_time < 0:
            raise ValueError(f"wait_time must not be negative, got {wait_time}")
        log.info("Waiting %s s.", wait_time)
        # TODO(roadmap): sleep in slices and honour runtime.should_stop(), so a
        # long wait does not hold up an abort. The framework contract only
        # promises a stop at the next step boundary, so this is a courtesy.
        time.sleep(wait_time)
        return {}
