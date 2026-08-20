# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The concrete step types.

Two so far: WaitStep, and a deliberately minimal PythonModuleStep (`method`
calls only - the old `read_attribute`/`write_attribute` actions and the rglob
module search stay in old_code until the module-loading design is settled;
this port resolves `module:` against the recipe's own folder, or imports a
dotted name). The other eight are ported as their dependencies land: the four
User* types need the request/response prompt wiring, SequenceStep/IndexedStep
need nesting, the SSH pair needs the credentials-in-config decision. Every
type is documented with its YAML in section 10 of
resources/roadmap/recipe_guide.md.
"""

import importlib
import importlib.util
import time
from pathlib import Path
from types import ModuleType
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


def load_python_module(module_ref: str, base_dir: str) -> ModuleType:
    """
    Turn a recipe's `module:` value into a loaded module.

    Two spellings, tried in this order:
    - a file beside the recipe: `example_tests.py` or `example_tests`,
      resolved against `base_dir` (or an absolute path). Loaded from the
      file directly, without touching sys.modules.
    - a dotted import name: `platform`, `mypackage.tests` - a plain import,
      so stdlib and installed code work too.

    Deliberately not ported: the old engine's recursive project-wide search
    for the file (old_code/steps.py __load_module) - a heuristic with a bare
    except at its heart. Here the recipe says where its code is.
    """
    candidates = []
    reference = Path(module_ref)
    if reference.is_absolute():
        candidates.append(reference)
        if reference.suffix != ".py":
            candidates.append(reference.with_suffix(".py"))
    else:
        base = Path(base_dir) if base_dir else Path()
        candidates.append(base / module_ref)
        if reference.suffix != ".py":
            candidates.append(base / (module_ref + ".py"))

    for candidate in candidates:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                f"pypts_recipe_module_{candidate.stem}", candidate
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load a module from '{candidate}'")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    if not module_ref.endswith(".py"):
        try:
            return importlib.import_module(module_ref)
        except ImportError as error:
            raise ImportError(
                f"Module '{module_ref}' is neither a file next to the recipe "
                f"(looked in '{base_dir or '.'}') nor an importable name: {error}"
            ) from error
    raise ImportError(
        f"Module file '{module_ref}' not found next to the recipe (looked in "
        f"'{base_dir or '.'}')"
    )


class PythonModuleStep(Step):
    """
    Call one function of a Python module; its return value is the output.
    Named `PythonModule` in a recipe's `steptype:`.

    The minimal port: `action_type: method` only. The resolved inputs become
    the function's keyword arguments, and the base class judges whatever
    comes back (a non-dict return is wrapped as {"output": value}).
    """

    def __init__(
        self,
        module: str,
        method_name: str | None = None,
        action_type: str = "method",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.module = module
        self.method_name = method_name
        if action_type != "method":
            raise ValueError(
                f"Step '{self.name}': action_type {action_type!r} is not ported yet - "
                f"only 'method' is (read_attribute/write_attribute live in old_code)"
            )
        if not method_name:
            raise ValueError(f"Step '{self.name}': method_name is required")

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        module = load_python_module(self.module, runtime.base_dir)
        if not hasattr(module, str(self.method_name)):
            raise AttributeError(
                f"Module '{self.module}' has no function '{self.method_name}'"
            )
        method = getattr(module, str(self.method_name))
        log.info("Calling %s.%s(%s)", self.module, self.method_name, step_input)
        return method(**step_input)
