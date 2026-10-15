# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
PythonModuleStep - call one function of a Python module.

Calling a method is the whole of this type: the old
`read_attribute`/`write_attribute` actions are dropped, and so is the
`action_type` key that selected between them - a recipe that wants an
attribute writes a one-line getter beside it and calls that. `module:`
resolves against the recipe's own folder, or imports a dotted name - the old
rglob search is gone too.

One concrete step type per module; the package docstring in __init__.py
holds the map of the ported types and of what still lives in old_code.
"""

import ast
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from pypts.logger.log import log
from pypts.step.runtime import Runtime
from pypts.step.step import Step

#: Every module file loaded so far, keyed by its resolved path. A test module
#: is loaded once per process, as the old engine's import_module did, so a
#: handle a `connect()` step keeps at module level is still there for the next
#: step. The full path is the key because two recipes may each have an
#: `example_tests.py` in their own folder. Only the sequence thread loads
#: modules, one run at a time, so there is no lock.
_loaded_modules: dict[Path, ModuleType] = {}


def forget_loaded_modules() -> int:
    """
    Drop every module file loaded so far, so the next use reads it afresh.

    Called when the operator unloads the recipe (Sequencer.forget_recipe), and
    never while a sequence runs - the sequence thread is the only reader. Only
    the file modules: they never touched sys.modules, so nothing else holds
    them. Dotted-name imports stay where importlib cached them.

    Returns:
        How many modules were dropped.
    """
    count = len(_loaded_modules)
    _loaded_modules.clear()
    return count


def load_python_module(module_ref: str, base_dir: str) -> ModuleType:
    """
    Turn a recipe's `module:` value into a loaded module.

    Two spellings, tried in this order:
    - a file beside the recipe: `example_tests.py` or `example_tests`,
      resolved against `base_dir` (or an absolute path). Loaded from the
      file directly, without touching sys.modules, and only the first time:
      later calls get the same module object back from _loaded_modules.
      A file that fails to load is not remembered, so it is tried again.
    - a dotted import name: `platform`, `mypackage.tests` - a plain import,
      so stdlib and installed code work too.

    Deliberately not ported: the old engine's recursive project-wide search
    for the file (old_code/steps.py __load_module) - a heuristic with a bare
    except at its heart. Here the recipe says where its code is.
    """
    path = _module_file_beside(module_ref, base_dir)
    if path is not None:
        if path in _loaded_modules:
            return _loaded_modules[path]
        spec = importlib.util.spec_from_file_location(f"pypts_recipe_module_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load a module from '{path}'")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _loaded_modules[path] = module
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


def _module_file_beside(module_ref: str, base_dir: str) -> Path | None:
    """
    The file a `module:` value names - beside the recipe, or absolute - resolved.

    None when there is no such file, which for load_python_module() means the
    value is a dotted import name instead.
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
            return candidate.resolve()
    return None


def find_module_file(module_ref: str, base_dir: str) -> Path | None:
    """
    The source file a `module:` value would run, found without running it.

    The same two spellings, in the same order, as load_python_module() - so the
    GUI's "Open Python file" opens the file a run would use. A dotted name is
    looked up with `importlib.util.find_spec`, which does not execute the
    module itself; for `pkg.sub` Python does import `pkg` to find `sub`.

    None when there is nothing to open: no such file or module, or a module
    with no source file of its own (a built-in, a compiled extension). This is
    a convenience lookup, so it never raises.
    """
    path = _module_file_beside(module_ref, base_dir)
    if path is not None:
        return path
    if module_ref.endswith(".py"):
        return None
    try:
        spec = importlib.util.find_spec(module_ref)
    except Exception as error:  # noqa: BLE001 - a parent package's import may raise anything
        log.debug("No source file found for module '%s': %s", module_ref, error)
        return None
    if spec is None or not spec.has_location or spec.origin is None:
        return None
    origin = Path(spec.origin)
    if origin.suffix != ".py" or not origin.is_file():
        return None
    return origin


def module_method_problem(module_ref: str, method_name: str, base_dir: str) -> str | None:
    """
    What is wrong with a `module:`/`method_name:` pair, found without running it.

    The recipe parser asks this at load time, so a typo in step 9 is said
    before step 1 has driven hardware. Only the file-beside-the-recipe
    spelling is checked: a dotted name would need its parent package imported
    (a side effect the load must not have), so it returns None, unchecked.
    The file itself is never executed - its text is read and AST-scanned for
    a top-level binding of `method_name`: a def, a class, an import or an
    assignment, looked for inside top-level if/try/with blocks too. A
    `from x import *` may bind anything, so it mutes the check.

    An advisory, not a verdict: a module may build its attributes dynamically,
    which is why the parser warns and never refuses.

    Returns:
        One sentence naming the problem, or None when none was found.
    """
    path = _module_file_beside(module_ref, base_dir)
    if path is None:
        if module_ref.endswith(".py"):
            return (
                f"module file '{module_ref}' not found next to the recipe "
                f"(looked in '{base_dir or '.'}')"
            )
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as error:
        return f"module '{module_ref}' cannot be read as Python: {error}"
    names = _top_level_names(tree.body)
    if names is None or method_name in names:
        return None
    return f"module '{module_ref}' has no function '{method_name}' at its top level"


def _top_level_names(body: list[ast.stmt]) -> set[str] | None:
    """
    Every name the statements bind at module level; None on a star import.

    Defs, classes, imports and plain assignments, recursing into the branches
    of if/try/with - the common homes of a conditional def. Deliberately no
    deeper (a def inside a function is not an attribute of the module).
    """
    names: set[str] = set()
    for statement in body:
        blocks: list[list[ast.stmt]] = []
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                names.update(_target_names(target))
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
            names.update(_target_names(statement.target))
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                names.add(alias.asname or alias.name.partition(".")[0])
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name == "*":
                    return None
                names.add(alias.asname or alias.name)
        elif isinstance(statement, ast.If):
            blocks = [statement.body, statement.orelse]
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            handler_bodies = [handler.body for handler in statement.handlers]
            blocks = [statement.body, statement.orelse, statement.finalbody, *handler_bodies]
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            blocks = [statement.body]
        for block in blocks:
            inner = _top_level_names(block)
            if inner is None:
                return None
            names.update(inner)
    return names


def _target_names(target: ast.expr) -> set[str]:
    """The plain names an assignment target binds (`a = `, `a, b = `)."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_target_names(element))
        return names
    return set()


class PythonModuleStep(Step):
    """
    Call one function of a Python module; its return value is the output.
    Named `PythonModule` in a recipe's `steptype:`.

    Methods only. The resolved inputs become the function's keyword
    arguments, and the base class judges whatever comes back (a non-dict
    return is wrapped as {"output": value}).
    """

    def __init__(
        self,
        module: str,
        method_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.module = module
        self.method_name = method_name
        if not method_name:
            raise ValueError(f"Step '{self.name}': method_name is required")

    def _step(self, runtime: Runtime, step_input: dict[str, Any]) -> Any:
        module = load_python_module(self.module, runtime.base_dir)
        if not hasattr(module, str(self.method_name)):
            raise AttributeError(
                f"Module '{self.module}' has no function '{self.method_name}'"
            )
        method = getattr(module, str(self.method_name))
        # The call itself is the developer's business: the operator already has
        # the step's own started/finished lines around it, and the argument
        # values are exactly the kind of internals logging_rules.md keeps at DEBUG.
        log.debug("Calling %s.%s(%r).", self.module, self.method_name, step_input)
        result = method(**step_input)
        log.debug("%s.%s returned %r.", self.module, self.method_name, result)
        return result
